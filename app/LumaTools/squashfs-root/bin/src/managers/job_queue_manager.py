import os
import sys
import logging
import time
import threading
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt, QMetaObject, Q_ARG, QTimer, QObject, pyqtSignal

from core import steam_helpers
from core.tasks.download_slssteam_task import DownloadSLSsteamTask
from utils.helpers import get_base_path

logger = logging.getLogger(__name__)

SLSSTEAM_REPAIR_COOLDOWN_SECONDS = 24 * 60 * 60


class JobQueueManager(QObject):
    user_message_requested = pyqtSignal(str, str, str)

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.job_queue = []
        self.jobs_completed_count = 0
        self.steam_restart_prompt_pending = False
        self.is_showing_completion_dialog = False
        self.user_message_requested.connect(self._show_message_box)

    def add_job(self, file_path, metadata=None):
        """Add a job to the queue (Thread-Safe)"""
        if threading.current_thread() is not threading.main_thread():
            QMetaObject.invokeMethod(
                self.main_window,
                "add_job_safely",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, file_path),
            )
            return

        if not os.path.exists(file_path):
            logger.error(f"Failed to add job: file {file_path} does not exist.")
            QMessageBox.critical(
                self.main_window,
                "Erro",
                f"Não foi possível adicionar o trabalho: arquivo não encontrado em {file_path}",
            )
            return

        job = {"path": file_path, "metadata": metadata or {}}
        self.job_queue.append(job)
        logger.info(f"Added new job to queue: {os.path.basename(file_path)}")

        self._update_ui_state()

        if not self.main_window.task_manager.is_processing:
            logger.info("Not processing, starting new job from queue.")
            if getattr(self.main_window, "log_output", None) is not None:
                self.main_window.log_output.clear()
            self._start_next_job()
        else:
            logger.info("App is busy, job added to queue.")

    def _queue_list_widget(self):
        ui_state = getattr(self.main_window, "ui_state", None)
        if ui_state is None:
            return None
        return getattr(ui_state, "queue_list_widget", None)

    def move_item_up(self):
        """Move selected queue item up"""
        queue_list = self._queue_list_widget()
        if queue_list is None:
            return
        current_row = queue_list.currentRow()
        if current_row > 0:
            item = self.job_queue.pop(current_row)
            self.job_queue.insert(current_row - 1, item)
            self._update_queue_display()
            queue_list.setCurrentRow(current_row - 1)

    def move_item_down(self):
        """Move selected queue item down"""
        queue_list = self._queue_list_widget()
        if queue_list is None:
            return
        current_row = queue_list.currentRow()
        if current_row != -1 and current_row < len(self.job_queue) - 1:
            item = self.job_queue.pop(current_row)
            self.job_queue.insert(current_row + 1, item)
            self._update_queue_display()
            queue_list.setCurrentRow(current_row + 1)

    def remove_item(self):
        """Remove selected queue item"""
        queue_list = self._queue_list_widget()
        if queue_list is None:
            return
        current_row = queue_list.currentRow()
        if current_row == -1:
            logger.debug("Remove item clicked, but no item is selected.")
            return

        try:
            removed_job = self.job_queue.pop(current_row)
            logger.info(
                f"Removed job from queue: {os.path.basename(removed_job['path'])}"
            )
            self._update_queue_display()

            if current_row < queue_list.count():
                queue_list.setCurrentRow(current_row)
            elif queue_list.count() > 0:
                queue_list.setCurrentRow(current_row - 1)

        except Exception as e:
            logger.error(f"Error removing queue item: {e}", exc_info=True)

    def _start_next_job(self):
        """Start the next job in queue"""
        self._update_ui_state()

        if not self.job_queue:
            self._handle_queue_completion()
            return

        next_job = self.job_queue[0]
        file_path = next_job["path"]
        metadata = next_job.get("metadata", {})

        self.main_window.task_manager.start_zip_processing(file_path, metadata)

        self.job_queue.pop(0)
        self._update_ui_state()

    def _handle_queue_completion(self):
        """Handle when queue is empty"""
        if self.is_showing_completion_dialog:
            return

        self.is_showing_completion_dialog = True
        try:
            was_pending = self.steam_restart_prompt_pending
            self.steam_restart_prompt_pending = False

            if was_pending:
                from utils.settings import get_settings

                settings = get_settings()
                prompt_steam_restart = settings.value(
                    "prompt_steam_restart", True, type=bool
                )

                if prompt_steam_restart:
                    QTimer.singleShot(0, self._prompt_for_steam_restart)
                else:
                    logger.info(
                        "Steam restart prompt disabled by settings. Skipping prompt."
                    )
            elif self.jobs_completed_count > 0:
                # Force bringing window to front if it was hidden/minimized
                if self.main_window:
                    self.main_window.show()
                    self.main_window.raise_()
                    self.main_window.activateWindow()
                    
                QMessageBox.information(
                    self.main_window,
                    "Fila concluída",
                    f"Todos os {self.jobs_completed_count} trabalho(s) foram concluídos com sucesso!",
                )

            self.jobs_completed_count = 0
        finally:
            self.is_showing_completion_dialog = False

    def _update_ui_state(self):
        """Update UI based on queue state"""
        if not self.main_window or not self.main_window.isVisible():
            return

        has_jobs = len(self.job_queue) > 0
        is_processing = self.main_window.task_manager.is_processing

        ui_state = getattr(self.main_window, "ui_state", None)
        if ui_state is not None:
            ui_state.update_queue_visibility(is_processing, has_jobs)
        self._update_queue_display()

    def _update_queue_display(self):
        """Update the queue list widget"""
        queue_list = self._queue_list_widget()
        if queue_list is None:
            return
        queue_list.clear()
        queue_list.addItems([os.path.basename(job["path"]) for job in self.job_queue])

    def _check_if_safe_to_start_next_job(self):
        """Check if it's safe to start the next job"""
        if (
            not self.main_window.task_manager.is_processing
            and not self.main_window.task_manager.is_awaiting_zip_task_stop
            and not self.main_window.task_manager.is_awaiting_speed_monitor_stop
            and not self.main_window.task_manager.is_awaiting_download_stop
            and not self.main_window.task_manager.achievement_task_runner
        ):
            logger.debug("All thread cleanup flags are clear. Safe to start next job.")
            self._start_next_job()
        else:
            logger.debug(
                f"Not starting next job yet. State: "
                f"is_processing={self.main_window.task_manager.is_processing}, "
                f"awaiting_zip={self.main_window.task_manager.is_awaiting_zip_task_stop}, "
                f"awaiting_speed={self.main_window.task_manager.is_awaiting_speed_monitor_stop}, "
                f"awaiting_download={self.main_window.task_manager.is_awaiting_download_stop}, "
                f"achievement_runner={self.main_window.task_manager.achievement_task_runner is not None}"
            )

    def check_if_safe_to_start_next_job(self):
        self._check_if_safe_to_start_next_job()

    def _prompt_for_steam_restart(self):
        """Prompt user to restart Steam (Run via QTimer on Main Thread)"""
        reply = QMessageBox.question(
            self.main_window,
            "Reiniciar Steam",
            "Foram criadas alterações integradas ao Steam. Deseja reiniciar o Steam agora para aplicá-las?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            logger.info("User agreed to restart Steam.")
            # Run heavy lifting in background
            threading.Thread(target=self._perform_steam_restart, daemon=True).start()

    def _perform_steam_restart(self):
        """Execute Steam restart logic in background thread"""
        try:
            if sys.platform == "linux":
                logger.info("Attempting to kill Steam process...")
                steam_helpers.kill_steam_process()
                time.sleep(1)

                result = steam_helpers.start_steam()

                if result == "MISSING_SLSSTEAM":
                    logger.warning("SLSsteam missing; attempting automatic repair.")
                    repaired = self._repair_slssteam()
                    if repaired and steam_helpers.start_steam() == "SUCCESS":
                        logger.info("Steam started successfully after SLSsteam installation.")
                    else:
                        steam_helpers.start_steam_plain()
                        self._show_slssteam_fallback_message(
                            "SLSsteam não encontrado",
                            "O jogo foi instalado normalmente. A Steam foi aberta sem SLSsteam porque não há bibliotecas compatíveis instaladas.",
                        )
                elif result == "SLSSTEAM_INCOMPATIBLE":
                    logger.warning("SLSsteam incompatible; attempting automatic repair.")
                    repaired = self._repair_slssteam()
                    if repaired:
                        logger.info("Retrying Steam start after SLSsteam repair.")
                        retry_result = steam_helpers.start_steam()
                        if retry_result == "SUCCESS":
                            logger.info("Steam started successfully after SLSsteam repair.")
                        else:
                            steam_helpers.start_steam_plain()
                            self._show_slssteam_fallback_message(
                                "SLSsteam incompatível",
                                "O jogo foi instalado normalmente. A Steam foi aberta sem SLSsteam porque as bibliotecas detectadas não combinam com o Steam.",
                            )
                    else:
                        steam_helpers.start_steam_plain()
                        self._show_slssteam_fallback_message(
                            "SLSsteam incompatível",
                            "O jogo foi instalado normalmente. A Steam foi aberta sem SLSsteam para evitar erro ELFCLASS.",
                        )
                elif result == "SUCCESS":
                    logger.info("Steam started successfully with cached libraries.")
                else:
                    logger.warning("Failed to start Steam.")
                    self._show_message_safe(
                        "Falha na execução",
                        "Não foi possível iniciar o Steam.",
                        "critical",
                    )

            else:
                # Windows
                steam_path = steam_helpers.find_steam_install()
                if steam_path:
                    logger.info("Closing Steam...")
                    if not steam_helpers.kill_steam_process():
                        logger.info(
                            "Steam process was not running or could not be killed."
                        )

                    time.sleep(1)
                    logger.info("Restarting Steam with native Windows launch flow...")
                    if steam_helpers.start_steam() != "SUCCESS":
                        self._show_message_safe(
                            "Falha na execução",
                            "Não foi possível reiniciar o Steam no Windows.",
                        )
                else:
                    self._show_message_safe(
                        "Erro",
                        "Não foi possível localizar a instalação do Steam.",
                    )

        except Exception as e:
            logger.error(f"Error during Steam restart: {e}")

    def _repair_slssteam(self) -> bool:
        if self._slssteam_repair_on_cooldown():
            logger.info("Skipping SLSsteam repair: cooldown is active.")
            return False

        try:
            message = DownloadSLSsteamTask.install_latest_blocking()
            logger.info("Automatic SLSsteam repair completed: %s", message)
            repaired = bool(DownloadSLSsteamTask.installed_library_status().get("compatible"))
            if repaired:
                self._clear_slssteam_repair_marker()
            return repaired
        except Exception as exc:
            logger.error("Automatic SLSsteam repair failed: %s", exc, exc_info=True)
            self._write_slssteam_repair_marker()
            return False

    @staticmethod
    def _slssteam_repair_marker() -> Path:
        return get_base_path() / "slssteam_repair_failed_at"

    def _slssteam_repair_on_cooldown(self) -> bool:
        marker = self._slssteam_repair_marker()
        try:
            failed_at = float(marker.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return False
        return time.time() - failed_at < SLSSTEAM_REPAIR_COOLDOWN_SECONDS

    def _write_slssteam_repair_marker(self) -> None:
        try:
            self._slssteam_repair_marker().write_text(str(time.time()), encoding="utf-8")
        except OSError:
            logger.debug("Failed to write SLSsteam repair cooldown marker", exc_info=True)

    def _clear_slssteam_repair_marker(self) -> None:
        try:
            self._slssteam_repair_marker().unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to clear SLSsteam repair cooldown marker", exc_info=True)

    def _show_slssteam_fallback_message(self, title: str, detail: str) -> None:
        self._show_message_safe(
            title,
            f"{detail}\n\nIsso não significa que o download falhou.",
            "warning",
        )

    def _show_message_box(self, title, text, level):
        parent = self.main_window if self.main_window and self.main_window.isVisible() else QApplication.activeWindow()
        if level == "warning":
            QMessageBox.warning(parent, title, text)
            return
        QMessageBox.critical(parent, title, text)

    def _show_message_safe(self, title, text, level="critical"):
        """Forward a message box request to the main Qt thread."""
        logger.error("MSG: %s - %s", title, text)
        self.user_message_requested.emit(title, text, level)

    def clear(self):
        """Clear the job queue"""
        self.job_queue.clear()
        self._update_ui_state()
