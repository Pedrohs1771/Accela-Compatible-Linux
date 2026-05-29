import logging
import os
import time

from PyQt6.QtCore import QObject, QTimer

try:
    from pypresence import Presence
except ImportError:
    Presence = None

logger = logging.getLogger(__name__)


class DiscordPresenceManager(QObject):
    """Provide optional Discord Rich Presence for ACCELA."""

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.rpc = None
        self.connected = False
        self.started_at = int(time.time())
        self.last_payload = None
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.update_presence)
        self.reload_settings()

    def reload_settings(self) -> None:
        enabled = self.settings.value("discord_presence_enabled", False, type=bool)
        client_id = self.settings.value("discord_presence_client_id", "", type=str).strip()

        if not enabled or not client_id or Presence is None:
            self._disconnect()
            if enabled and Presence is None:
                logger.warning(
                    "Discord Rich Presence enabled, but pypresence is not installed."
                )
            return

        if self.rpc and self.connected and getattr(self.rpc, "client_id", None) == client_id:
            self.timer.start()
            self.update_presence()
            return

        self._disconnect()

        try:
            self.rpc = Presence(client_id)
            self.rpc.connect()
            self.connected = True
            self.started_at = int(time.time())
            self.timer.start()
            self.update_presence()
            logger.info("Discord Rich Presence connected successfully.")
        except Exception as exc:
            logger.warning("Failed to initialize Discord Rich Presence: %s", exc)
            self._disconnect()

    def update_presence(self) -> None:
        if not self.connected or not self.rpc:
            return

        payload = self._build_payload()
        if payload == self.last_payload:
            return

        try:
            self.rpc.update(**payload)
            self.last_payload = payload
        except Exception as exc:
            logger.warning("Failed to update Discord Rich Presence: %s", exc)
            self._disconnect()

    def _build_payload(self) -> dict:
        queue_count = len(self.main_window.job_queue.job_queue)
        task_manager = self.main_window.task_manager
        last_game = getattr(task_manager, "_last_installed_game", "") or "Nenhum ainda"

        if task_manager.is_processing:
            current_name = ""
            if getattr(task_manager, "game_data", None):
                current_name = task_manager.game_data.get("game_name", "")
            if not current_name and task_manager.current_job:
                current_name = os.path.basename(task_manager.current_job)
            details = f"Baixando {current_name or 'conteúdo'}"
            state = f"Fila restante: {queue_count}"
        elif queue_count:
            details = "Organizando a fila"
            state = f"{queue_count} item(ns) aguardando"
        else:
            details = "Gerenciando a biblioteca"
            state = f"Último jogo: {last_game}"

        payload = {
            "details": details,
            "state": state,
            "start": self.started_at,
        }

        large_image = self.settings.value(
            "discord_presence_large_image", "", type=str
        ).strip()
        small_image = self.settings.value(
            "discord_presence_small_image", "", type=str
        ).strip()

        if large_image:
            payload["large_image"] = large_image
            payload["large_text"] = "ACCELA em execucao"
        if small_image:
            payload["small_image"] = small_image
            payload["small_text"] = "ACCELA em tempo real"

        return payload

    def _disconnect(self) -> None:
        self.timer.stop()
        self.last_payload = None

        if self.rpc is not None:
            try:
                self.rpc.clear()
            except Exception:
                pass
            try:
                self.rpc.close()
            except Exception:
                pass

        self.rpc = None
        self.connected = False

    def shutdown(self) -> None:
        self._disconnect()
