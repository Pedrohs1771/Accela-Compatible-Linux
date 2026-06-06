import logging
import glob
import os
import re
import shutil
import sys
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Set, List

# QObject and pyqtSlot for robust threading
from PyQt6.QtCore import QTimer, QMetaObject, Qt, QObject, pyqtSlot
from PyQt6.QtWidgets import QFileDialog, QMessageBox

try:
    import psutil
except ImportError:
    psutil = None

from core import steam_helpers
from core.tasks.application_shortcuts import ApplicationShortcutsTask
from core.tasks.download_depots_task import DownloadDepotsTask
from core.tasks.download_slssteam_task import DownloadSLSsteamTask
from core.tasks.generate_achievements_task import GenerateAchievementsTask
from core.tasks.monitor_speed_task import SpeedMonitorTask
from core.tasks.process_zip_task import ProcessZipTask
from core.tasks.steamless_task import SteamlessTask
from core.fix_planner import apply_ryuu_fix, record_online_fix_layer
from core.ryuu_client import RyuuClient, RyuuClientError, load_ryuu_auth_key

from utils.helpers import get_base_path
from utils.proton_tools import (
    apply_steam_compat_tool,
    build_default_proton_selection,
    clear_steam_compat_tool,
)
from utils.steam_manifest import get_game_directory, repair_installed_app_state, write_acf_file
from utils.wrapper_metadata import persist_selected_dlcs
from utils.yaml_config_manager import (
    get_user_config_path,
    add_additional_app,
    add_dlc_data,
    is_slssteam_mode_enabled,
    is_slssteam_config_management_enabled,
)

from utils.paths import Paths
from utils.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class TaskManager(QObject):
    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings

        # Task state
        self.speed_monitor_task = None
        self.speed_monitor_runner = None
        self.is_awaiting_speed_monitor_stop = False

        self.zip_task = None
        self.zip_task_runner = None
        self.is_awaiting_zip_task_stop = False

        self.download_task = None
        self.download_runner = None
        self.is_awaiting_download_stop = False
        self.achievement_task = None
        self.achievement_task_runner = None
        self.achievement_worker = None
        self.steamless_task = None
        self.application_shortcuts_task = None
        self.application_shortcuts_task_runner = None
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

        # Processing state
        self.is_processing = False
        self.is_download_paused = False
        self.is_cancelling = False
        self.current_job: Optional[str] = None
        self.current_job_metadata: Optional[Dict[str, Any]] = None
        self.game_data: Optional[Dict[str, Any]] = None
        self.current_dest_path: Optional[str] = None
        self.slssteam_mode_was_active = False
        self.library_mode_was_active = False
        self._ryuu_status = {"status": "skipped", "message": ""}
        self._pending_ryuu_fix_path: Optional[str] = None
        self._pending_ryuu_error = ""
        self._pending_ryuu_apply_result: Optional[Dict[str, Any]] = None
        self._steamless_success = None
        self._steamless_manual_run = False

        # Job step states
        self._job_steps_completed: Set[str] = set()

        # Progress tracking
        self._steamless_progress_log = []
        self._steamless_game_name = ""

        # Status tracking
        self._last_steamless_success = None
        self._steamless_ran = False
        self._steamless_error = False
        self._last_slscheevo_success = None
        self._slscheevo_ran = False
        self._slscheevo_error = False

        self._last_ddm_status = "not_run"
        self._last_ddm_status_text = "N/D"
        self._last_slscheevo_status = "not_run"
        self._last_slscheevo_status_text = "N/D"
        self._last_steamless_status = "not_run"
        self._last_steamless_status_text = "N/D"
        self._last_installed_game = None
        self._online_fix_status = "skipped"
        self._online_fix_status_text = "N/D"
        self._launch_options_status = "skipped"
        self._launch_options_status_text = "N/D"

        self._delete_files_on_cancel: Optional[bool] = None

        # Status colors
        self.STATUS_OK = "#00FF00"
        self.STATUS_IN_PROGRESS = "#FFA500"
        self.STATUS_ERROR = "#FF0000"
        self.STATUS_NOT_RUN = "accent"

    @property
    def last_installed_game(self):
        return self._last_installed_game

    def start_zip_processing(self, zip_path, metadata=None):
        self.is_processing = True
        self.current_job = zip_path
        self.current_job_metadata = metadata or {}
        self._job_steps_completed.clear()

        if self.main_window:
            self.main_window.progress_bar.setVisible(True)
            self.main_window.progress_bar.setRange(0, 0)
            self.main_window.drop_text_label.setText(
                f"Processando: {os.path.basename(zip_path)}"
            )

        self.zip_task = ProcessZipTask()
        self.zip_task_runner = TaskRunner()
        self.is_awaiting_zip_task_stop = True
        self.zip_task_runner.cleanup_complete.connect(self._on_zip_task_stopped)

        worker = self.zip_task_runner.run(self.zip_task.run, zip_path)
        worker.finished.connect(self._on_zip_processed)
        worker.error.connect(self._handle_task_error)

    def _on_zip_processed(self, game_data):
        if not game_data or game_data.get("cancelled"):
            logger.info("Zip processing finished without actionable game data.")
            self.job_finished()
            return

        self.main_window.progress_bar.setRange(0, 100)
        self.main_window.progress_bar.setValue(100)
        self.game_data = game_data

        if self.game_data and self.game_data.get("depots"):
            if self._should_auto_select_depots():
                self._auto_select_depots_from_job()
                return
            self._show_depot_selection_dialog()
        else:
            QMessageBox.warning(
                self.main_window,
                "Nenhum depot encontrado",
                "O arquivo ZIP foi processado, mas nenhum depot disponível para download foi encontrado.",
            )
            self.job_finished()

    def _should_auto_select_depots(self) -> bool:
        metadata = self.current_job_metadata or {}
        return bool(metadata.get("auto_select_depots")) and metadata.get("source") in {
            "ryuu",
            "content_zip",
        }

    def _auto_select_depots_from_job(self) -> None:
        if not self.game_data:
            self.job_finished()
            return

        depots = self.game_data.get("depots") or {}
        selected_depots = list(depots.keys())
        if not selected_depots:
            self.job_finished()
            return

        logger.info(
            "Content job auto-selected %s depot(s) for %s",
            len(selected_depots),
            self.game_data.get("game_name", self.game_data.get("appid", "")),
        )
        self.game_data["selected_depots_list"] = selected_depots
        metadata = self.current_job_metadata or {}
        selected_dlc_override = (
            metadata.get("selected_dlcs")
            if "selected_dlcs" in metadata
            else metadata.get("selected_dlcs_override")
        )
        if selected_dlc_override is not None:
            available_dlcs = {str(key) for key in (self.game_data.get("dlcs") or {}).keys()}
            self.game_data["selected_dlcs"] = [
                str(dlc_id)
                for dlc_id in selected_dlc_override
                if not available_dlcs or str(dlc_id) in available_dlcs
            ]
            logger.info(
                "Content job selected %s requested DLC/AppID item(s) for %s",
                len(self.game_data["selected_dlcs"]),
                self.game_data.get("game_name", self.game_data.get("appid", "")),
            )
        elif self.game_data.get("dlcs"):
            self.game_data["selected_dlcs"] = list(self.game_data["dlcs"].keys())
            logger.info(
                "Content job auto-selected %s DLC/AppID item(s) for %s",
                len(self.game_data["selected_dlcs"]),
                self.game_data.get("game_name", self.game_data.get("appid", "")),
            )
        self._apply_default_linux_proton_selection(selected_depots)
        self._start_download_with_destination(selected_depots)

    def _show_depot_selection_dialog(self):
        # Deferred import to prevent circular dependency
        from ui.dialogs.depotselection import DepotSelectionDialog

        game_data = self.game_data
        if not game_data:
            self.job_finished()
            return

        # Even if auto_skip_single_choice is enabled, we MUST show the dialog 
        # if the user wants to enable online compatibility, as that checkbox 
        # is only available in the DepotSelectionDialog.
        auto_skip_single_choice = self.settings.value(
            "auto_skip_single_choice", False, type=bool
        )
        depots = game_data.get("depots") or {}
        
        # Force showing the dialog ALWAYS to ensure the user can toggle 
        # 'Ativar compatibilidade online'. The auto-skip was causing confusion.
        pass

        self.main_window.ui_state.depot_dialog = DepotSelectionDialog(
            game_data["appid"],
            game_data["game_name"],
            game_data["depots"],
            game_data.get("header_url"),
            self.main_window,
        )

        if self.main_window.ui_state.depot_dialog.exec():
            selected_depots = (
                self.main_window.ui_state.depot_dialog.get_selected_depots()
            )
            if self.game_data:
                self.game_data["selected_depots_list"] = selected_depots
                self.game_data.update(
                    self.main_window.ui_state.depot_dialog.get_proton_preferences()
                )

            if not selected_depots:
                self.job_finished()
                return

            self._start_download_with_destination(selected_depots)
        else:
            self.job_finished()

    def _apply_default_linux_proton_selection(self, selected_depots):
        if sys.platform != "linux" or not self.game_data:
            return

        proton_defaults = build_default_proton_selection(
            selected_depots, self.game_data.get("depots") or {}
        )
        self.game_data.update(proton_defaults)

    def _start_download_with_destination(self, selected_depots):
        dest_path = self._get_destination_path()
        if dest_path:
            self._start_download(selected_depots, dest_path)
        else:
            self.job_finished()

    def _get_destination_path(self):
        slssteam_mode = is_slssteam_mode_enabled()
        library_mode = self.settings.value("library_mode", False, type=bool)
        current_job_metadata = self.current_job_metadata or {}
        existing_library_path = current_job_metadata.get("library_path")

        if slssteam_mode:
            self._handle_slssteam_mode()
            if existing_library_path:
                return existing_library_path
            return self._get_library_destination_path()
        elif library_mode:
            if existing_library_path:
                return existing_library_path
            return self._get_library_destination_path()
        else:
            return QFileDialog.getExistingDirectory(
                self.main_window, "Select Destination Folder"
            )

    def _get_library_destination_path(self):
        # Deferred import
        from ui.dialogs.steamlibrary import SteamLibraryDialog

        libraries = steam_helpers.get_steam_libraries()
        if libraries:
            if len(libraries) == 1:
                return libraries[0]
            dialog = SteamLibraryDialog(libraries, self.main_window)
            if dialog.exec():
                return dialog.get_selected_path()
            else:
                return None
        else:
            preferred_library = steam_helpers.get_preferred_steam_library()
            if preferred_library:
                logger.info(
                    "Steam library list was empty; falling back to main Steam path: %s",
                    preferred_library,
                )
                return preferred_library

            return QFileDialog.getExistingDirectory(
                self.main_window, "Select Destination Folder"
            )

    def _handle_slssteam_mode(self):
        # Deferred import
        from ui.dialogs.dlcselection import DlcSelectionDialog

        game_data = self.game_data
        if not game_data:
            return

        if sys.platform == "win32" and game_data.get("dlcs"):
            dlc_dialog = DlcSelectionDialog(game_data["dlcs"], self.main_window)
            if dlc_dialog.exec():
                game_data["selected_dlcs"] = dlc_dialog.get_selected_dlcs()

    def _start_download(self, selected_depots, dest_path):
        if not self.game_data:
            self.job_finished()
            return

        # Reset step tracker for this new download phase
        self._job_steps_completed.clear()

        self.current_dest_path = dest_path
        self.slssteam_mode_was_active = is_slssteam_mode_enabled()
        self.library_mode_was_active = self.settings.value(
            "library_mode", False, type=bool
        )
        self.is_cancelling = False

        self._last_steamless_success = None
        self._last_slscheevo_success = None
        self._steamless_ran = False
        self._steamless_error = False
        self._slscheevo_ran = False
        self._slscheevo_error = False
        self._last_ddm_status = "in_progress"
        self._last_ddm_status_text = "Baixando..."
        self._last_slscheevo_status = "not_run"
        self._last_slscheevo_status_text = "N/D"
        self._last_steamless_status = "not_run"
        self._last_steamless_status_text = "N/D"
        self._online_fix_status = "skipped"
        self._online_fix_status_text = "N/D"
        self._launch_options_status = "skipped"
        self._launch_options_status_text = "N/D"

        self.main_window.ui_state.switch_to_download_gif()
        self._update_status_button_color()
        self.main_window.drop_text_label.setText(
            f"Baixando: {self.game_data.get('game_name', '')}"
        )

        self.main_window.progress_bar.setVisible(True)
        self.main_window.progress_bar.setValue(0)
        self.main_window.speed_label.setVisible(True)

        self.download_task = DownloadDepotsTask()
        self.download_task.progress.connect(logger.info)
        self.download_task.progress_percentage.connect(
            self.main_window.progress_bar.setValue
        )
        self.download_task.completed.connect(self._on_download_complete)
        self.download_task.error.connect(self._handle_task_error)

        self.download_runner = TaskRunner()
        self.is_awaiting_download_stop = True
        self.download_runner.cleanup_complete.connect(self._on_download_task_stopped)
        worker = self.download_runner.run(
            self.download_task.run, self.game_data, selected_depots, dest_path
        )
        worker.error.connect(self._handle_task_error)

        self._start_speed_monitor()
        self.is_download_paused = False
        self.main_window.ui_state.pause_button.setText("Pausar")
        self.main_window.ui_state.pause_button.setVisible(True)
        self.main_window.ui_state.cancel_button.setVisible(True)

        if not self.slssteam_mode_was_active:
            app_token = self.game_data.get("app_token")
            if app_token:
                game_dir = get_game_directory(dest_path, self.game_data)
                token_file = os.path.join(game_dir, "apptoken.txt")
                try:
                    os.makedirs(game_dir, exist_ok=True)
                    with open(token_file, "w") as f:
                        f.write(app_token)
                except OSError as e:
                    logger.error(f"Failed to write app token: {e}")

    def _start_speed_monitor(self):
        self.speed_monitor_task = SpeedMonitorTask()
        self.speed_monitor_task.speed_update.connect(
            self.main_window.speed_label.setText
        )

        self.speed_monitor_runner = TaskRunner()
        self.speed_monitor_runner.cleanup_complete.connect(
            self._on_speed_monitor_stopped
        )
        self.speed_monitor_runner.run(self.speed_monitor_task.run)

    def _stop_speed_monitor(self):
        if self.speed_monitor_task:
            self.speed_monitor_task.stop()
            self.speed_monitor_task = None
        else:
            if self.is_awaiting_speed_monitor_stop:
                self.is_awaiting_speed_monitor_stop = False
                self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_speed_monitor_stopped(self):
        self.speed_monitor_runner = None
        self.is_awaiting_speed_monitor_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_zip_task_stopped(self):
        self.zip_task_runner = None
        self.is_awaiting_zip_task_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_download_task_stopped(self):
        self.download_runner = None
        self.is_awaiting_download_stop = False
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_download_complete(self):
        """Handle download completion"""
        if self.is_cancelling:
            if self._delete_files_on_cancel:
                self._cleanup_cancelled_job_files()
            self.job_finished()
            return

        self._stop_speed_monitor()
        self.main_window.progress_bar.setValue(100)

        if not self.game_data:
            if self.is_processing:
                self.job_finished()
            return

        self.main_window.drop_text_label.setText("Finalizando instalação...")
        logger.info("Starting post-download I/O processing in background thread...")
        self._ryuu_status = {"status": "skipped", "message": ""}
        self._pending_ryuu_fix_path = None
        self._pending_ryuu_error = ""
        self._pending_ryuu_apply_result = None

        size_on_disk = 0
        if self.download_task:
            size_on_disk = self.download_task.total_download_size_for_this_job

        # Capture settings
        auto_apply_goldberg_val = self.settings.value(
            "auto_apply_goldberg", False, type=bool
        )
        config_management_enabled_val = False
        try:
            config_management_enabled_val = is_slssteam_config_management_enabled()
        except OSError as e:
            logger.error(f"Error checking config management status: {e}")

        # Start the worker thread
        threading.Thread(
            target=self._run_finalize_io_worker,
            args=(size_on_disk, auto_apply_goldberg_val, config_management_enabled_val),
            daemon=True,
        ).start()

    def _run_finalize_io_worker(
        self, size_on_disk: int, auto_apply_goldberg: bool, config_enabled: bool
    ):
        """Background thread worker for post-download I/O"""
        try:
            self._finalize_acf_and_manifests(size_on_disk)
            self._persist_wrapper_metadata()
            self._prefetch_current_package_dlcs()
            self._finalize_platform_specifics(config_enabled)
            self._finalize_goldberg(auto_apply_goldberg)
            self._finalize_online_fix()
            self._finalize_greenluma(config_enabled)

        except OSError as e:
            logger.error(
                f"Critical error in post-processing thread: {e}", exc_info=True
            )
        finally:
            # Thread-safe slot invocation
            QMetaObject.invokeMethod(
                self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
            )

    def _finalize_acf_and_manifests(self, size_on_disk: int):
        # 1. ACF
        self._create_acf_file(size_on_disk)

        # 2. Manifests
        self._move_manifests_to_depotcache()

        # 3. Depot Info
        selected_depots = self.game_data.get("selected_depots_list", [])
        all_manifests = self.game_data.get("manifests", {})
        if selected_depots and all_manifests:
            self._save_main_depot_info(self.game_data, selected_depots, all_manifests)

        appid = self.game_data.get("appid")
        if appid and self.current_dest_path:
            repair_installed_app_state(self.current_dest_path, appid, logger=logger)

    def _persist_wrapper_metadata(self):
        """
        Persist wrapper metadata in the game's .DepotDownloader folder.
        Stores selected DLC IDs so uninstall can clean up AppList entries later.
        """
        if sys.platform != "win32":
            return

        if not self.game_data or not self.current_dest_path:
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)
        selected_dlcs: List[str] = self.game_data.get("selected_dlcs") or []

        if persist_selected_dlcs(game_directory, selected_dlcs):
            appid = self.game_data.get("appid", "unknown")
            logger.debug(
                f"Persisted wrapper metadata for AppID {appid} with {len(selected_dlcs)} DLC ID(s)"
            )

    def _prefetch_current_package_dlcs(self) -> None:
        if not self.current_job:
            return
        package = Path(self.current_job)
        if not package.is_file() or package.suffix.lower() != ".zip":
            return
        try:
            from core.content_manager import ContentManager

            report = ContentManager().prefetch_package(
                package,
                source=str((self.current_job_metadata or {}).get("source") or "install_zip"),
                game_dir=(
                    get_game_directory(self.current_dest_path, self.game_data)
                    if self.current_dest_path and self.game_data
                    else None
                ),
            )
            logger.info(
                "DLC prefetch scanned %s item(s) for AppID %s",
                len(report.get("dlcs", [])),
                report.get("base_appid", ""),
            )
        except Exception:
            logger.warning("DLC prefetch failed for %s", package, exc_info=True)

    def _finalize_platform_specifics(self, config_enabled: bool):
        # 4. Linux Permissions
        if sys.platform != "linux":
            return

        self._set_linux_binary_permissions()
        self._apply_linux_steam_compatibility()
        if self.slssteam_mode_was_active and config_enabled:
            self._add_appids_to_slssteam_config()

    def _apply_linux_steam_compatibility(self):
        if not self.game_data:
            return

        appid = self.game_data.get("appid")
        if not appid:
            return

        if not self.game_data.get("force_proton"):
            if self.game_data.get("apply_online_fix"):
                tool_name = self.game_data.get("proton_tool_name") or "proton_experimental"
                if apply_steam_compat_tool(appid, tool_name):
                    logger.info(
                        f"Steam compatibility forced to '{tool_name}' for Online-Fix AppID {appid}"
                    )
                return
            clear_steam_compat_tool(appid)
            return

        tool_name = self.game_data.get("proton_tool_name", "")
        tool_display = self.game_data.get("proton_tool_display_name", tool_name)
        if not tool_name:
            logger.warning(
                "Windows depots detected, but no Proton compatibility tool was available"
            )
            return

        if apply_steam_compat_tool(appid, tool_name):
            logger.info(
                f"Steam compatibility forced to '{tool_display}' for AppID {appid}"
            )

    def _finalize_goldberg(self, auto_apply: bool):
        # 5. Goldberg
        # Check if online_mode was selected in the depot dialog
        online_mode = self.game_data.get("online_mode", False) if self.game_data else False
        
        # Apply if global setting is ON OR if this specific install has online_mode enabled
        should_apply = (auto_apply or online_mode) and not self.is_cancelling and self.current_dest_path
        
        if not should_apply:
            return

        game_dir = get_game_directory(self.current_dest_path, self.game_data)

        try:
            # Pass the real AppID. The apply function will handle Spacewar (480) 
            # and force_appid.txt automatically if online_mode is enabled.
            real_appid = str(self.game_data.get("appid", ""))
            
            self.apply_goldberg_to_game(
                game_directory=game_dir,
                appid=real_appid,
                game_name=self.game_data.get("game_name", ""),
                show_dialog=False,
            )
        except OSError as e:
            logger.error(f"Error applying Goldberg: {e}")

    def _finalize_online_fix(self):
        """Busca e injeta o Online-Fix se solicitado durante a instalação."""
        if not self.game_data or not self.game_data.get("apply_online_fix"):
            self._online_fix_status = "skipped"
            self._online_fix_status_text = "Não solicitado"
            return

        game_dir = get_game_directory(self.current_dest_path, self.game_data)
        game_name = self.game_data.get("game_name", "")
        self._online_fix_status = "error"
        self._online_fix_status_text = "Falhou"
        
        logger.info(f"Iniciando automação do Online-Fix para: {game_name}")
        
        from core.online_fix_api import OnlineFixAPI
        from core.online_fix_injector import OnlineFixInjector
        
        api = OnlineFixAPI()
        injector = OnlineFixInjector()
        
        try:
            page = api.search_game(game_name)
            if not page:
                logger.warning(f"Jogo {game_name} não encontrado no Online-Fix.me")
                return
            
            folder_url = api.get_fix_download_link(page)
            if not folder_url:
                logger.warning("Link de download do Online-Fix não encontrado.")
                return
            
            files = api.get_direct_files(folder_url)
            if not files:
                logger.warning("Nenhum arquivo de fix encontrado na pasta do Online-Fix.")
                return
            
            # Baixar o primeiro fix encontrado
            file_url = files[0]
            save_path = os.path.join(get_base_path(), "downloads", os.path.basename(file_url))
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            logger.info(f"Baixando Online-Fix de: {file_url}")
            if api.download_file(file_url, save_path):
                logger.info("Download concluído. Injetando fix...")
                # Detectar loader se existir antes de injetar
                target_loader = None
                for root, _, files in os.walk(game_dir):
                    for file in files:
                        if file.lower().endswith("_loader.exe"):
                            target_loader = file
                            break
                
                # Desempacotar corretamente os 4 valores retornados pelo inject_fix
                success, found_dlls, launch_options, main_exe_path = injector.inject_fix(
                    game_dir, save_path, target_executable=target_loader
                )
                
                if success:
                    logger.info("Online-Fix aplicado com sucesso durante a instalação!")
                    self._online_fix_status = "ok"
                    self._online_fix_status_text = "Aplicado"
                    record_online_fix_layer(
                        game_dir,
                        appid=str(self.game_data.get("appid", "")),
                        game_name=game_name,
                        found_dlls=found_dlls,
                        launch_options=launch_options,
                    )
                    if sys.platform == "linux":
                        # Usar as launch_options geradas pelo próprio injetor (que já usa ';' e lida com loaders)
                        if self.game_data.get("appid"):
                            from utils.proton_tools import apply_steam_compat_tool
                            from utils.steam_config_helper import set_steam_launch_options
                            from core.steam_helpers import find_steam_install
                            
                            appid = self.game_data.get("appid")
                            proton_tool = self.game_data.get("proton_tool_name", "proton_experimental")
                            
                            # 1. Forçar Proton
                            apply_steam_compat_tool(appid, proton_tool)
                            
                            # 2. Definir Launch Options automaticamente
                            steam_root = find_steam_install()
                            if set_steam_launch_options(steam_root, appid, launch_options):
                                self._launch_options_status = "ok"
                                self._launch_options_status_text = "Configuradas"
                                logger.info(f"Launch Options configuradas automaticamente para AppID {appid}: {launch_options}")
                            else:
                                self._launch_options_status = "error"
                                self._launch_options_status_text = "Falhou"
                                logger.warning("Não foi possível configurar Launch Options automaticamente. O usuário deverá fazer manualmente.")
                else:
                    logger.error("Falha ao injetar o Online-Fix.")
            else:
                logger.error("Falha ao baixar o arquivo do Online-Fix.")
        except Exception as e:
            logger.error(f"Erro no fluxo automático do Online-Fix: {e}")

    def _finalize_greenluma(self, config_enabled: bool):
        # 6. GreenLuma Files (Win32)
        if not (self.slssteam_mode_was_active and sys.platform == "win32"):
            return

        try:
            logger.info("Looking for Steam installation...")
            steam_path = steam_helpers.find_steam_install()
            if steam_path:
                logger.info(
                    f"Steam found at {steam_path}. Checking GreenLuma config..."
                )
                self._create_greenluma_applist_files(
                    steam_path, config_enabled=config_enabled
                )
                self._copy_greenluma_bin_files(
                    steam_path, config_enabled=config_enabled
                )
                logger.info("GreenLuma configuration check complete.")
            else:
                logger.warning(
                    "Steam installation not found, skipping GreenLuma config."
                )
        except OSError as e:
            logger.error(f"GreenLuma configuration failed: {e}", exc_info=True)

    @pyqtSlot()
    def _finalize_job_logic(self):
        """Called on Main Thread. Acts as a State Machine Conductor."""
        # Force steam restart prompt to be pending if we applied Goldberg/Online mode
        current_metadata = self.current_job_metadata or {}
        if current_metadata.get("source") == "ryuu":
            self.main_window.job_queue.steam_restart_prompt_pending = True
        elif self.game_data and self.game_data.get("online_mode"):
            self.main_window.job_queue.steam_restart_prompt_pending = True
        elif self._should_prompt_for_steam_restart():
            self.main_window.job_queue.steam_restart_prompt_pending = True

        steamless_enabled = self.settings.value("use_steamless", False, type=bool)
        if steamless_enabled and not self.is_cancelling:
            if "steamless" not in self._job_steps_completed:
                self._job_steps_completed.add("steamless")
                self.main_window.drop_text_label.setText(
                    f"Running Steamless: {self.game_data.get('game_name', '')}"
                )
                try:
                    self._start_steamless_processing()
                    return
                except Exception as e:
                    logger.error(f"Steamless failed to start: {e}")

        shortcuts_enabled = self.settings.value(
            "create_application_shortcuts", False, type=bool
        )
        slssteam_mode = is_slssteam_mode_enabled()

        if (
            shortcuts_enabled
            and slssteam_mode
            and sys.platform == "linux"
            and not self.is_cancelling
        ):
            if "shortcuts_linux" not in self._job_steps_completed:
                self._job_steps_completed.add("shortcuts_linux")
                self._start_application_shortcuts_step()
                return

        achievements_enabled = self.settings.value(
            "generate_achievements", False, type=bool
        )
        if achievements_enabled and not self.is_cancelling:
            if "achievements" not in self._job_steps_completed:
                self._job_steps_completed.add("achievements")
                self.main_window.drop_text_label.setText(
                    f"Generating Achievements: {self.game_data.get('game_name', '')}"
                )
                try:
                    self._start_achievement_generation()
                    return
                except Exception as e:
                    logger.error(f"Achievement generation failed to start: {e}")
                    # Fall through to next step if it fails to start

        if (
            shortcuts_enabled
            and not self.is_cancelling
            and "shortcuts_linux" not in self._job_steps_completed
        ):
            if "shortcuts_std" not in self._job_steps_completed:
                self._job_steps_completed.add("shortcuts_std")
                self._start_application_shortcuts_step()
                return

        if self._should_offer_ryuu_fix() and "ryuu_check" not in self._job_steps_completed:
            self._job_steps_completed.add("ryuu_check")
            self._start_ryuu_check_step()
            return

        # --- FINISH ---
        logger.info("All post-processing steps complete. Finishing job.")
        self.main_window.job_queue.jobs_completed_count += 1
        if not self.is_cancelling and not getattr(self.main_window, "_shutdown_started", False):
            self.main_window.game_manager.scan_steam_libraries_async()

        self.job_finished()

    def _should_offer_ryuu_fix(self) -> bool:
        if self.is_cancelling or not self.game_data or not self.current_dest_path:
            return False
        if (self.current_job_metadata or {}).get("source") == "ryuu":
            return False
        appid = str(self.game_data.get("appid", "")).strip()
        if not appid.isdigit() or appid == "0":
            return False
        return bool(load_ryuu_auth_key())

    def _start_ryuu_check_step(self) -> None:
        game_name = self.game_data.get("game_name", "Jogo") if self.game_data else "Jogo"
        self.main_window.drop_text_label.setText(f"Verificando Ryuu Fix para {game_name}...")
        threading.Thread(target=self._run_ryuu_download_worker, daemon=True).start()

    def _run_ryuu_download_worker(self) -> None:
        try:
            if not self.game_data:
                raise RyuuClientError("Jogo invalido.")
            appid = str(self.game_data.get("appid", "")).strip()
            output_dir = Path(get_base_path()) / "ryuu_fixes"
            fix_path = RyuuClient().download(appid, output_dir, branch="public")
            self._pending_ryuu_fix_path = str(fix_path)
            self._pending_ryuu_error = ""
        except Exception as exc:
            self._pending_ryuu_fix_path = None
            self._pending_ryuu_error = str(exc)
            logger.info("Ryuu Fix nao disponivel ou falhou ao baixar: %s", exc)
        finally:
            QMetaObject.invokeMethod(
                self, "_on_ryuu_check_finished", Qt.ConnectionType.QueuedConnection
            )

    @pyqtSlot()
    def _on_ryuu_check_finished(self) -> None:
        if self.is_cancelling:
            self._finalize_job_logic()
            return

        if not self._pending_ryuu_fix_path:
            self._ryuu_status = {"status": "not_found", "message": self._pending_ryuu_error}
            self._finalize_job_logic()
            return

        try:
            from core.content_manager import ContentManager

            report = ContentManager().prefetch_package(
                self._pending_ryuu_fix_path,
                source="ryuu",
                game_dir=(
                    get_game_directory(self.current_dest_path, self.game_data)
                    if self.current_dest_path and self.game_data
                    else None
                ),
            )
            cached = sum(
                item.get("status") == "cached_installable"
                for item in report.get("dlcs", [])
            )
            self._ryuu_status = {
                "status": "prefetched",
                "message": f"Ryuu analisado; {cached} DLC(s) pronta(s) no cache.",
            }
        except Exception as exc:
            self._ryuu_status = {"status": "prefetch_error", "message": str(exc)}
            logger.warning("Falha no prefetch DLC Ryuu", exc_info=True)
        self._finalize_job_logic()

    def _run_ryuu_apply_worker(self) -> None:
        try:
            if not self.game_data or not self.current_dest_path or not self._pending_ryuu_fix_path:
                raise RyuuClientError("Dados do jogo indisponiveis.")
            appid = str(self.game_data.get("appid", "")).strip()
            game_name = self.game_data.get("game_name", "Jogo")
            game_dir = get_game_directory(self.current_dest_path, self.game_data)
            self._pending_ryuu_apply_result = apply_ryuu_fix(
                game_dir,
                self._pending_ryuu_fix_path,
                appid=appid,
                game_name=game_name,
                branch="public",
                preserve_online_fix=True,
            )
            self._pending_ryuu_error = ""
        except Exception as exc:
            self._pending_ryuu_apply_result = None
            self._pending_ryuu_error = str(exc)
            logger.error("Falha ao aplicar Ryuu Fix: %s", exc)
        finally:
            QMetaObject.invokeMethod(
                self, "_on_ryuu_apply_finished", Qt.ConnectionType.QueuedConnection
            )

    @pyqtSlot()
    def _on_ryuu_apply_finished(self) -> None:
        if self._pending_ryuu_apply_result is None:
            self._ryuu_status = {"status": "error", "message": self._pending_ryuu_error}
            QMessageBox.warning(
                self.main_window,
                "Ryuu Fix",
                "Não consegui baixar/aplicar o fix Ryuu. Verifique sua key ou tente novamente.",
            )
        else:
            skipped = self._pending_ryuu_apply_result.get("skipped_conflicts") or []
            if skipped:
                self._ryuu_status = {
                    "status": "applied_with_conflicts",
                    "message": "Ryuu aplicado sem sobrescrever arquivos do OnlineFix.",
                }
                QMessageBox.information(
                    self.main_window,
                    "Ryuu Fix",
                    "Ryuu Fix aplicado. Arquivos protegidos do OnlineFix foram mantidos.",
                )
            else:
                self._ryuu_status = {"status": "applied", "message": "Ryuu Fix aplicado."}
                QMessageBox.information(self.main_window, "Ryuu Fix", "Ryuu Fix aplicado.")
        self._finalize_job_logic()

    def _start_application_shortcuts_step(self):
        self.main_window.drop_text_label.setText(
            f"Creating Application Shortcuts: {self.game_data.get('game_name', '')}"
        )
        self._start_application_shortcuts_processing()

    def _should_prompt_for_steam_restart(self) -> bool:
        if self.is_cancelling:
            return False

        return self.slssteam_mode_was_active or self.library_mode_was_active

    @staticmethod
    def _save_main_depot_info(game_data, selected_depots, all_manifests):
        try:
            appid = game_data.get("appid")
            if not appid or not selected_depots:
                return

            main_depot_id = str(selected_depots[0])
            manifest_id = all_manifests.get(main_depot_id)
            if not manifest_id:
                return

            depots_dir = Path(get_base_path()) / "depots"
            depots_dir.mkdir(parents=True, exist_ok=True)
            depot_file = depots_dir / f"{appid}.depot"
            access_token = game_data.get("app_token", "")

            with open(depot_file, "w") as f:
                if access_token:
                    f.write(f"{main_depot_id}: {manifest_id}: {access_token}\n")
                else:
                    f.write(f"{main_depot_id}: {manifest_id}\n")
        except OSError as e:
            logger.error(f"Failed to save depot info: {e}")

    def _create_acf_file(self, size_on_disk):
        if not self.game_data or not self.current_dest_path:
            return

        try:
            write_acf_file(
                self.current_dest_path,
                self.game_data,
                size_on_disk,
                include_depots=True,
            )
        except OSError as e:
            logger.error(f"Error creating .acf file: {e}")

    def _move_manifests_to_depotcache(self):
        if not self.game_data or not self.current_dest_path:
            return

        target_depotcache_dir = os.path.join(self.current_dest_path, "depotcache")
        fixed_manifest_dir = os.path.join(tempfile.gettempdir(), "mistwalker_manifests")
        manifest_dirs = []
        if os.path.isdir(fixed_manifest_dir):
            manifest_dirs.append(fixed_manifest_dir)

        manifest_dirs.extend(
            path
            for path in glob.glob(os.path.join(tempfile.gettempdir(), "lumatools-job-*", "manifests"))
            if os.path.isdir(path)
        )

        try:
            os.makedirs(target_depotcache_dir, exist_ok=True)
            manifests_map = self.game_data.get("manifests", {})
            if not manifests_map:
                if os.path.isdir(fixed_manifest_dir):
                    shutil.rmtree(fixed_manifest_dir)
                return

            moved_count = 0
            for depot_id, manifest_gid in manifests_map.items():
                manifest_filename = f"{depot_id}_{manifest_gid}.manifest"
                source_path = next(
                    (
                        os.path.join(manifest_dir, manifest_filename)
                        for manifest_dir in manifest_dirs
                        if os.path.exists(os.path.join(manifest_dir, manifest_filename))
                    ),
                    "",
                )
                dest_path = os.path.join(target_depotcache_dir, manifest_filename)
                if source_path:
                    shutil.move(source_path, dest_path)
                    moved_count += 1

            logger.info("Moved %s manifest(s) to depotcache.", moved_count)
            if os.path.isdir(fixed_manifest_dir):
                shutil.rmtree(fixed_manifest_dir)
        except OSError as e:
            logger.error(f"Failed to move manifests to depotcache: {e}")

    def _set_linux_binary_permissions(self):
        if not self.game_data or not self.current_dest_path:
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)

        if os.path.exists(game_directory):
            self._run_chmod_recursive(game_directory)

    def _create_steamless_task(self, progress_handler):
        self.steamless_task = SteamlessTask()
        self.steamless_task.progress.connect(progress_handler)
        self.steamless_task.result.connect(self._on_steamless_complete)
        self.steamless_task.finished.connect(self._on_steamless_finished)
        self.steamless_task.error.connect(self._handle_steamless_task_error)
        return self.steamless_task

    def _reset_steamless_task(self):
        if self.steamless_task:
            self.steamless_task.stop()
            self.steamless_task = None

    def _start_steamless_processing(self):
        if not self.current_dest_path or not self.game_data:
            self._finalize_job_logic()
            return

        game_directory = get_game_directory(self.current_dest_path, self.game_data)

        if not os.path.exists(game_directory):
            self._finalize_job_logic()
            return

        if not self._game_has_windows_executables(game_directory):
            logger.info("Steamless ignorado: nenhum .exe encontrado em %s", game_directory)
            self._last_steamless_success = None
            self._last_steamless_status = "not_run"
            self._last_steamless_status_text = "Ignorado: nenhum .exe"
            self._steamless_ran = False
            self._finalize_job_logic()
            return

        logger.info("\n" + "=" * 40)
        logger.info("Starting Steamless DRM Removal...")

        steamless_task = self._create_steamless_task(logger.info)
        steamless_task.set_game_directory(game_directory)
        steamless_task.start()

        self._steamless_ran = True
        self._update_status_button_color()

    @staticmethod
    def _game_has_windows_executables(game_directory: str) -> bool:
        for _, _, files in os.walk(game_directory):
            if any(file_name.lower().endswith(".exe") for file_name in files):
                return True
        return False

    def run_steamless_manually(self, exe_path: str, game_name: Optional[str] = None):
        self._reset_steamless_task()

        self._steamless_game_name = game_name or os.path.basename(exe_path)
        self._steamless_progress_log = []
        self._steamless_manual_run = True

        logger.info(f"Starting manual Steamless processing for: {exe_path}")
        steamless_task = self._create_steamless_task(self._on_steamless_progress)
        steamless_task.set_target_exe(exe_path)
        steamless_task.start()

    def run_steamless_for_game(self, game_directory: str, game_name: str):
        self._reset_steamless_task()

        self._steamless_game_name = game_name
        self._steamless_progress_log = []
        self._steamless_manual_run = True

        logger.info(f"Starting manual Steamless processing for game: {game_name}")
        steamless_task = self._create_steamless_task(self._on_steamless_progress)
        steamless_task.set_game_directory(game_directory)
        steamless_task.start()

    def run_chmod_for_game(
        self, game_directory: str, game_name: str, show_dialog: bool = False
    ):
        logger.info(f"Starting chmod for game: {game_name}")

        def chmod_worker():
            count = self._run_chmod_recursive(game_directory)
            logger.info(f"Chmod completed: {count} files processed")

            if show_dialog:
                # Deferred import
                from ui.dialogs.chmod_resume import ChmodResumeDialog

                def show():
                    self._show_chmod_resume_dialog(game_name, count, ChmodResumeDialog)

                QTimer.singleShot(0, show)

        threading.Thread(target=chmod_worker, daemon=True).start()

    def _ensure_game_directory(self, game_directory: str, show_dialog: bool) -> bool:
        if game_directory and os.path.exists(game_directory):
            return True
        if show_dialog:
            QMessageBox.warning(
                self.main_window,
                "Diretório não encontrado",
                f"Diretório do jogo não encontrado: {game_directory}",
            )
        return False

    @staticmethod
    def _detect_elf_architecture(file_path: str) -> Optional[str]:
        """
        Detect if an ELF file is 32-bit or 64-bit.
        Returns '32', '64', or None if not detectable.
        """
        try:
            with open(file_path, "rb") as f:
                # ELF magic bytes
                magic = f.read(4)
                if magic != b"\x7fELF":
                    return None

                # Byte 4 = class (1 = 32-bit, 2 = 64-bit)
                elf_class = f.read(1)
                if elf_class == b"\x01":
                    return "32"
                elif elf_class == b"\x02":
                    return "64"
        except (IOError, OSError):
            pass
        return None

    def apply_goldberg_to_game(
        self, game_directory: str, appid: str, game_name: str, show_dialog: bool = True
    ) -> bool:
        """Apply Goldberg emulator to a game directory."""
        logger.info(f"Applying Goldberg for game: {game_name} (AppID: {appid})")

        if not self._ensure_game_directory(game_directory, show_dialog):
            return False

        target_dirs = self._find_steam_api_dirs(game_directory)
        if not target_dirs:
            if show_dialog:
                QMessageBox.information(
                    self.main_window,
                    "Nenhum arquivo da Steam API encontrado",
                    "Nenhum arquivo steam_api.dll, steam_api64.dll, libsteam_api.so ou libsteam_api64.so foi encontrado.",
                )
            return False

        goldberg_src = Paths.deps("Goldberg")
        if not goldberg_src.exists():
            if show_dialog:
                QMessageBox.critical(
                    self.main_window,
                    "Origem ausente",
                    f"Pasta do Goldberg não encontrada: {goldberg_src}",
                )
            return False

        processed = 0
        for target_dir in target_dirs:
            try:
                self._apply_goldberg_to_single_dir(target_dir, appid, goldberg_src)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to apply Goldberg in {target_dir}: {e}")

        if show_dialog:
            QMessageBox.information(
                self.main_window,
                "Aplicar Goldberg",
                f"Arquivos do Goldberg aplicados em {processed} pasta(s).",
            )
        return True

    def remove_goldberg_from_game(
        self, game_directory: str, appid: str, game_name: str, show_dialog: bool = True
    ) -> bool:
        """Remove Goldberg emulator from a game directory."""
        logger.info(f"Removing Goldberg for game: {game_name}")

        if not self._ensure_game_directory(game_directory, show_dialog):
            return False

        target_dirs = self._find_steam_api_backup_dirs(game_directory)
        if not target_dirs:
            if show_dialog:
                QMessageBox.information(
                    self.main_window,
                    "Nenhum backup encontrado",
                    "Nenhum arquivo de backup .valve foi encontrado.",
                )
            return False

        processed = 0
        for target_dir in target_dirs:
            try:
                self._remove_goldberg_from_single_dir(target_dir)
                processed += 1
            except Exception as e:
                logger.error(f"Failed to remove Goldberg from {target_dir}: {e}")

        if show_dialog:
            QMessageBox.information(
                self.main_window,
                "Remover Goldberg",
                f"Arquivos originais restaurados em {processed} pasta(s).",
            )
        return True

    def _find_steam_api_dirs(self, root_dir: str) -> Set[str]:
        """Return set of directories containing any steam_api file."""
        targets = set()
        steam_api_names = {
            "steam_api.dll",
            "steam_api64.dll",
            "libsteam_api.so",
            "libsteam_api64.so",
        }
        for root, _, files in os.walk(root_dir):
            if any(fname.lower() in steam_api_names for fname in files):
                targets.add(root)
        return targets

    def _find_steam_api_backup_dirs(self, root_dir: str) -> Set[str]:
        """Return set of directories containing .valve backup files."""
        targets = set()
        backup_suffixes = (".dll.valve", ".so.valve")
        for root, _, files in os.walk(root_dir):
            if any(fname.lower().endswith(backup_suffixes) for fname in files):
                targets.add(root)
        return targets

    def _apply_goldberg_to_single_dir(
        self, target_dir: str, appid: str, goldberg_src: Path
    ):
        """Apply Goldberg to one directory."""
        renamed_files = self._backup_steam_api_files(target_dir)
        self._copy_goldberg_matching_files(target_dir, goldberg_src, renamed_files)
        self._copy_goldberg_common_files(target_dir, goldberg_src)
        
        # Check if we are in online_mode (Spacewar mode)
        online_mode = self.game_data.get("online_mode", False) if self.game_data else False
        
        if online_mode:
            # For online mode:
            # 1. steam_appid.txt must be 480 (Spacewar)
            self._write_appid_file(target_dir, "480")
            # 2. force_appid.txt inside steam_settings must be the REAL AppID
            self._write_force_appid_file(target_dir, appid)
        else:
            # Normal offline mode
            self._write_appid_file(target_dir, appid)
            
        self._generate_interfaces_for_valve_files(target_dir, goldberg_src)

    def _write_force_appid_file(self, target_dir: str, appid: str):
        """Write force_appid.txt in steam_settings folder."""
        settings_dir = os.path.join(target_dir, "steam_settings")
        os.makedirs(settings_dir, exist_ok=True)
        force_appid_path = os.path.join(settings_dir, "force_appid.txt")
        try:
            with open(force_appid_path, "w", encoding="utf-8") as f:
                f.write(str(appid))
            logger.info(f"Wrote force_appid.txt with real AppID {appid} to {settings_dir}")
        except OSError as e:
            logger.warning(f"Failed to write force_appid.txt: {e}")

    def _backup_steam_api_files(self, directory: str) -> List[str]:
        """Rename all steam_api files to .valve. Return list of original filenames."""
        renamed = []
        patterns = [
            "steam_api.dll",
            "steam_api64.dll",
            "libsteam_api.so",
            "libsteam_api64.so",
        ]
        for name in patterns:
            src = os.path.join(directory, name)
            if os.path.exists(src):
                dst = src + ".valve"
                if not os.path.exists(dst):
                    os.rename(src, dst)
                    renamed.append(name)
        return renamed

    def _copy_goldberg_matching_files(
        self, target_dir: str, goldberg_src: Path, renamed_files: List[str]
    ):
        """For each renamed file, copy the Goldberg replacement from the goldberg deps folder."""
        for name in renamed_files:
            if name.endswith(".dll"):
                src = goldberg_src / "windows" / name
                if src.exists():
                    shutil.copy2(str(src), os.path.join(target_dir, name))
                else:
                    logger.warning(f"Goldberg file not found: {src}")

            elif name.endswith(".so"):
                backup_path = os.path.join(target_dir, name + ".valve")
                if not os.path.exists(backup_path):
                    logger.error(f"Backup file missing: {backup_path}")
                    continue

                arch = self._detect_elf_architecture(backup_path)
                if arch is None:
                    logger.warning(
                        f"Could not detect architecture of {backup_path}, skipping"
                    )
                    continue

                if arch == "32":
                    src_filename = "libsteam_api.so"
                elif arch == "64":
                    src_filename = "libsteam_api64.so"
                else:
                    logger.warning(f"Unknown architecture '{arch}' for {backup_path}")
                    continue

                src = goldberg_src / "linux" / src_filename
                if src.exists():
                    shutil.copy2(str(src), os.path.join(target_dir, name))
                    logger.info(
                        f"Copied {src_filename} (detected {arch}-bit) to {name}"
                    )
                else:
                    logger.error(
                        f"Goldberg file not found: {src} (needed for {arch}-bit)"
                    )
            else:
                continue

    def _copy_goldberg_common_files(self, target_dir: str, goldberg_src: Path):
        """Copy steam_settings folder."""
        src_settings = goldberg_src / "steam_settings"
        if src_settings.exists():
            dst_settings = os.path.join(target_dir, "steam_settings")
            if os.path.exists(dst_settings):
                shutil.rmtree(dst_settings)
            shutil.copytree(str(src_settings), dst_settings)

    def _write_appid_file(self, target_dir: str, appid: str):
        """Write steam_appid.txt"""
        appid_path = os.path.join(target_dir, "steam_appid.txt")
        try:
            with open(appid_path, "w", encoding="utf-8") as f:
                f.write(str(appid))
        except OSError as e:
            logger.warning(f"Failed to write steam_appid.txt: {e}")

    def _generate_interfaces_for_valve_files(self, target_dir: str, goldberg_src: Path):
        """
        For each .valve file that is a steam_api backup, run generate_interfaces
        and move the resulting steam_interfaces.txt to steam_settings.
        """
        steam_settings_dir = os.path.join(target_dir, "steam_settings")
        for fname in os.listdir(target_dir):
            if not fname.lower().endswith((".dll.valve", ".so.valve")):
                continue
            if "steam_api" not in fname.lower():
                continue

            # Determine bitness from filename
            is_64bit = "64" in fname
            valve_path = os.path.join(target_dir, fname)
            if self._run_generate_interfaces_for_file(
                target_dir, valve_path, is_64bit, goldberg_src
            ):
                # Move generated interfaces file if it exists
                interfaces_src = os.path.join(target_dir, "steam_interfaces.txt")
                if os.path.exists(interfaces_src):
                    os.makedirs(steam_settings_dir, exist_ok=True)
                    interfaces_dst = os.path.join(
                        steam_settings_dir, "steam_interfaces.txt"
                    )
                    shutil.move(interfaces_src, interfaces_dst)
                    logger.info(f"Moved steam_interfaces.txt to {steam_settings_dir}")

    def _run_generate_interfaces_for_file(
        self,
        game_directory: str,
        valve_file_path: str,
        is_64bit: bool,
        goldberg_src: Path,
    ) -> bool:
        """Run generate_interfaces for one .valve file. Return True on success."""
        is_windows = sys.platform == "win32"
        exe_name = f"generate_interfaces_x{'64' if is_64bit else '32'}"
        if is_windows:
            exe_name += ".exe"

        exe_path = goldberg_src / "genints" / exe_name
        if not exe_path.exists():
            logger.error(f"generate_interfaces executable not found: {exe_path}")
            return False

        valve_file_name = os.path.basename(valve_file_path)
        cmd = [str(exe_path), valve_file_name]

        try:
            result = subprocess.run(
                cmd,
                cwd=game_directory,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
                errors="replace",
            )
            if result.stdout:
                logger.info(result.stdout.strip())
            if result.stderr:
                logger.debug(f"generate_interfaces stderr: {result.stderr.strip()}")

            if result.returncode == 0:
                logger.info(f"Generate interfaces completed for {valve_file_name}")
                return True
            else:
                logger.error(
                    f"Generate interfaces failed (code {result.returncode}) for {valve_file_name}"
                )
                return False
        except Exception as e:
            logger.error(f"Error running generate_interfaces: {e}")
            return False

    def _remove_goldberg_from_single_dir(self, target_dir: str):
        """Remove Goldberg from one directory."""
        self._delete_goldberg_added_files(target_dir)
        self._restore_original_files(target_dir)

    def _delete_goldberg_added_files(self, target_dir: str):
        """Delete files/folders that were added by Goldberg."""
        # Remove steam_settings
        settings_path = os.path.join(target_dir, "steam_settings")
        if os.path.exists(settings_path):
            shutil.rmtree(settings_path)

        # Remove steam_appid.txt
        appid_path = os.path.join(target_dir, "steam_appid.txt")
        if os.path.exists(appid_path):
            os.remove(appid_path)

        # Remove any Goldberg DLLs/SOs that are not .valve
        for name in [
            "steam_api.dll",
            "steam_api64.dll",
            "libsteam_api.so",
            "libsteam_api64.so",
        ]:
            full = os.path.join(target_dir, name)
            if os.path.exists(full) and not os.path.exists(full + ".valve"):
                os.remove(full)

    def _restore_original_files(self, target_dir: str):
        """Rename .valve backups back to original names."""
        for fname in os.listdir(target_dir):
            if not fname.lower().endswith((".dll.valve", ".so.valve")):
                continue
            original = fname[:-6]  # remove .valve
            backup_path = os.path.join(target_dir, fname)
            original_path = os.path.join(target_dir, original)

            # Delete current file if it exists (Goldberg copy)
            if os.path.exists(original_path):
                os.remove(original_path)

            # Restore backup
            os.rename(backup_path, original_path)

    @staticmethod
    def _run_chmod_recursive(game_directory) -> int:
        import stat

        linux_binary_extensions = {
            ".sh",
            ".bash",
            ".x86",
            ".x86_64",
            ".bin",
            ".run",
            ".elf",
            ".pck",
        }
        elf_magic = b"\x7fELF"
        shebang_magic = b"#!"

        chmod_count = 0

        for root, _, filenames in os.walk(game_directory):
            for filename in filenames:
                file_path = os.path.join(root, filename)

                if os.path.islink(file_path):
                    continue

                should_chmod = False
                filename_lower = filename.lower()

                if any(filename_lower.endswith(ext) for ext in linux_binary_extensions):
                    should_chmod = True
                elif "." not in filename:
                    try:
                        with open(file_path, "rb") as f:
                            header = f.read(4)
                            if header.startswith(elf_magic) or header.startswith(
                                shebang_magic
                            ):
                                should_chmod = True
                    except (IOError, OSError):
                        continue

                if should_chmod:
                    try:
                        file_stat = os.stat(file_path)
                        current_mode = file_stat.st_mode
                        if not (current_mode & stat.S_IXUSR):
                            new_mode = current_mode | 0o755
                            os.chmod(file_path, new_mode)
                            chmod_count += 1
                    except OSError:
                        pass

        return chmod_count

    def _show_chmod_resume_dialog(self, game_name: str, file_count: int, dialog_class):
        dialog = dialog_class(
            game_name=game_name,
            file_count=file_count,
            success=True,
            parent=self.main_window,
        )
        dialog.exec()

    def _on_steamless_progress(self, message):
        self._steamless_progress_log.append(message)
        logger.info(message)

    def _on_steamless_complete(self, success):
        logger.info("\n" + "=" * 40)
        if success:
            logger.info("Steamless processing completed successfully")
        else:
            logger.info("Steamless processing completed with warnings or no DRM found")

        self._steamless_success = success
        self._last_steamless_success = success

    def _on_steamless_finished(self):
        if self.steamless_task:
            QTimer.singleShot(0, self._clear_steamless_task)

        if self._steamless_manual_run:
            self._show_steamless_resume_dialog()
            self._steamless_manual_run = False
            self._steamless_success = None
            return

        if self._steamless_success is not None:
            self._steamless_success = None

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _clear_steamless_task(self):
        self.steamless_task = None

    def _show_steamless_resume_dialog(self):
        # Deferred import
        from ui.dialogs.steamless_resume import SteamlessResumeDialog

        exe_count = 0
        processed_count = 0
        had_error = self._steamless_error

        for message in self._steamless_progress_log:
            if "Found " in message and "executable(s)" in message:
                try:
                    parts = message.split()
                    for i, part in enumerate(parts):
                        if part == "Found" and i + 1 < len(parts):
                            exe_count = int(parts[i + 1])
                            break
                except ValueError:
                    pass

            if "Successfully processed:" in message:
                processed_count += 1
            if "Successfully unpacked file!" in message:
                processed_count += 1
                exe_count = max(exe_count, 1)
            if "No Steam DRM detected" in message:
                exe_count = max(exe_count, 1)

        actual_success = processed_count > 0 and not had_error

        dialog = SteamlessResumeDialog(
            game_name=self._steamless_game_name,
            exe_count=exe_count,
            processed_count=processed_count,
            success=actual_success,
            parent=self.main_window,
        )
        dialog.exec()
        self._steamless_progress_log = []
        self._steamless_game_name = ""

    def _handle_steamless_task_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Steamless processing failed: {error_value}")
        self._steamless_error = True
        if self.steamless_task:
            QTimer.singleShot(0, self._clear_steamless_task)

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _start_achievement_generation(self):
        if not self.game_data:
            self._finalize_job_logic()
            return

        app_id = self.game_data.get("appid")
        if not app_id:
            self._finalize_job_logic()
            return

        # Check if SLScheevo exists before trying to run it
        from utils.helpers import get_slscheevo_path
        if not get_slscheevo_path().exists():
            logger.info("SLScheevo dependency missing; achievement generation skipped.")
            self._last_slscheevo_status = "not_run"
            self._last_slscheevo_status_text = "Ignorado: ausente"
            self._last_slscheevo_success = None
            self._slscheevo_ran = False
            self._slscheevo_error = False
            self._finalize_job_logic()
            return

        if not GenerateAchievementsTask.has_saved_account():
            logger.info("SLScheevo sem login salvo; geração de conquistas ignorada.")
            self._last_slscheevo_status = "not_run"
            self._last_slscheevo_status_text = "Ignorado: sem login"
            self._last_slscheevo_success = None
            self._slscheevo_ran = False
            self._slscheevo_error = False
            self._finalize_job_logic()
            return

        logger.info("\n" + "=" * 40)
        logger.info("Starting Steam Achievement Generation...")

        try:
            self.achievement_task = GenerateAchievementsTask()
            self.achievement_task.progress.connect(logger.info)

            self.achievement_task_runner = TaskRunner()
            self.achievement_worker = self.achievement_task_runner.run(
                self.achievement_task.run, app_id
            )
            self.achievement_task_runner.cleanup_complete.connect(
                self._on_achievement_task_cleanup
            )
        except Exception as e:
            logger.error(f"Failed to initialize achievement task: {e}")
            self._finalize_job_logic()

        self._update_status_button_color()
        self._slscheevo_ran = True

        self.achievement_worker.finished.connect(
            self._on_achievement_generation_complete
        )
        self.achievement_worker.error.connect(self._handle_achievement_error)

    def _on_achievement_generation_complete(self, result):
        if result is None:
            success = False
            message = "Unknown error"
        else:
            success = result.get("success", False)
            message = result.get("message", "Unknown status")

        self._last_slscheevo_success = success
        if success:
            logger.info(f"Achievement generation completed: {message}")
        else:
            logger.info(f"Achievement generation failed: {message}")

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _handle_achievement_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Achievement generation failed: {error_value}")
        self._last_slscheevo_success = False
        self._slscheevo_error = True

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _on_achievement_task_cleanup(self):
        self.achievement_task_runner = None
        self.achievement_task = None
        self.achievement_worker = None
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _on_application_shortcuts_task_cleanup(self):
        self.application_shortcuts_task_runner = None
        self.application_shortcuts_task = None
        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _start_application_shortcuts_processing(self):
        if not self.game_data:
            self._finalize_job_logic()
            return

        app_id = self.game_data.get("appid")
        game_name = self.game_data.get("game_name")
        sgdb_api_key = self.settings.value("sgdb_api_key", "", type=str)

        if not app_id or not sgdb_api_key:
            self._finalize_job_logic()
            return

        logger.info("\n" + "=" * 40)
        logger.info("Starting Application Shortcuts Creation...")

        self.application_shortcuts_task = ApplicationShortcutsTask()
        self.application_shortcuts_task.set_api_key(sgdb_api_key)
        self.application_shortcuts_task.progress.connect(logger.info)

        self.application_shortcuts_task_runner = TaskRunner()
        self.application_shortcuts_task_runner.cleanup_complete.connect(
            self._on_application_shortcuts_task_cleanup
        )

        worker = self.application_shortcuts_task_runner.run(
            self.application_shortcuts_task.run, app_id, game_name
        )
        worker.finished.connect(self._on_application_shortcuts_complete)
        worker.error.connect(self._handle_application_shortcuts_error)

    def _on_application_shortcuts_complete(self, result):
        if result:
            logger.info("Application shortcuts creation completed successfully")
        else:
            logger.info("Application shortcuts creation failed")

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _handle_application_shortcuts_error(self, error_info):
        _, error_value, _ = error_info
        logger.error(f"Application shortcuts creation failed: {error_value}")

        QMetaObject.invokeMethod(
            self, "_finalize_job_logic", Qt.ConnectionType.QueuedConnection
        )

    def _add_appids_to_slssteam_config(self):
        if not self.game_data:
            return

        try:
            config_path = get_user_config_path()
            if not config_path.exists():
                return

            main_appid = self.game_data.get("appid")
            game_name = self.game_data.get("game_name", "")
            if main_appid:
                add_additional_app(config_path, str(main_appid), game_name)

            selected_dlcs = self.game_data.get("selected_dlcs", [])
            dlcs = self.game_data.get("dlcs", {})

            if main_appid and selected_dlcs:
                for dlc_id in selected_dlcs:
                    dlc_name = dlcs.get(dlc_id, "")
                    add_additional_app(config_path, str(dlc_id), dlc_name)
                    add_dlc_data(config_path, str(main_appid), str(dlc_id), dlc_name)

        except OSError as e:
            logger.warning(f"Failed to add AppIDs to SLSsteam config: {e}")

    def _create_greenluma_applist_files(self, steam_path, config_enabled=True):
        if not config_enabled:
            return

        try:
            app_list_dir = os.path.join(steam_path, "AppList")
            if not os.path.exists(app_list_dir):
                os.makedirs(app_list_dir)

            if not self.game_data:
                return

            game_appid = self.game_data.get("appid")
            if not game_appid:
                return

            if not self._app_id_exists_in_applist(app_list_dir, game_appid):
                next_num = self._find_next_applist_number(app_list_dir)
                filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(game_appid)
                logger.info(
                    f"Created GreenLuma file: {filepath} for AppID: {game_appid}"
                )

            selected_dlcs: List[str] = self.game_data.get("selected_dlcs") or []
            for dlc_id in selected_dlcs:
                if not self._app_id_exists_in_applist(app_list_dir, dlc_id):
                    next_num = self._find_next_applist_number(app_list_dir)
                    filepath = os.path.join(app_list_dir, f"{next_num}.txt")
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.write(str(dlc_id))
                    logger.info(f"Created GreenLuma file: {filepath} for DLC: {dlc_id}")

        except OSError as e:
            logger.error(f"Failed to create GreenLuma AppList files: {e}")

    @staticmethod
    def _copy_greenluma_bin_files(steam_path, config_enabled=True):
        if sys.platform != "win32":
            return
        if not config_enabled:
            return

        source_dir = Paths.deps()
        files_to_copy = ["NoQuestion.bin", "StealthMode.bin"]

        for filename in files_to_copy:
            source_path = os.path.join(source_dir, filename)
            dest_path = os.path.join(steam_path, filename)

            try:
                if os.path.exists(source_path):
                    if not os.path.exists(dest_path):
                        shutil.copy2(source_path, dest_path)
                        logger.info(f"Copied {filename} to Steam folder")
            except OSError:
                pass

    @staticmethod
    def _find_next_applist_number(app_list_dir):
        if not os.path.exists(app_list_dir):
            os.makedirs(app_list_dir)
            return 1
        max_num = 0
        try:
            for filename in os.listdir(app_list_dir):
                match = re.match(r"^(\d+)\.txt$", filename)
                if match:
                    num = int(match.group(1))
                    if num > max_num:
                        max_num = num
        except (OSError, ValueError):
            pass
        return max_num + 1

    @staticmethod
    def _app_id_exists_in_applist(app_list_dir, app_id_to_check):
        if not os.path.exists(app_list_dir):
            return False
        try:
            for filename in os.listdir(app_list_dir):
                if filename.lower().endswith(".txt"):
                    filepath = os.path.join(app_list_dir, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            if f.read().strip() == app_id_to_check:
                                return True
                    except OSError:
                        pass
        except OSError:
            pass
        return False

    def _handle_task_error(self, error_info):
        if self.is_cancelling:
            return
        if not self.is_processing:
            return

        _, error_value, _ = error_info
        QMessageBox.critical(
            self.main_window, "Erro", f"Ocorreu um erro: {error_value}"
        )
        if not self.is_cancelling:
            self.job_finished()

    def job_finished(self):
        """Clean up after job completion"""
        if not self.is_processing:
            return

        logger.info(
            f"Job '{os.path.basename(self.current_job or 'Unknown')}' finished."
        )

        if self.game_data:
            self._last_installed_game = self.game_data.get("game_name", "Desconhecido")

        ddm_ok = not self.is_cancelling

        if not self._slscheevo_ran:
            slscheevo_ok = None
        elif self._slscheevo_error:
            slscheevo_ok = False
        else:
            slscheevo_ok = True

        if not self._steamless_ran:
            steamless_ok = None
        elif self._steamless_error:
            steamless_ok = False
        else:
            steamless_ok = True

        self._update_status_for_job(
            ddm_ok=ddm_ok,
            slscheevo_ok=slscheevo_ok,
            steamless_ok=steamless_ok,
        )
        self._set_post_install_summary(ddm_ok)

        self.main_window.ui_state.show_main_gif()
        self.main_window.progress_bar.setVisible(False)
        self.main_window.speed_label.setVisible(False)
        self.game_data = None
        self.current_dest_path = None
        self.current_job_metadata = None
        self.slssteam_mode_was_active = False
        self.library_mode_was_active = False
        self.is_processing = False

        self._update_status_button_color()
        self.current_job = None

        self.is_download_paused = False
        self.main_window.ui_state.pause_button.setVisible(False)
        self.main_window.ui_state.cancel_button.setVisible(False)
        self.download_task = None
        self.is_cancelling = False
        self._delete_files_on_cancel = None

        if self.speed_monitor_task:
            self.is_awaiting_speed_monitor_stop = True
            self._stop_speed_monitor()
        else:
            self.is_awaiting_speed_monitor_stop = False

        if self.download_runner is None:
            self.is_awaiting_download_stop = False

        if self.zip_task_runner is None:
            self.is_awaiting_zip_task_stop = False

        self.main_window.job_queue.check_if_safe_to_start_next_job()

    def _update_status_button_color(self):
        status = self.get_component_status()
        settings = self.main_window.settings
        accent_color = settings.value("accent_color", "#C06C84")

        ddm_status = status["ddm_status"]
        slscheevo_status = status["slscheevo_status"]
        steamless_status = status["steamless_status"]

        if (
            ddm_status == "error"
            or slscheevo_status == "error"
            or steamless_status == "error"
        ):
            overall_color = self.STATUS_ERROR
        elif (
            ddm_status == "in_progress"
            or slscheevo_status == "in_progress"
            or steamless_status == "in_progress"
        ):
            overall_color = self.STATUS_IN_PROGRESS
        elif ddm_status == "ok" or slscheevo_status == "ok" or steamless_status == "ok":
            overall_color = self.STATUS_OK
        else:
            overall_color = accent_color

        self.main_window.bottom_titlebar.update_colored_circle_button(
            self.main_window.bottom_titlebar.status_button, overall_color
        )
        self.main_window.bottom_titlebar.no_previous_state = False

    def toggle_pause(self):
        if not self.download_task:
            return

        self.is_download_paused = not self.is_download_paused

        try:
            self.download_task.toggle_pause(self.is_download_paused)
            if self.is_download_paused:
                self.main_window.ui_state.pause_button.setText("Retomar")
                self.main_window.drop_text_label.setText(
                    f"Pausado: {os.path.basename(self.current_job)}"
                )
                self._stop_speed_monitor()
            else:
                self.main_window.ui_state.pause_button.setText("Pausar")
                self.main_window.drop_text_label.setText(
                    f"Baixando: {os.path.basename(self.current_job)}"
                )
                self._start_speed_monitor()
        except Exception as e:
            logger.error(f"Failed to toggle pause: {e}")

    def cancel_current_job(self):
        if not self.download_task or not self.current_job:
            return

        reply = QMessageBox.question(
            self.main_window,
            "Cancelar trabalho",
            (
                "Tem certeza de que deseja cancelar o download de "
                f"'{os.path.basename(self.current_job)}'?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.No:
            return

        logger.info(f"--- Cancelling job: {os.path.basename(self.current_job)} ---")
        self.is_cancelling = True
        if self.download_runner is not None:
            self.is_awaiting_download_stop = True

        existing_install = self._detect_existing_installation()
        self._delete_files_on_cancel = self._confirm_delete_on_cancel(existing_install)

        if self.download_task:
            self.download_task.stop()
        self._kill_download_process()

        if self.achievement_task:
            self.achievement_task.stop()

        if self.steamless_task:
            self.steamless_task.stop()

    def _detect_existing_installation(self) -> bool:
        if not self.current_dest_path or not self.game_data:
            return False

        current_job_metadata = self.current_job_metadata or {}
        install_path = current_job_metadata.get("install_path")
        if install_path and os.path.exists(install_path):
            return True

        steamapps_dir = os.path.join(self.current_dest_path, "steamapps")
        appmanifest_path = os.path.join(
            steamapps_dir,
            f"appmanifest_{self.game_data.get('appid', '')}.acf",
        )
        if os.path.exists(appmanifest_path):
            return True

        game_dir = get_game_directory(self.current_dest_path, self.game_data)
        if os.path.isdir(game_dir):
            try:
                with os.scandir(game_dir) as entries:
                    for _ in entries:
                        return True
            except OSError:
                return True

        return False

    def _confirm_delete_on_cancel(self, existing_install: bool) -> bool:
        if existing_install:
            message = (
                "Foi detectada uma instalação existente. Deseja apagar os arquivos deste trabalho cancelado?"
            )
            default_button = QMessageBox.StandardButton.No
        else:
            message = "Deseja apagar os arquivos baixados parcialmente deste trabalho?"
            default_button = QMessageBox.StandardButton.Yes

        reply = QMessageBox.question(
            self.main_window,
            "Cancelar download",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _kill_download_process(self):
        if self.download_task and self.download_task.process:
            if psutil is None:
                logger.error("psutil unavailable; cannot terminate process safely.")
                return
            try:
                p = psutil.Process(self.download_task.process.pid)
                for child in p.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                p.kill()
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                logger.error(f"Failed to kill process: {e}")

            self.download_task.process = None
            self.download_task.process_pid = None

    def _cleanup_cancelled_job_files(self):
        if not self.game_data or not self.current_dest_path:
            return

        try:
            steamapps_dir = os.path.join(self.current_dest_path, "steamapps")
            common_dir = os.path.join(steamapps_dir, "common")
            game_dir = get_game_directory(self.current_dest_path, self.game_data)
            acf_path = os.path.join(
                steamapps_dir, f"appmanifest_{self.game_data['appid']}.acf"
            )

            if os.path.exists(game_dir):
                shutil.rmtree(game_dir)
            if os.path.exists(acf_path):
                os.remove(acf_path)

            temp_manifest_dir = os.path.join(
                tempfile.gettempdir(), "mistwalker_manifests"
            )
            if os.path.exists(temp_manifest_dir):
                shutil.rmtree(temp_manifest_dir)

            if not self.slssteam_mode_was_active:
                try:
                    if os.path.exists(common_dir):
                        os.rmdir(common_dir)
                    if os.path.exists(steamapps_dir):
                        os.rmdir(steamapps_dir)
                except OSError:
                    pass

        except OSError as e:
            logger.error(f"Failed during cancel cleanup: {e}")

    def download_slssteam(self, steam_path=None):
        if sys.platform != "linux":
            logger.info("Ignoring SLSsteam installation request outside Linux.")
            QMessageBox.information(
                self.main_window,
                "SLSsteam indisponível",
                "O SLSsteam é uma integração Linux. No Windows, o LumaTools usa o fluxo nativo da plataforma.",
            )
            return

        if (
            self.slssteam_download_task is not None
            and self.slssteam_download_runner is not None
        ):
            return

        self.slssteam_download_task = DownloadSLSsteamTask(steam_path=steam_path)
        self.slssteam_download_task.progress.connect(self._handle_slssteam_progress)
        self.slssteam_download_task.progress_percentage.connect(
            self._handle_slssteam_progress_percentage
        )
        self.slssteam_download_task.completed.connect(
            self._on_slssteam_download_complete
        )
        self.slssteam_download_task.error.connect(self._handle_slssteam_download_error)

        self.slssteam_download_runner = TaskRunner()
        worker = self.slssteam_download_runner.run(self.slssteam_download_task.run)
        worker.error.connect(self._handle_task_error)

    @staticmethod
    def _handle_slssteam_progress(message):
        logger.info(f"SLSsteam: {message}")

    def _handle_slssteam_progress_percentage(self, percentage):
        pass

    def _on_slssteam_download_complete(self, message):
        logger.info(f"SLSsteam download completed: {message}")
        QMessageBox.information(
            self.main_window, "Instalação do SLSsteam concluída", message
        )
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

    def _handle_slssteam_download_error(self):
        logger.error("SLSsteam download failed")
        QMessageBox.critical(
            self.main_window,
            "Erro",
            "Falha ao baixar o SLSsteam. Verifique sua conexão com a internet.",
        )
        self.slssteam_download_task = None
        self.slssteam_download_runner = None

    def cleanup(self):
        """Clean up all tasks during shutdown"""
        self._stop_speed_monitor()

        if self.speed_monitor_runner is not None:
            try:
                self.speed_monitor_runner.stop(wait_ms=500, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping speed monitor runner during cleanup: {e}")
            self.speed_monitor_runner = None

        if self.download_task and self.download_task.process:
            self.download_task.stop()
            self._kill_download_process()

        if self.download_runner is not None:
            try:
                self.download_runner.stop(wait_ms=1000, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping download runner during cleanup: {e}")
            self.download_runner = None

        if self.zip_task_runner is not None:
            try:
                self.zip_task_runner.stop(wait_ms=1000, terminate_on_timeout=True)
            except Exception as e:
                logger.debug(f"Error stopping zip task runner during cleanup: {e}")
            self.zip_task_runner = None

        if self.achievement_task:
            self.achievement_task.stop()
        if self.achievement_task_runner is not None:
            try:
                self.achievement_task_runner.stop(
                    wait_ms=1000, terminate_on_timeout=True
                )
            except Exception as e:
                logger.debug(
                    f"Error stopping achievement task runner during cleanup: {e}"
                )
            self.achievement_task_runner = None
            self.achievement_task = None

        if self.steamless_task:
            self.steamless_task.stop()

        if self.application_shortcuts_task:
            self.application_shortcuts_task.stop()
        if self.application_shortcuts_task_runner is not None:
            try:
                self.application_shortcuts_task_runner.stop(
                    wait_ms=1000, terminate_on_timeout=True
                )
            except Exception as e:
                logger.debug(
                    "Error stopping application shortcuts runner during cleanup: %s", e
                )
            self.application_shortcuts_task_runner = None
        self.application_shortcuts_task = None

        if self.slssteam_download_task:
            self.slssteam_download_task.stop()
        if self.slssteam_download_runner is not None:
            try:
                self.slssteam_download_runner.stop(
                    wait_ms=1000, terminate_on_timeout=True
                )
            except Exception as e:
                logger.debug(
                    "Error stopping SLSsteam download runner during cleanup: %s", e
                )
            self.slssteam_download_runner = None
        self.slssteam_download_task = None

    def get_component_status(self):
        if self.is_processing:
            if self.download_task or self.zip_task:
                ddm_status = "in_progress"
                ddm_status_text = "Baixando..."
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
            elif self.steamless_task:
                ddm_status = "ok"
                ddm_status_text = "Concluído"
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = "in_progress"
                steamless_status_text = "Executando..."
            elif self.achievement_task:
                ddm_status = "ok"
                ddm_status_text = "Concluído"
                slscheevo_status = "in_progress"
                slscheevo_status_text = "Gerando conquistas..."
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
            else:
                ddm_status = self._last_ddm_status
                ddm_status_text = self._last_ddm_status_text
                slscheevo_status = self._last_slscheevo_status
                slscheevo_status_text = self._last_slscheevo_status_text
                steamless_status = self._last_steamless_status
                steamless_status_text = self._last_steamless_status_text
        else:
            ddm_status = self._last_ddm_status
            ddm_status_text = self._last_ddm_status_text
            slscheevo_status = self._last_slscheevo_status
            slscheevo_status_text = self._last_slscheevo_status_text
            steamless_status = self._last_steamless_status
            steamless_status_text = self._last_steamless_status_text

        return {
            "ddm_status": ddm_status,
            "ddm_status_text": ddm_status_text,
            "slscheevo_status": slscheevo_status,
            "slscheevo_status_text": slscheevo_status_text,
            "steamless_status": steamless_status,
            "steamless_status_text": steamless_status_text,
        }

    def _get_steamless_status_text(self):
        if self._last_steamless_success is None:
            return "Pronto"
        elif self._last_steamless_success:
            return "Sucesso"
        else:
            return "Concluído (nenhum DRM encontrado)"

    def _update_status_for_job(self, ddm_ok=True, slscheevo_ok=None, steamless_ok=None):
        self._last_ddm_status = "ok" if ddm_ok else "error"
        self._last_ddm_status_text = "Concluído" if ddm_ok else "Falhou"

        if slscheevo_ok is None:
            self._last_slscheevo_status = "not_run"
            if not self._last_slscheevo_status_text.startswith("Ignorado"):
                self._last_slscheevo_status_text = "N/D"
        else:
            self._last_slscheevo_status = "ok" if slscheevo_ok else "error"
            self._last_slscheevo_status_text = "Concluído" if slscheevo_ok else "Falhou"

        if steamless_ok is None:
            self._last_steamless_status = "not_run"
            if not self._last_steamless_status_text.startswith("Ignorado"):
                self._last_steamless_status_text = "N/D"
        else:
            self._last_steamless_status = "ok" if steamless_ok else "error"
            self._last_steamless_status_text = self._get_steamless_status_text()

    def _set_post_install_summary(self, installed_ok: bool) -> None:
        if not self.main_window or not self.game_data:
            return

        game_name = self.game_data.get("game_name", "Jogo")
        lines = [
            f"{'OK' if installed_ok else 'ERRO'} {game_name} instalado"
        ]

        if self._online_fix_status == "ok":
            lines.append("OK OnlineFix aplicado")
        elif self._online_fix_status == "error":
            lines.append("AVISO OnlineFix não foi aplicado")

        if self._launch_options_status == "ok":
            lines.append("OK Launch Options configuradas")
        elif self._launch_options_status == "error":
            lines.append("AVISO Launch Options não foram configuradas")

        if self._last_steamless_status_text.startswith("Ignorado"):
            lines.append(f"INFO Steamless {self._last_steamless_status_text.lower()}")
        elif self._last_steamless_status == "ok":
            lines.append(f"OK Steamless: {self._last_steamless_status_text}")
        elif self._last_steamless_status == "error":
            lines.append("AVISO Steamless falhou")

        if self._last_slscheevo_status_text.startswith("Ignorado"):
            lines.append(f"INFO SLScheevo {self._last_slscheevo_status_text.lower()}")
        elif self._last_slscheevo_status == "ok":
            lines.append("OK SLScheevo concluído")
        elif self._last_slscheevo_status == "error":
            lines.append("AVISO SLScheevo falhou")

        if sys.platform == "linux":
            slssteam_status = DownloadSLSsteamTask.installed_library_status()
            if not slssteam_status.get("compatible"):
                lines.append(
                    "AVISO SLSsteam incompatível: Steam será aberta sem injeção"
                )

        if self._ryuu_status.get("status") in {"applied", "applied_with_conflicts"}:
            lines.append("OK Ryuu Fix aplicado")
        elif self._ryuu_status.get("status") == "error":
            lines.append("AVISO Ryuu Fix não foi aplicado")

        self.main_window.drop_text_label.setText("\n".join(lines))
