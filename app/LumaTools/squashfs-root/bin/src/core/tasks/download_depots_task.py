import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Tuple, Optional, Dict, Any

from PyQt6.QtCore import QObject, pyqtSignal

# Local imports
from utils.helpers import resource_path, ensure_dotnet_availability, get_dotnet_path
from utils.settings import get_settings

# Third-party imports
try:
    import psutil
except ImportError:
    logging.critical(
        "Failed to import 'psutil'. Pausing/resuming downloads will not work."
    )
    psutil = None

logger = logging.getLogger(__name__)

DEFAULT_MAX_DOWNLOADS = 8
MAX_SAFE_DOWNLOADS = 32

ENCRYPTED_CONTENT_PATTERNS = (
    "content still encrypted",
    "still encrypted",
    "missing decryption key",
    "unable to get depot decryption key",
    "no decryption key",
    "depot encrypted",
)


class DownloadDepotsTask(QObject):
    """
    Manages the downloading of Steam depots. Handles process management,
    progress tracking, and pause/resume functionality.
    """

    progress = pyqtSignal(str)
    progress_percentage = pyqtSignal(int)
    completed = pyqtSignal()
    error = pyqtSignal(tuple)

    def __init__(self):
        super().__init__()
        self._is_running = True
        self.percentage_regex = re.compile(r"(\d{1,3}(?:\.\d{1,2})?)%")
        self.last_percentage = -1
        self.process: Optional[subprocess.Popen] = None

        self.total_download_size_for_this_job = 0
        self.completed_so_far_for_this_job = 0
        self.current_depot_size = 0
        self._last_log_time = 0
        self._log_buffer = []
        self.commands_started = 0
        self.failed_depots: List[Dict[str, Any]] = []
        self.skipped_depots: List[str] = []
        self.last_error_reason = ""
        self.encrypted_content_detected = False
        self._current_depot_encrypted = False
        self._current_depot_id = ""

    @property
    def is_running_flag(self) -> bool:
        """Property to access the private running state safely."""
        return self._is_running

    def run(
        self, game_data: Dict[str, Any], selected_depots: List[str], dest_path: str
    ):
        """
        Main execution method to download selected depots.
        """
        logger.info(f"Download task starting for {len(selected_depots)} depots.")
        current_cmd: Optional[List[str]] = None
        self.commands_started = 0
        self.failed_depots = []
        self.skipped_depots = []
        self.last_error_reason = ""
        self.encrypted_content_detected = False

        try:
            # Check for .NET 9 availability before proceeding (will attempt auto-install if missing)
            self.progress.emit("Checking .NET 9 runtime availability...")
            if not ensure_dotnet_availability():
                self.progress.emit(
                    "ERROR: .NET 9 runtime is required and could not be installed automatically."
                )
                logger.critical(".NET 9 runtime not available")
                self.error.emit((RuntimeError, ".NET 9 runtime not available", None))
                return

            commands, skipped_depots, depot_sizes = self._prepare_downloads(
                game_data, selected_depots, dest_path
            )
            self.skipped_depots = list(skipped_depots)

            if not commands:
                raise RuntimeError("No valid download commands to execute.")

            total_depots = len(commands)
            self.total_download_size_for_this_job = sum(depot_sizes)
            self.completed_so_far_for_this_job = 0

            logger.info(
                f"Task tracking total download size: {self.total_download_size_for_this_job} bytes"
            )

            for i, current_cmd in enumerate(commands):
                if not self._is_running:
                    logger.info("Download task stopping before next depot.")
                    break

                depot_id = current_cmd[
                    5
                ]  # 'dotnet', 'dll', '-app', 'id', '-depot', 'id'
                self._current_depot_id = str(depot_id)
                self._current_depot_encrypted = False
                self.current_depot_size = depot_sizes[i]

                self.progress.emit(
                    f"--- Starting download for depot {depot_id} "
                    f"({i + 1}/{total_depots}) [Size: {self.current_depot_size} bytes] ---"
                )
                self.last_percentage = -1

                # Determine creation flags for Windows to hide the console window
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW

                # Use binary mode to handle \r correctly
                self.process = subprocess.Popen(
                    current_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=False,  # Binary mode
                    creationflags=creation_flags,
                )
                self.commands_started += 1

                # Read output directly in this thread
                self._read_process_output()

                # Flush any remaining logs
                self._flush_log_buffer()

                if not self._is_running:
                    if self.process and self.process.poll() is None:
                        self.process.terminate()
                    logger.info("Download task stopping because stop() was called.")
                    self.completed.emit()
                    return

                return_code = 0
                if self.process:
                    return_code = self.process.poll()
                    self.process = None

                if self._current_depot_encrypted:
                    self.failed_depots.append(
                        {
                            "depot_id": str(depot_id),
                            "return_code": int(return_code or 1),
                            "status": "encrypted_content_or_unsupported_depot",
                        }
                    )
                    break
                if return_code != 0:
                    msg = (
                        f"ERROR: DepotDownloader exited with code "
                        f"{return_code} for depot {depot_id}."
                    )
                    self.progress.emit(msg)
                    logger.error(msg)
                    self.failed_depots.append(
                        {
                            "depot_id": str(depot_id),
                            "return_code": int(return_code),
                            "status": "download_failed",
                        }
                    )
                    break
                else:
                    self.completed_so_far_for_this_job += self.current_depot_size

            if skipped_depots:
                self.progress.emit(
                    f"Skipped {len(skipped_depots)} depots due to missing manifests: "
                    f"{', '.join(skipped_depots)}"
                )
                self.failed_depots.extend(
                    {
                        "depot_id": str(depot_id),
                        "return_code": -1,
                        "status": "missing_manifest",
                    }
                    for depot_id in skipped_depots
                )

            if not self._is_running:
                logger.info("Download task stopped before cleanup.")
                self.completed.emit()
                return

            if self.commands_started <= 0:
                raise RuntimeError("No depot download command was started.")

            if self.failed_depots:
                failures = ", ".join(
                    f"{item['depot_id']}={item['status']}"
                    for item in self.failed_depots
                )
                self.last_error_reason = f"Depot download failed: {failures}"
                self._cleanup_temp_files()
                raise RuntimeError(self.last_error_reason)

            self._cleanup_temp_files()
            self.completed.emit()

        except FileNotFoundError:
            binary = "executable"
            if current_cmd:
                binary = current_cmd[0]

            error_msg = (
                f"ERROR: '{binary}' command not found. "
                "Ensure .NET Runtime is installed and 'dotnet' is in your PATH."
            )
            self.progress.emit(error_msg)
            logger.critical(f"'{binary}' not found.")
            self.error.emit((FileNotFoundError, error_msg, None))
            raise

        except (OSError, subprocess.SubprocessError) as e:
            self.progress.emit(f"An unexpected error occurred during download: {e}")
            logger.error(f"Download subprocess failed: {e}", exc_info=True)
            self.process = None
            self.error.emit((type(e), e, None))
            raise

    def _read_process_output(self):
        """Reads process output byte-by-byte to handle \r updates."""
        if not self.process or not self.process.stdout:
            return

        buffer = bytearray()
        while self._is_running:
            # Check if process is None before reading
            if self.process is None:
                break

            # Read small chunks to be responsive
            chunk = self.process.stdout.read(1)

            if not chunk:
                # Check if process is None before polling
                if self.process and self.process.poll() is not None:
                    break
                time.sleep(0.01)
                continue

            if chunk == b"\r" or chunk == b"\n":
                if buffer:
                    try:
                        line = buffer.decode("utf-8", errors="replace")
                        self._handle_downloader_output(line)
                    except UnicodeDecodeError:
                        pass
                    buffer.clear()
            else:
                buffer.extend(chunk)

        # Process remaining buffer
        if buffer:
            try:
                line = buffer.decode("utf-8", errors="replace")
                self._handle_downloader_output(line)
            except UnicodeDecodeError:
                pass

    def _cleanup_temp_files(self):
        """Cleans up temporary files created during the download process."""
        self.progress.emit("--- Cleaning up temporary files ---")
        temp_dir = tempfile.gettempdir()
        items_to_clean = {
            "mistwalker_keys.vdf": os.path.join(temp_dir, "mistwalker_keys.vdf"),
        }

        for name, path in items_to_clean.items():
            if os.path.exists(path):
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path)
                        self.progress.emit(f"Removed temp directory '{name}'.")
                    else:
                        os.remove(path)
                        self.progress.emit(f"Removed temp file '{name}'.")
                except OSError as e:
                    self.progress.emit(f"Error removing temp item '{name}': {e}")

    def _flush_log_buffer(self):
        """Emits any buffered log lines."""
        if self._log_buffer:
            # Join buffered lines and emit as a single signal
            # This reduces the number of signals sent to the main thread
            combined_log = "\n".join(self._log_buffer)
            self.progress.emit(combined_log)
            self._log_buffer.clear()
            self._last_log_time = time.time()

    def _handle_downloader_output(self, line: str):
        """Parses output lines from the downloader to update progress."""
        if not self._is_running:
            return

        line = line.strip()
        if not line:
            return

        line_lower = line.lower()
        if any(pattern in line_lower for pattern in ENCRYPTED_CONTENT_PATTERNS):
            self.encrypted_content_detected = True
            self._current_depot_encrypted = True
            self.last_error_reason = (
                "encrypted_content_or_unsupported_depot"
                + (f": depot {self._current_depot_id}" if self._current_depot_id else "")
            )

        # Add to buffer
        self._log_buffer.append(line)

        # Check for percentage update
        match = self.percentage_regex.search(line)
        if match:
            try:
                percentage = float(match.group(1))

                if self.total_download_size_for_this_job > 0:
                    progress_of_current_depot = (
                        percentage / 100.0
                    ) * self.current_depot_size

                    total_progress_bytes = (
                        self.completed_so_far_for_this_job + progress_of_current_depot
                    )

                    total_percentage = int(
                        (total_progress_bytes / self.total_download_size_for_this_job)
                        * 100
                    )

                    total_percentage = max(0, min(100, total_percentage))

                    if total_percentage != self.last_percentage:
                        self.progress_percentage.emit(total_percentage)
                        self.last_percentage = total_percentage
                else:
                    int_percentage = int(percentage)
                    if int_percentage != self.last_percentage:
                        self.progress_percentage.emit(int_percentage)
                        self.last_percentage = int_percentage
            except ValueError:
                pass

        # Check if we should flush the buffer
        is_important = (
            "error" in line_lower
            or "warning" in line_lower
            or "failed" in line_lower
        )
        current_time = time.time()

        # Flush if important message or time interval passed (80ms)
        if is_important or (current_time - self._last_log_time > 0.08):
            self._flush_log_buffer()

    def _prepare_downloads(
        self, game_data: Dict[str, Any], selected_depots: List[str], dest_path: str
    ) -> Tuple[List[List[str]], List[str], List[int]]:
        """
        Prepares the list of commands, identifies skipped depots, and gathers sizes.
        """
        temp_dir = tempfile.gettempdir()
        keys_path = os.path.join(temp_dir, "mistwalker_keys.vdf")
        manifest_dir = os.path.join(temp_dir, "mistwalker_manifests")

        self.progress.emit(f"Generating depot keys file at {keys_path}")
        with open(keys_path, "w") as f:
            for depot_id in selected_depots:
                if depot_id in game_data["depots"]:
                    f.write(f"{depot_id};{game_data['depots'][depot_id]['key']}\n")

        safe_game_name_fallback = (
            re.sub(r"[^\w\s-]", "", game_data.get("game_name", ""))
            .strip()
            .replace(" ", "_")
        )
        install_folder_name = game_data.get("installdir", safe_game_name_fallback)
        if not install_folder_name:
            install_folder_name = f"App_{game_data['appid']}"

        download_dir = os.path.join(
            dest_path, "steamapps", "common", install_folder_name
        )
        os.makedirs(download_dir, exist_ok=True)
        self.progress.emit(f"Download destination set to: {download_dir}")

        # Use dotnet to run the .NET 9 DLL (multiplatform, like Steamless)
        # Get the full path to dotnet, checking both PATH and default install location
        dotnet_path = get_dotnet_path()
        if not dotnet_path:
            raise RuntimeError(
                "dotnet command not found. Please install .NET 9 runtime manually."
            )
        dotnet_cmd = dotnet_path
        dll_path = resource_path(os.path.join("deps", "DepotDownloader.dll"))

        max_downloads = self._get_max_downloads()

        commands = []
        skipped_depots = []
        depot_sizes = []

        for depot_id in selected_depots:
            manifest_id = game_data["manifests"].get(depot_id)
            if not manifest_id:
                self.progress.emit(
                    f"Warning: No manifest ID for depot {depot_id}. Skipping."
                )
                skipped_depots.append(str(depot_id))
                continue

            try:
                size_str = game_data["depots"][depot_id].get("size")
                if size_str:
                    depot_sizes.append(int(size_str))
                else:
                    depot_sizes.append(0)
                    self.progress.emit(
                        f"Warning: No size data for depot {depot_id}. "
                        "Total progress may be inaccurate."
                    )
            except (ValueError, TypeError):
                depot_sizes.append(0)
                self.progress.emit(
                    f"Warning: Invalid size data for depot {depot_id}. "
                    "Total progress may be inaccurate."
                )

            manifest_file_path = os.path.join(
                manifest_dir, f"{depot_id}_{manifest_id}.manifest"
            )

            commands.append(
                [
                    dotnet_cmd,
                    dll_path,
                    "-app",
                    str(game_data["appid"]),
                    "-depot",
                    str(depot_id),
                    "-manifest",
                    str(manifest_id),
                    "-manifestfile",
                    manifest_file_path,
                    "-depotkeys",
                    keys_path,
                    "-max-downloads",
                    str(max_downloads),
                    "-dir",
                    download_dir,
                    "-validate",
                ]
            )

        return commands, skipped_depots, depot_sizes

    @staticmethod
    def _get_max_downloads() -> int:
        settings = get_settings()
        try:
            raw_value = int(
                settings.value("max_downloads", DEFAULT_MAX_DOWNLOADS, type=int)
            )
        except (TypeError, ValueError):
            raw_value = DEFAULT_MAX_DOWNLOADS

        if raw_value <= 0:
            logger.warning(
                "Invalid max_downloads=%s; using stable default %s.",
                raw_value,
                DEFAULT_MAX_DOWNLOADS,
            )
            return DEFAULT_MAX_DOWNLOADS

        clamped_value = max(1, min(MAX_SAFE_DOWNLOADS, raw_value))
        if clamped_value != raw_value:
            logger.warning(
                "Clamping max_downloads from %s to %s for download stability.",
                raw_value,
                clamped_value,
            )
        return clamped_value

    def stop(self):
        """Signals the task to stop."""
        logger.debug("Stop signal received by download task.")
        self._is_running = False

    def toggle_pause(self, pause: bool):
        """
        Pauses or resumes the download process tree.
        """
        if not psutil:
            logger.error("psutil not found. Cannot pause or resume.")
            raise RuntimeError("psutil library is not loaded.")

        if not self.process:
            logger.warning("Attempted to pause/resume, but no process is running.")
            return

        target_action = "pausing" if pause else "resuming"

        try:
            parent = psutil.Process(self.process.pid)
            children = parent.children(recursive=True)
            processes = [parent] + children

            for proc in processes:
                try:
                    if pause:
                        proc.suspend()
                    else:
                        proc.resume()
                except psutil.NoSuchProcess:
                    logger.warning(f"Process {proc.pid} no longer exists. Skipping.")

            result_status = "paused" if pause else "resumed"
            logger.info(f"Download process tree {result_status}.")

        except psutil.NoSuchProcess:
            logger.error(
                f"Main process {self.process.pid} not found. Cannot pause/resume."
            )
            self.process = None
        except psutil.Error as e:
            logger.error(f"An error occurred while {target_action} process: {e}")
            raise
