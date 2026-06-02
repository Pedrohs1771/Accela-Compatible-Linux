import logging
import os
import sys
import threading
import re
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal, QCoreApplication

from core.steam_helpers import (
    get_steam_libraries,
    get_library_index,
    find_steam_install,
)
from core.tasks.manifest_check_task import ManifestCheckTask
from utils.helpers import get_base_path
from utils.task_runner import TaskRunner
from utils.yaml_config_manager import (
    get_user_config_path,
    add_additional_app,
    remove_additional_app,
    fix_slssteam_config_indentation,
    get_app_tokens,
    add_app_token,
    is_greenluma_wrapper_mode_enabled,
    is_slssteam_mode_enabled,
)
from utils.wrapper_metadata import load_selected_dlcs, persist_selected_dlcs

logger = logging.getLogger(__name__)

# Update status constants
UPDATE_STATUS = {
    "UPDATE_AVAILABLE": "update_available",
    "UP_TO_DATE": "up_to_date",
    "CANNOT_DETERMINE": "cannot_determine",
    "CHECKING": "checking",  # While async update check is running
}


class GameManager(QObject):
    """
    Manager for handling game library operations.
    Manages game metadata, library view, and game-related operations.
    """

    # Signals
    game_updated = pyqtSignal(str)
    library_updated = pyqtSignal()
    game_selected = pyqtSignal(str)
    scan_complete = pyqtSignal(int)  # Emits number of games found
    game_update_status_changed = pyqtSignal(str, str)  # (appid, update_status)

    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.settings = main_window.settings

        # Game library data
        self.games = []
        self.selected_game = None
        self.filtered_games = []

        # Manifest check task management
        self.manifest_check_task = None
        self.manifest_check_runner = None
        self._games_to_check = []

        # Library scan task management
        self.scan_runner = None
        self._scan_cancelled = False
        self._scan_generation = 0

        logger.info("GameManager initialized")

    @staticmethod
    def _get_sorted_games(games_list):
        """Helper method to sort games by name (case-insensitive)"""
        return sorted(games_list, key=lambda x: x.get("game_name", "").lower())

    def add_game(self, game_data):
        """Add a game to the library"""
        # TODO: Implement game addition logic
        logger.info(f"Adding game to library: {game_data.get('game_name', 'Unknown')}")
        self.games.append(game_data)
        # Sort the main games list
        self.games = self._get_sorted_games(self.games)
        self._apply_filters()
        self.library_updated.emit()

    def remove_game(self, game_id):
        """Remove a game from the library"""
        # TODO: Implement game removal logic
        logger.info(f"Removing game from library: {game_id}")
        self.games = [g for g in self.games if g.get("appid") != game_id]
        # Sort the main games list
        self.games = self._get_sorted_games(self.games)
        self._apply_filters()
        self.library_updated.emit()

    def get_game(self, game_id):
        """Get a specific game by ID"""
        for game in self.games:
            if game.get("appid") == game_id:
                return game
        return None

    def get_all_games(self):
        """Get all games in the library - returns sorted list"""
        games_to_return = self.filtered_games if self.filtered_games else self.games
        return self._get_sorted_games(games_to_return)

    def select_game(self, game_id):
        """Select a specific game"""
        game = self.get_game(game_id)
        if game:
            self.selected_game = game
            self.game_selected.emit(game_id)
            logger.info(
                f"Selected game: {game.get('game_name', 'Unknown')} ({game_id})"
            )
            return True
        return False

    def update_game(self, game_id, game_data):
        """Update game information"""
        # TODO: Implement game update logic
        logger.info(f"Updating game: {game_id}")
        for i, game in enumerate(self.games):
            if game.get("appid") == game_id:
                self.games[i].update(game_data)
                # Sort the main games list after update
                self.games = self._get_sorted_games(self.games)
                self.game_updated.emit(game_id)
                self._apply_filters()
                self.library_updated.emit()
                return True
        return False

    def _apply_filters(self):
        """Apply current filters to the game list"""
        # TODO: Implement filtering logic
        self.filtered_games = self._get_sorted_games(self.games)

    def search_games(self, query):
        """Search games by name or other criteria"""
        # TODO: Implement search functionality
        if not query:
            self.filtered_games = []
            self._apply_filters()
            self.library_updated.emit()
            return

        query = query.lower()
        matched_games = [
            game for game in self.games if query in game.get("game_name", "").lower()
        ]
        self.filtered_games = self._get_sorted_games(matched_games)
        self.library_updated.emit()

    def clear_filters(self):
        """Clear all applied filters"""
        self.filtered_games = []
        self._apply_filters()
        self.library_updated.emit()

    def check_game_updates_async(self):
        """
        Start async update checking for all games in the library.
        Games appear with 'checking' status initially, then update individually.
        """
        # Cancel any existing task by stopping it and waiting for cleanup
        if (
            self.manifest_check_task is not None
            or self.manifest_check_runner is not None
        ):
            logger.info("Cancelling previous manifest check task")
            self.cancel_update_checks()

        # Get games with valid appids
        self._games_to_check = [
            g for g in self.games if g.get("appid") not in ("0", "N/A", "unknown")
        ]

        if not self._games_to_check:
            logger.info("No games with valid appids to check")
            return

        logger.info(
            f"Starting async update check for {len(self._games_to_check)} games"
        )

        # Create new task
        self.manifest_check_task = ManifestCheckTask(self._games_to_check)

        # Connect signals
        self.manifest_check_task.game_update_checked.connect(
            self._on_game_update_checked
        )
        self.manifest_check_task.progress.connect(self._on_update_check_progress)
        self.manifest_check_task.completed.connect(self._on_update_check_completed)
        self.manifest_check_task.error.connect(self._on_update_check_error)

        # Start task via TaskRunner
        self.manifest_check_runner = TaskRunner()
        # Connect to cleanup_complete to clear references AFTER thread finishes
        self.manifest_check_runner.cleanup_complete.connect(
            self._on_manifest_check_runner_cleanup
        )
        self.manifest_check_runner.run(self.manifest_check_task.run)

    def _on_game_update_checked(self, appid, update_status):
        """Handle individual game update check result"""
        # Find and update the game
        for game in self.games:
            if game.get("appid") == appid:
                game["update_status"] = update_status
                logger.debug(f"Updated status for game {appid}: {update_status}")
                # Emit specific signal for individual game update (UI can choose to update just that item)
                self.game_update_status_changed.emit(appid, update_status)
                break

    @staticmethod
    def _on_update_check_progress(current, total):
        """Handle update check progress"""
        logger.debug(f"Update check progress: {current}/{total}")

    @staticmethod
    def _on_update_check_completed():
        """Handle update check completion"""
        logger.info("All game updates checked")
        # Note: We don't clear references here
        # They will be cleared by _on_manifest_check_runner_cleanup when thread finishes

    @staticmethod
    def _on_update_check_error(error_info):
        """Handle update check error"""
        exc_type, exc_msg, exc_traceback = error_info
        logger.error(
            f"Error during update check: {exc_msg}",
            exc_info=(exc_type, exc_msg, exc_traceback),
        )
        # Note: We don't clear references here
        # They will be cleared by _on_manifest_check_runner_cleanup when thread finishes

    def _on_manifest_check_runner_cleanup(self):
        """Handle TaskRunner cleanup completion - called when thread finishes"""
        logger.debug("TaskRunner cleanup complete, clearing references")
        self.manifest_check_task = None
        self.manifest_check_runner = None
        self._games_to_check = []

    def scan_steam_libraries_async(self):
        """
        Start an async scan of Steam library directories for installed Steam games.
        The UI will update automatically when the scan completes via signals.
        """
        logger.info("Starting async scan of Steam libraries for installed Steam games...")

        if self.scan_runner is not None:
            logger.debug("Stopping previous library scan before starting a new one")
            self.cancel_scan()

        # Reset cancel flag
        self._scan_cancelled = False
        self._scan_generation += 1
        generation = self._scan_generation

        # Clear existing games before scanning
        self.games.clear()
        self.filtered_games.clear()

        # Create a worker function that does the scanning
        def do_scan():
            return self._perform_scan(generation)

        # Use TaskRunner to run in background thread
        self.scan_runner = TaskRunner()
        self.scan_runner.cleanup_complete.connect(self._on_scan_runner_cleanup)
        self.scan_runner.run(do_scan)

    def cancel_scan(self):
        """Cancel any in-progress library scan."""
        self._scan_cancelled = True
        if self.scan_runner is not None:
            try:
                self.scan_runner.stop(wait_ms=1000, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping scan runner: {e}")
            self.scan_runner = None

    def _on_scan_runner_cleanup(self):
        self.scan_runner = None

    def _perform_scan(self, generation=None):
        """
        Internal method that performs the actual scan.
        Returns the number of games found.
        """
        if generation is not None and generation != self._scan_generation:
            logger.debug("Ignoring stale scan generation %s", generation)
            return 0

        steam_libraries = get_steam_libraries()

        if not steam_libraries:
            logger.warning("No Steam libraries found")
            return 0

        logger.info(f"Found {len(steam_libraries)} Steam library location(s)")

        games_found = 0
        scanned_libraries = 0

        # Cache the main Steam installation path to avoid repeated lookups
        steam_install_path = find_steam_install()

        for library_path in steam_libraries:
            if self._scan_cancelled:
                logger.info("Scan cancelled before scanning remaining libraries")
                break
            logger.info(f"Scanning library: {library_path}")
            scanned_libraries += 1

            games_found += self._scan_library(library_path, steam_install_path)

        lumatools_games_found = sum(
            1 for game in self.games if game.get("is_lumatools_install")
        )
        logger.info(
            "Scan complete. Scanned %s library location(s), found %s installed Steam "
            "game(s) (%s LumaTools-managed).",
            scanned_libraries,
            games_found,
            lumatools_games_found,
        )

        if self._scan_cancelled or getattr(self.main_window, "_shutdown_started", False):
            logger.info("Scan finished during shutdown/cancel; skipping post-scan work.")
            return games_found

        # Sort games after scanning
        self.games = self._get_sorted_games(self.games)
        self._apply_filters()

        # Fix SLSsteam config indentation if needed (before syncing)
        self._fix_slssteam_config()

        # Sync games to SLSsteam config if integration is enabled
        self._sync_games_to_slssteam_config()

        # Sync missing apptokens from manifests
        self._sync_app_tokens_from_manifests()

        # Emit signals on main thread using QTimer.singleShot
        def update_ui():
            if generation is not None and generation != self._scan_generation:
                logger.debug("Skipping stale UI update for scan generation %s", generation)
                return
            self.library_updated.emit()
            self.scan_complete.emit(games_found)

        QTimer.singleShot(0, update_ui)

        # Start async update checking for all collected games (called directly, not in QTimer)
        # This ensures it always runs even if the UI signals are delayed
        app = QCoreApplication.instance()
        shutting_down = bool(
            getattr(self.main_window, "_shutdown_started", False)
            or (app is not None and app.closingDown())
        )
        if games_found > 0 and not shutting_down:
            logger.info("Starting async update check for collected games")
            self.check_game_updates_async()

        return games_found

    def _scan_library(self, library_path, steam_install_path):
        """Scan a single Steam library for games."""
        games_found = 0
        steamapps_path = os.path.join(library_path, "steamapps")
        if not os.path.exists(steamapps_path):
            logger.warning(f"Steamapps directory not found at: {steamapps_path}")
            return 0

        manifest_index = {}

        # First, scan appmanifest_*.acf files to find all registered games
        manifests_found = 0
        seen_appids = {game.get("appid") for game in self.games}
        seen_paths = {game.get("install_path") for game in self.games}

        try:
            with os.scandir(steamapps_path) as entries:
                for entry in entries:
                    if self._scan_cancelled: break
                    if entry.is_file() and entry.name.startswith("appmanifest_") and entry.name.endswith(".acf"):
                        try:
                            manifest_info = self._parse_manifest_summary(entry.path, entry.name)
                            if not manifest_info:
                                continue

                            appid = manifest_info["appid"]
                            installdir = manifest_info["installdir"]
                            game_name = manifest_info["name"]
                            manifest_index[installdir.lower()] = manifest_info

                            if appid in seen_appids:
                                continue

                            game_path = os.path.join(steamapps_path, "common", installdir)
                            if os.path.exists(game_path) and game_path not in seen_paths:
                                marker_path = self._get_lumatools_marker_path(game_path)
                                game_data = self._collect_game_data(
                                    game_path,
                                    game_name,
                                    library_path,
                                    steam_install_path,
                                    marker_path=marker_path,
                                    appmanifest_path=entry.path,
                                    appid=appid,
                                    install_dir=installdir,
                                )
                                if game_data:
                                    self.games.append(game_data)
                                    seen_appids.add(appid)
                                    seen_paths.add(game_path)
                                    games_found += 1
                                    manifests_found += 1
                        except Exception as e:
                            logger.debug(f"Failed to parse manifest {entry.name}: {e}")
        except OSError as e:
            logger.error(f"Error scanning manifests in {steamapps_path}: {e}")

        # Fallback: Scan common directory for folders not linked to manifests (e.g. manual installs)
        common_path = os.path.join(steamapps_path, "common")
        if os.path.exists(common_path):
            try:
                with os.scandir(common_path) as entries:
                    for entry in entries:
                        if self._scan_cancelled: break
                        if not entry.is_dir(): continue
                        if entry.path in seen_paths: continue
                        
                        if not self._has_game_content(entry.path): continue
                        
                        marker_path = self._get_lumatools_marker_path(entry.path)
                        manifest_info = manifest_index.get(entry.name.lower())
                        game_data = self._collect_game_data(
                            entry.path,
                            entry.name,
                            library_path,
                            steam_install_path,
                            marker_path=marker_path,
                            appmanifest_path=(
                                manifest_info["path"] if manifest_info else None
                            ),
                            appid=(manifest_info["appid"] if manifest_info else None),
                            install_dir=(
                                manifest_info["installdir"] if manifest_info else None
                            ),
                        )
                        if game_data:
                            self.games.append(game_data)
                            seen_paths.add(entry.path)
                            games_found += 1
            except OSError as e:
                logger.error(f"Error scanning {common_path}: {e}")

        return games_found

    @staticmethod
    def _has_game_content(game_path):
        """
        Check if the game folder has actual content beyond LumaTools marker folders.
        Returns True if there are files or folders other than the marker folders.
        """
        try:
            # Common names to ignore (case-insensitive)
            ignore_names = {".lumatools", ".depotdownloader", "desktop.ini", "thumbs.db"}

            with os.scandir(game_path) as entries:
                for entry in entries:
                    try:
                        name = entry.name
                        lname = name.lower()

                        # Skip LumaTools marker folders (case-insensitive)
                        # Skip typical OS metadata files and any hidden file (starts with '.')
                        if lname in ignore_names or name.startswith("."):
                            continue

                        # If we find any file or directory that is not ignored, treat it as content
                        if entry.is_file() or entry.is_dir():
                            return True
                    except (OSError, FileNotFoundError, PermissionError):
                        # Skip entries that can't be accessed
                        continue

            return False
        except OSError:
            return False

    @staticmethod
    def _get_lumatools_marker_path(game_path):
        """Return the LumaTools marker folder path for a game, if present."""
        for marker_name in (".LumaTools", ".DepotDownloader"):
            marker_path = os.path.join(game_path, marker_name)
            if os.path.exists(marker_path):
                return marker_path
        return None

    @staticmethod
    def _fix_slssteam_config():
        """
        Fix indentation of AdditionalApps entries in SLSsteam config.yaml.
        This runs automatically after a scan completes to fix any misformatted
        entries from older versions of LumaTools.
        """
        config_path = get_user_config_path()
        if config_path.exists():
            fix_slssteam_config_indentation(config_path)

    def _sync_games_to_slssteam_config(self):
        """
        Sync found games to SLSsteam AdditionalApps if integration is enabled.
        This runs automatically after a scan completes.
        """
        if not is_slssteam_mode_enabled():
            return

        # Get config path
        config_path = get_user_config_path()
        if not config_path.exists():
            logger.debug("SLSsteam config.yaml not found, skipping sync")
            return

        # Add each game's AppID to AdditionalApps
        added_count = 0
        for game in self.games:
            if not game.get("is_lumatools_install"):
                continue
            appid = game.get("appid")
            game_name = game.get("game_name", "")
            if appid and appid not in ("0", "N/A", "unknown"):
                if add_additional_app(config_path, appid, game_name):
                    added_count += 1

        if added_count > 0:
            logger.info(f"Synced {added_count} game(s) to SLSsteam AdditionalApps")

    def _sync_app_tokens_from_manifests(self):
        """
        Check all ZIPs in morrenus_manifests for apptokens
        and add any missing tokens to config.yaml.
        Called after game library scan completes.
        """
        if not is_slssteam_mode_enabled():
            return

        # Get paths
        config_path = get_user_config_path()
        if not config_path.exists():
            logger.debug("SLSsteam config.yaml not found, skipping token sync")
            return

        manifests_dir = Path(get_base_path()) / "morrenus_manifests"
        if not manifests_dir.exists():
            logger.debug("morrenus_manifests directory not found")
            return

        # Get existing tokens from config
        existing_tokens = get_app_tokens(config_path)
        logger.debug(f"Found {len(existing_tokens)} existing AppTokens in config")

        # Pattern to extract app_id from filename: lumatools_fetch_{app_id}.zip
        zip_pattern = re.compile(r"^lumatools_fetch_(\d+)\.zip$")

        tokens_added = 0
        tokens_skipped = 0

        try:
            for zip_file in manifests_dir.glob("lumatools_fetch_*.zip"):
                match = zip_pattern.match(zip_file.name)
                if not match:
                    continue

                app_id = match.group(1)

                # Skip if token already exists for this app_id
                if app_id in existing_tokens:
                    tokens_skipped += 1
                    continue

                # Extract token from ZIP
                try:
                    with zipfile.ZipFile(zip_file, "r") as zip_ref:
                        lua_files = [
                            f for f in zip_ref.namelist() if f.endswith(".lua")
                        ]
                        if not lua_files:
                            continue

                        lua_content = zip_ref.read(lua_files[0]).decode("utf-8")

                        # Extract token using the same pattern as ProcessZipTask
                        token_pattern = r'addtoken\s*\(\s*\d+\s*,\s*"([^"]+)"\s*\)'
                        token_match = re.search(
                            token_pattern, lua_content, re.IGNORECASE
                        )

                        if not token_match:
                            continue

                        app_token = token_match.group(1)

                        # Add token to config
                        if add_app_token(config_path, app_id, app_token):
                            tokens_added += 1
                            logger.info(
                                f"Added missing AppToken for AppID {app_id} from {zip_file.name}"
                            )
                        else:
                            tokens_skipped += 1

                except Exception as e:
                    logger.warning(f"Failed to extract token from {zip_file.name}: {e}")
                    continue

        except Exception as e:
            logger.error(
                f"Error scanning morrenus_manifests for tokens: {e}", exc_info=True
            )
            return

        if tokens_added > 0:
            logger.info(
                f"Synced {tokens_added} missing AppToken(s) from morrenus_manifests"
            )
        if tokens_skipped > 0:
            logger.debug(f"Skipped {tokens_skipped} AppToken(s) that already exist")

    def _collect_game_data(
        self,
        game_path,
        game_name,
        library_path,
        steam_path=None,
        marker_path=None,
        appmanifest_path=None,
        appid=None,
        install_dir=None,
    ):
        """
        Collect game data from installation directory.
        Returns a dictionary with game information.
        """
        try:
            if self._scan_cancelled:
                return None

            marker_path = marker_path or self._get_lumatools_marker_path(game_path)
            is_lumatools_install = bool(marker_path)

            # Try to read appmanifest to get AppID and other metadata
            if not appmanifest_path and not appid:
                appmanifest_path, appid = self._parse_acf_for_appid(library_path, game_name)

            # Warn if AppID could not be determined
            if not appid:
                logger.warning(
                    f"FAILED to determine AppID for '{game_name}'. Game will have AppID='0' (unknown). This may happen if the ACF file's installdir doesn't match the folder name exactly."
                )

            # Initialize game data dictionary early so we can populate it
            # Determine install directory name
            install_dir = install_dir or game_name

            game_data = {
                "appid": appid or "0",
                "game_name": game_name,
                "install_dir": install_dir,
                "install_path": game_path,
                "library_path": library_path,
                "library_index": get_library_index(library_path, steam_path),
                "size_on_disk": 0,  # Will be calculated below
                "source": "LumaTools" if is_lumatools_install else "Steam",
                "is_lumatools_install": is_lumatools_install,
                "depot_downloader_path": marker_path or "",
                "lumatools_marker_path": marker_path or "",
                "appmanifest_path": appmanifest_path or "",
            }

            # Load persisted wrapper metadata (selected DLC IDs) for uninstall cleanup.
            if is_lumatools_install:
                persisted_selected_dlcs = load_selected_dlcs(game_path)
                if persisted_selected_dlcs:
                    game_data["selected_dlcs"] = persisted_selected_dlcs
                    # Keep compatibility with existing cleanup path that expects a dlcs mapping.
                    game_data["dlcs"] = {
                        dlc_id: "" for dlc_id in persisted_selected_dlcs
                    }
                elif os.name == "nt" and appid and appid not in ("0", "N/A", "unknown"):
                    # Best-effort migration for older installs without persisted DLC metadata.
                    inferred_selected_dlcs = (
                        self._infer_selected_dlcs_from_applist_and_manifest(appid)
                    )
                    if inferred_selected_dlcs:
                        game_data["selected_dlcs"] = inferred_selected_dlcs
                        game_data["dlcs"] = {
                            dlc_id: "" for dlc_id in inferred_selected_dlcs
                        }
                        if persist_selected_dlcs(game_path, inferred_selected_dlcs):
                            logger.debug(
                                f"Migrated and persisted {len(inferred_selected_dlcs)} DLC ID(s) for AppID {appid}"
                            )

            # Get file size - try ACF first, fall back to manual calculation
            size_on_disk = 0
            acf_size_available = False

            # Check for ACF file data first
            if appmanifest_path and os.path.exists(appmanifest_path):
                acf_size_available = self._parse_acf_for_metadata(
                    appmanifest_path, game_data
                )
                if acf_size_available:
                    size_on_disk = game_data["size_on_disk"]

            # Only calculate size manually if ACF doesn't have a valid SizeOnDisk
            if not acf_size_available:
                logger.debug(
                    f"ACF SizeOnDisk not available, calculating size manually for {game_name}"
                )
                try:
                    for dirpath, dirnames, filenames in os.walk(game_path):
                        if self._scan_cancelled:
                            return None
                        for filename in filenames:
                            if self._scan_cancelled:
                                return None
                            filepath = os.path.join(dirpath, filename)
                            try:
                                # Use lstat to get file size without following symlinks
                                # This avoids issues with broken symlinks
                                if os.path.isfile(filepath) or os.path.islink(filepath):
                                    size_on_disk += os.lstat(filepath).st_size
                            except (OSError, FileNotFoundError, PermissionError):
                                # Skip files that can't be accessed (broken symlinks, permission errors, etc.)
                                pass
                except OSError:
                    pass

            # Update the size in game_data
            game_data["size_on_disk"] = size_on_disk

            # Set default update status to "checking" - will be checked asynchronously
            # Only if appid is valid
            if appid and appid not in ("0", "N/A", "unknown"):
                game_data["update_status"] = UPDATE_STATUS["CHECKING"]
            else:
                game_data["update_status"] = UPDATE_STATUS["CANNOT_DETERMINE"]

            return game_data

        except Exception as e:
            logger.error(
                f"Error collecting game data for {game_name}: {e}", exc_info=True
            )
            return None

    def _parse_acf_for_appid(self, library_path, game_name):
        """Parse ACF files to find the AppID for a given game name."""
        appmanifest_path = None
        appid = None

        # Look for appmanifest files in steamapps
        steamapps_path = os.path.join(library_path, "steamapps")
        if os.path.exists(steamapps_path):
            logger.debug(f"Looking for ACF match for game: '{game_name}'")
            try:
                with os.scandir(steamapps_path) as entries:
                    for entry in entries:
                        if self._scan_cancelled:
                            return None, None
                        try:
                            if not (
                                entry.name.startswith("appmanifest_")
                                and entry.name.endswith(".acf")
                            ):
                                continue
                            test_manifest_path = entry.path

                            # Parse ACF to check if this is the right game
                            try:
                                with open(
                                    test_manifest_path, "r", encoding="utf-8"
                                ) as f:
                                    content = f.read()
                                    # Extract installdir using regex
                                    match = re.search(
                                        r'"installdir"\s+"([^"]+)"', content
                                    )
                                    if match:
                                        installdir = match.group(1)
                                        logger.debug(
                                            f"  Checking {entry.name}: installdir='{installdir}'"
                                        )

                                        # Check if this manifest matches the current game
                                        if installdir == game_name or (
                                            installdir.lower() == game_name.lower()
                                        ):
                                            appmanifest_path = test_manifest_path
                                            # Extract appid from filename
                                            appid = entry.name.replace(
                                                "appmanifest_", ""
                                            ).replace(".acf", "")
                                            logger.debug(
                                                f"  ✓ Match found! AppID: {appid}"
                                            )
                                            logger.debug(
                                                f"Successfully determined AppID for '{game_name}': {appid}"
                                            )
                                            break  # Found the right manifest, stop looking
                            except (OSError, IOError, PermissionError):
                                logger.debug(
                                    f"  Error reading {entry.name}: file may be in use or inaccessible"
                                )
                                continue
                        except (OSError, FileNotFoundError, PermissionError):
                            continue
            except OSError as e:
                logger.debug(f"  Error scanning steamapps directory: {e}")

        return appmanifest_path, appid

    @staticmethod
    def _parse_manifest_summary(manifest_path, manifest_name):
        try:
            appid_match = re.search(r"appmanifest_(\d+)\.acf", manifest_name)
            if not appid_match:
                return None

            with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            name_match = re.search(r'"name"\s+"([^"]+)"', content)
            dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
            if not name_match or not dir_match:
                return None

            return {
                "appid": appid_match.group(1),
                "name": name_match.group(1),
                "installdir": dir_match.group(1),
                "path": manifest_path,
            }
        except OSError:
            return None

    @staticmethod
    def _parse_acf_for_metadata(appmanifest_path, game_data):
        """Parse ACF file for metadata like name, buildid, and size."""
        acf_size_available = False
        try:
            with open(appmanifest_path, "r", encoding="utf-8") as f:
                content = f.read()

                # Extract name using regex
                name_match = re.search(r'"name"\s+"([^"]+)"', content)
                if name_match:
                    game_data["game_name"] = name_match.group(1)

                # Extract buildid using regex
                buildid_match = re.search(r'"buildid"\s+"([^"]+)"', content)
                if buildid_match:
                    game_data["buildid"] = buildid_match.group(1)

                # Extract LastUpdated using regex
                lastupdated_match = re.search(r'"LastUpdated"\s+"([^"]+)"', content)
                if lastupdated_match:
                    game_data["last_updated"] = lastupdated_match.group(1)

                # Extract SizeOnDisk using regex (only use if non-zero)
                sizeon_disk_match = re.search(r'"SizeOnDisk"\s+"([^"]+)"', content)
                if sizeon_disk_match:
                    acf_size = int(sizeon_disk_match.group(1))
                    # Only use ACF size if it's greater than 0
                    if acf_size > 0:
                        game_data["size_on_disk"] = acf_size
                        acf_size_available = True
                        logger.debug(
                            f"Using ACF SizeOnDisk for {game_data['game_name']}: {acf_size} bytes"
                        )
        except Exception as e:
            logger.debug(f"Could not parse ACF file {appmanifest_path}: {e}")

        return acf_size_available

    def clear_library(self):
        """Clear all games from the library"""
        logger.info("Clearing entire game library")
        self.games.clear()
        self.filtered_games.clear()
        self.selected_game = None
        self.library_updated.emit()

    @staticmethod
    def import_library(file_path):
        """Import library from a file"""
        # TODO: Implement library import
        logger.info(f"Importing library from: {file_path}")
        return False

    def get_library_stats(self):
        """Get statistics about the game library"""
        total_games = len(self.games)
        total_size = sum(game.get("size_on_disk", 0) for game in self.games)

        return {
            "total_games": total_games,
            "total_size": total_size,
            "filtered_count": len(self.filtered_games),
        }

    def cleanup(self):
        """Clean up GameManager resources"""
        logger.info("Cleaning up GameManager")

        # Stop any running manifest check task
        self.cancel_update_checks()

        # Stop any running scan
        self._scan_cancelled = True
        if self.scan_runner is not None:
            try:
                self.scan_runner.stop(wait_ms=2000, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping scan runner during cleanup: {e}")
            self.scan_runner = None

        self.games.clear()
        self.filtered_games.clear()
        self.selected_game = None
        self._games_to_check = []

    def cancel_update_checks(self):
        """Cancel any in-progress update checks and clean up task/runner references."""
        if self.manifest_check_task is not None:
            try:
                self.manifest_check_task.stop()
            except Exception as e:
                logger.debug(f"Error stopping manifest check task: {e}")

        if self.manifest_check_runner is not None:
            try:
                self.manifest_check_runner.stop(wait_ms=2000, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping manifest check runner: {e}")

        self.manifest_check_task = None
        self.manifest_check_runner = None
        self._games_to_check = []

    def get_uninstall_confirmation_message(self, game_data):
        """
        Build a confirmation message for uninstalling a game.
        Returns a string with the confirmation message.
        """
        game_name = game_data.get("game_name", "Desconhecido")
        install_path = game_data.get("install_path")
        appid = game_data.get("appid", "0")

        import os
        import platform

        from core.steam_helpers import find_steam_install, get_steam_libraries

        confirm_msg = f"Tem certeza de que deseja desinstalar '{game_name}'?\n\n"
        is_lumatools_install = game_data.get("is_lumatools_install", False)

        # Warn if appid is unknown
        if not appid or appid in ("0", "N/A", "unknown"):
            confirm_msg += "⚠️ AVISO: o AppID deste jogo é desconhecido.\n"
            if platform.system() == "Linux":
                confirm_msg += "Os dados de compatibilidade e saves NÃO serão removidos.\n"
            elif platform.system() == "Windows" and is_lumatools_install:
                confirm_msg += "Os arquivos AppList do GreenLuma NÃO serão removidos.\n"
            confirm_msg += "\n"

        confirm_msg += "Isso apagará permanentemente:\n"
        confirm_msg += f"• Pasta do jogo: {install_path}\n"

        # Only show ACF removal if appid is valid
        if appid and appid not in ("0", "N/A", "unknown"):
            confirm_msg += f"• Manifesto do app da Steam ({appid}.acf)\n"

        # Check for additional items that would be removed
        if (
            platform.system() == "Linux"
            and appid
            and appid not in ("0", "N/A", "unknown")
        ):
            steam_libraries = get_steam_libraries()
            if steam_libraries:
                steam_dir = steam_libraries[0]
                compatdata_path = os.path.join(
                    steam_dir, "steamapps", "compatdata", appid
                )
                userdata_path = os.path.join(steam_dir, "userdata")

                # Check if compatdata exists
                if os.path.exists(compatdata_path):
                    confirm_msg += (
                        f"• Dados de compatibilidade do Proton/Wine: {compatdata_path}\n"
                    )

                # Check if userdata exists
                if os.path.exists(userdata_path):
                    has_saves = False
                    try:
                        for user_dir in os.listdir(userdata_path):
                            user_path = os.path.join(userdata_path, user_dir)
                            if os.path.isdir(user_path):
                                saves_path = os.path.join(user_path, appid, "remote")
                                if os.path.exists(saves_path):
                                    has_saves = True
                                    break
                    except OSError:
                        pass

                    if has_saves:
                        confirm_msg += "• Saves da Steam Cloud nas pastas userdata\n"
        elif (
            platform.system() == "Windows"
            and is_lumatools_install
            and appid
            and appid not in ("0", "N/A", "unknown")
        ):
            wrapper_mode_enabled = is_greenluma_wrapper_mode_enabled()
            if not wrapper_mode_enabled:
                confirm_msg += (
                    "• Limpeza do AppList do GreenLuma ignorada (modo wrapper desativado)\n"
                )
            else:
                steam_path = find_steam_install()
                if steam_path:
                    app_list_dir = os.path.join(steam_path, "AppList")
                    if os.path.exists(app_list_dir):
                        try:
                            appid_str = str(appid)
                            dlc_ids = self._collect_known_dlc_ids(game_data)
                            if not dlc_ids:
                                dlc_ids = (
                                    self._infer_selected_dlcs_from_applist_and_manifest(
                                        appid_str
                                    )
                                )

                            app_ids_to_check = [appid_str, *dlc_ids]
                            files_by_id = self._find_applist_files_for_ids(
                                app_list_dir, app_ids_to_check
                            )

                            found_appid_files = files_by_id.get(appid_str, [])
                            found_dlc_files = []
                            for dlc_id in dlc_ids:
                                found_dlc_files.extend(files_by_id.get(str(dlc_id), []))

                            if found_appid_files:
                                confirm_msg += (
                                    "• Arquivo(s) principal(is) do AppList do GreenLuma: "
                                    f"{', '.join(found_appid_files)}\n"
                                )
                            if found_dlc_files:
                                confirm_msg += (
                                    "• Arquivo(s) DLC do AppList do GreenLuma: "
                                    f"{', '.join(found_dlc_files)}\n"
                                )
                        except OSError:
                            pass

        confirm_msg += "\nEssa ação não pode ser desfeita!"
        return confirm_msg

    def uninstall_game(
        self,
        game_data,
        remove_compatdata=False,
        remove_saves=False,
        remove_from_library=False,
        remove_shortcuts=False,
    ):
        """
        Uninstall a game by removing its folder, ACF file, and optionally compatdata/saves.
        Returns (success: bool, error_message: str)
        """
        game_name = game_data.get("game_name", "Desconhecido")
        install_path = game_data.get("install_path")
        library_path = game_data.get("library_path")
        appid = game_data.get("appid", "0")

        import os
        import platform

        try:
            # Remove game folder
            if install_path and os.path.exists(install_path):
                import shutil

                shutil.rmtree(install_path)
                logger.info(f"Removed game folder: {install_path}")

            # Remove ACF file
            if library_path and appid != "N/A":
                acf_path = os.path.join(
                    library_path, "steamapps", f"appmanifest_{appid}.acf"
                )
                if os.path.exists(acf_path):
                    os.remove(acf_path)
                    logger.info(f"Removed ACF file: {acf_path}")

            # Remove depot file
            if (
                game_data.get("is_lumatools_install")
                and appid
                and appid not in ("0", "N/A", "unknown")
            ):
                try:
                    depot_file = Path(get_base_path()) / "depots" / f"{appid}.depot"
                    if depot_file.exists():
                        depot_file.unlink()
                        logger.info(f"Removed depot file: {depot_file}")
                except Exception as e:
                    logger.warning(
                        f"Failed to remove depot file for appid {appid}: {e}"
                    )

            # Remove platform-specific data
            if platform.system() == "Linux":
                self._remove_linux_game_data(appid, remove_compatdata, remove_saves)

                # Remove shortcuts only if explicitly requested
                if remove_shortcuts:
                    self._remove_linux_shortcuts_and_icons(appid)

                # Remove from SLSsteam config.yaml AdditionalApps list
                if (
                    remove_from_library
                    and appid
                    and appid not in ("0", "N/A", "unknown")
                ):
                    config_path = get_user_config_path()
                    if config_path.exists():
                        remove_additional_app(config_path, str(appid))
            elif platform.system() == "Windows":
                self._remove_windows_game_data(appid, game_data)

            # Remove from game manager
            self.remove_game(appid)

            return True, None

        except Exception as e:
            error_msg = f"Error uninstalling game {game_name}: {e}"
            logger.error(error_msg)
            return False, str(e)

    @staticmethod
    def _remove_linux_game_data(appid, remove_compatdata, remove_saves):
        """
        Remove Linux-specific game data (compatdata and Steam Cloud saves).
        """
        import os

        from core.steam_helpers import get_steam_libraries

        # CRITICAL SAFETY CHECK: Never remove compatdata/saves for invalid appids
        if not appid or appid in ("0", "N/A", "unknown"):
            logger.warning(
                f"Skipping compatdata/saves removal for invalid appid: {appid}"
            )
            return

        # Validate appid is numeric
        if not str(appid).isdigit():
            logger.error(
                f"Invalid appid format: {appid}. Must be numeric. Skipping compatdata/saves removal."
            )
            return

        steam_libraries = get_steam_libraries()
        if not steam_libraries:
            return

        # Use the first (primary) Steam library
        steam_dir = steam_libraries[0]

        # Remove compatdata
        if remove_compatdata:
            compatdata_path = os.path.join(steam_dir, "steamapps", "compatdata", appid)
            if os.path.exists(compatdata_path):
                try:
                    import shutil

                    shutil.rmtree(compatdata_path)
                    logger.info(f"Removed compatdata: {compatdata_path}")
                except Exception as e:
                    logger.warning(
                        f"Failed to remove compatdata {compatdata_path}: {e}"
                    )

        # Remove Steam Cloud saves
        if remove_saves:
            userdata_path = os.path.join(steam_dir, "userdata")
            if os.path.exists(userdata_path):
                try:
                    # Find all user directories
                    for user_dir in os.listdir(userdata_path):
                        user_path = os.path.join(userdata_path, user_dir)
                        if os.path.isdir(user_path):
                            saves_path = os.path.join(user_path, appid, "remote")
                            if os.path.exists(saves_path):
                                import shutil

                                shutil.rmtree(saves_path)
                                logger.info(
                                    f"Removed saves for user {user_dir}: {saves_path}"
                                )
                except Exception as e:
                    logger.warning(f"Failed to remove saves: {e}")

    @staticmethod
    def _remove_linux_shortcuts_and_icons(appid):
        """
        Remove Linux desktop shortcuts and icons created by ApplicationShortcutsTask.
        """
        import os
        from pathlib import Path

        # CRITICAL SAFETY CHECK: Never remove shortcuts/icons for invalid appids
        if not appid or appid in ("0", "N/A", "unknown"):
            logger.warning(
                f"Skipping shortcuts/icons removal for invalid appid: {appid}"
            )
            return

        # Validate appid is numeric
        if not str(appid).isdigit():
            logger.error(
                f"Invalid appid format: {appid}. Must be numeric. Skipping shortcuts/icons removal."
            )
            return

        try:
            # Remove desktop entry
            desktop_dir = Path.home() / ".local" / "share" / "applications"
            if desktop_dir.exists():
                # Look for desktop files that contain the appid in the Exec line
                desktop_files_removed = 0
                for desktop_file in desktop_dir.glob("*.desktop"):
                    try:
                        with open(desktop_file, "r", encoding="utf-8") as f:
                            content = f.read()
                            if f"steam://rungameid/{appid}" in content:
                                os.remove(desktop_file)
                                logger.info(f"Removed desktop entry: {desktop_file}")
                                desktop_files_removed += 1
                    except OSError as e:
                        logger.warning(
                            f"Error reading desktop file {desktop_file}: {e}"
                        )

                if desktop_files_removed == 0:
                    logger.info(f"No desktop entries found for AppID {appid}")

            # Remove icons
            icon_base = Path.home() / ".local" / "share" / "icons" / "hicolor"
            if icon_base.exists():
                icon_name = f"steam_icon_{appid}.png"
                icons_removed = 0

                # Remove icons from all size directories
                for size_dir in icon_base.glob("*x*"):
                    if size_dir.is_dir():
                        apps_dir = size_dir / "apps"
                        if apps_dir.exists():
                            icon_path = apps_dir / icon_name
                            if icon_path.exists():
                                try:
                                    os.remove(icon_path)
                                    logger.info(f"Removed icon: {icon_path}")
                                    icons_removed += 1
                                except OSError as e:
                                    logger.warning(
                                        f"Failed to remove icon {icon_path}: {e}"
                                    )

                if icons_removed == 0:
                    logger.info(f"No icons found for AppID {appid}")

        except OSError as e:
            logger.error(
                f"Failed to remove Linux shortcuts and icons for AppID {appid}: {e}"
            )

    def _remove_windows_game_data(self, appid, game_data):
        """
        Remove Windows-specific game data (GreenLuma AppList files).
        """
        import os

        from core.steam_helpers import find_steam_install

        if not game_data.get("is_lumatools_install"):
            logger.debug("Skipping GreenLuma cleanup for non-LumaTools install")
            return

        # AppList cleanup on Windows should only run when GreenLuma wrapper mode is enabled.
        if not is_greenluma_wrapper_mode_enabled():
            logger.debug(
                "GreenLuma wrapper mode is disabled, skipping AppList cleanup"
            )
            return

        # CRITICAL SAFETY CHECK: Never remove AppList files for invalid appids
        if not appid or appid in ("0", "N/A", "unknown"):
            logger.warning(
                f"Skipping GreenLuma AppList cleanup for invalid appid: {appid}"
            )
            return

        # Validate appid is numeric
        if not str(appid).isdigit():
            logger.error(
                f"Invalid appid format: {appid}. Must be numeric. Skipping GreenLuma cleanup."
            )
            return

        # Find Steam installation path
        steam_path = find_steam_install()
        if not steam_path:
            logger.warning(
                "Could not find Steam installation path. Skipping GreenLuma AppList cleanup."
            )
            return

        # Locate AppList directory
        app_list_dir = os.path.join(steam_path, "AppList")
        if not os.path.exists(app_list_dir):
            logger.info(
                "AppList directory does not exist. No GreenLuma files to clean up."
            )
            return

        logger.info(f"Scanning GreenLuma AppList directory: {app_list_dir}")

        self._find_and_delete_greenluma_files(app_list_dir, appid)
        self._remove_dlc_files(app_list_dir, game_data, appid)

    @staticmethod
    def _find_and_delete_greenluma_files(app_list_dir, appid):
        """Find and delete GreenLuma files for the given AppID."""
        # Step 1: Find all .txt files that contain this appid
        files_to_delete = []
        all_files_data = []  # List of tuples (filename, filepath, appid_content)

        try:
            for filename in os.listdir(app_list_dir):
                if filename.lower().endswith(".txt"):
                    filepath = os.path.join(app_list_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read().strip()
                            # Store all files for later renumbering
                            all_files_data.append((filename, filepath, content))

                            # Check if this file contains our appid
                            if content == str(appid):
                                files_to_delete.append((filename, filepath))
                                logger.info(
                                    f"Found GreenLuma file to delete: {filename} (contains AppID {appid})"
                                )
                    except OSError as e:
                        logger.warning(f"Error reading AppList file {filepath}: {e}")
        except OSError as e:
            logger.error(f"Error scanning AppList directory {app_list_dir}: {e}")
            return

        # Step 2: Delete files containing this appid
        for filename_to_delete, filepath in files_to_delete:
            try:
                os.remove(filepath)
                logger.info(f"Deleted GreenLuma file: {filepath}")
            except OSError as e:
                logger.warning(f"Failed to delete GreenLuma file {filepath}: {e}")

        # Step 3: Renumber remaining files to maintain sequential numbering
        # Build list of remaining files (those that don't contain our appid)
        remaining_files = [
            (fname, fpath, fcontent)
            for fname, fpath, fcontent in all_files_data
            if fpath not in [f[1] for f in files_to_delete]
        ]

        # Sort remaining files by their current number
        def extract_number(fname):
            match = re.match(r"^(\d+)\.txt$", fname)
            return int(match.group(1)) if match else 0

        remaining_files.sort(key=lambda x: extract_number(x[0]))

        # Renumber all remaining files sequentially starting from 0
        for index, (old_filename, old_filepath, content) in enumerate(remaining_files):
            new_filename = f"{index}.txt"
            new_filepath = os.path.join(app_list_dir, new_filename)

            # Only rename if the filename will change
            if old_filename != new_filename:
                try:
                    os.rename(old_filepath, new_filepath)
                    logger.debug(
                        f"Renamed GreenLuma file: {old_filename} -> {new_filename}"
                    )
                except OSError as e:
                    logger.warning(
                        f"Failed to rename {old_filename} to {new_filename}: {e}"
                    )

        logger.info(
            f"GreenLuma AppList cleanup complete. Removed {len(files_to_delete)} file(s)."
        )

    @staticmethod
    def _collect_known_dlc_ids(game_data):
        """Collect DLC IDs from in-memory game data fields."""
        selected_dlcs = game_data.get("selected_dlcs") or []
        dlc_map = game_data.get("dlcs", {})
        if not isinstance(dlc_map, dict):
            dlc_map = {}

        dlc_ids = []
        seen = set()

        for dlc_id in selected_dlcs:
            dlc_id_str = str(dlc_id).strip()
            if not dlc_id_str or dlc_id_str in seen:
                continue
            seen.add(dlc_id_str)
            dlc_ids.append(dlc_id_str)

        for dlc_id in dlc_map:
            dlc_id_str = str(dlc_id).strip()
            if not dlc_id_str or dlc_id_str in seen:
                continue
            seen.add(dlc_id_str)
            dlc_ids.append(dlc_id_str)

        return dlc_ids

    @staticmethod
    def _find_applist_files_for_ids(app_list_dir, app_ids):
        """Return a mapping {appid: [filename, ...]} for matching AppList .txt files."""
        target_ids = {str(app_id).strip() for app_id in app_ids if str(app_id).strip()}
        files_by_id = {app_id: [] for app_id in target_ids}
        if not target_ids:
            return files_by_id

        for filename in os.listdir(app_list_dir):
            if not filename.lower().endswith(".txt"):
                continue

            filepath = os.path.join(app_list_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as file_handle:
                    content = file_handle.read().strip()
                if content in files_by_id:
                    files_by_id[content].append(filename)
            except OSError:
                continue

        for file_list in files_by_id.values():
            file_list.sort()

        return files_by_id

    def _read_manifest_dlc_ids(self, appid):
        """
        Best-effort read of DLC IDs from the local manifest ZIP for the given appid.
        Returns [] if no usable manifest is available.
        """
        appid_str = str(appid).strip()
        if not appid_str.isdigit():
            return []

        manifests_dir = Path(get_base_path()) / "morrenus_manifests"
        manifest_zip = manifests_dir / f"lumatools_fetch_{appid_str}.zip"
        if not manifest_zip.exists():
            return []

        try:
            with zipfile.ZipFile(manifest_zip, "r") as zip_ref:
                lua_files = [
                    name for name in zip_ref.namelist() if name.endswith(".lua")
                ]
                if not lua_files:
                    return []

                lua_content = zip_ref.read(lua_files[0]).decode(
                    "utf-8", errors="ignore"
                )
        except (OSError, zipfile.BadZipFile, RuntimeError):
            return []

        app_matches = list(
            re.finditer(r"addappid\((.*?)\)(.*)", lua_content, re.IGNORECASE)
        )
        if len(app_matches) < 2:
            return []

        first_args = [arg.strip() for arg in app_matches[0].group(1).strip().split(",")]
        if not first_args:
            return []

        first_appid = first_args[0].strip('"')
        if first_appid != appid_str:
            return []

        dlc_ids = []
        seen = set()
        for match in app_matches[1:]:
            args = [arg.strip() for arg in match.group(1).strip().split(",")]
            if not args:
                continue

            candidate_id = args[0].strip('"')
            has_depot_key = len(args) > 2 and bool(args[2].strip('"'))
            if has_depot_key:
                continue
            if not candidate_id.isdigit():
                continue
            if candidate_id in seen:
                continue

            seen.add(candidate_id)
            dlc_ids.append(candidate_id)

        return dlc_ids

    def _infer_selected_dlcs_from_applist_and_manifest(self, appid):
        """
        Best-effort inference for old installs:
        intersect local manifest DLC IDs with IDs currently present in AppList.
        """
        appid_str = str(appid).strip()
        if not appid_str.isdigit():
            return []

        steam_path = find_steam_install()
        if not steam_path:
            return []

        app_list_dir = os.path.join(steam_path, "AppList")
        if not os.path.exists(app_list_dir):
            return []

        try:
            files_by_id = self._find_applist_files_for_ids(app_list_dir, [appid_str])
            if not files_by_id.get(appid_str):
                return []
        except OSError:
            return []

        manifest_dlc_ids = self._read_manifest_dlc_ids(appid_str)
        if not manifest_dlc_ids:
            return []

        try:
            files_by_id = self._find_applist_files_for_ids(
                app_list_dir, manifest_dlc_ids
            )
        except OSError:
            return []

        return [dlc_id for dlc_id in manifest_dlc_ids if files_by_id.get(str(dlc_id))]

    def _remove_dlc_files(self, app_list_dir, game_data, appid):
        """Remove DLC files from the AppList directory."""
        dlc_ids = self._collect_known_dlc_ids(game_data)
        if not dlc_ids:
            dlc_ids = self._infer_selected_dlcs_from_applist_and_manifest(appid)

        if not dlc_ids:
            return

        logger.info(f"Removing {len(dlc_ids)} DLC files from AppList directory.")
        for dlc_id in dlc_ids:
            self._find_and_delete_greenluma_files(app_list_dir, dlc_id)
