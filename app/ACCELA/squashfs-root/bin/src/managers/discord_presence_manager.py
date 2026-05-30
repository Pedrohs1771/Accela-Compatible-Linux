from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from PyQt6.QtCore import QObject, QTimer

try:
    from pypresence import Presence
except ImportError:
    Presence = None

logger = logging.getLogger(__name__)


class DiscordPresenceManager(QObject):
    """Discord Rich Presence with graceful reconnects and zero-noise behavior."""

    DEFAULT_CLIENT_ID_ENV = "ACCELA_DISCORD_CLIENT_ID"
    DEFAULT_REPO_URL = "https://github.com/Pedrohs1771/Accela-Compatible-Linux"
    DEFAULT_RELEASES_URL = (
        "https://github.com/Pedrohs1771/Accela-Compatible-Linux/releases/latest"
    )
    DEFAULT_LARGE_IMAGE = "accela_large"
    DEFAULT_ASSET_TEXT = "ACCELA Compatible Linux"
    DEFAULT_SMALL_IMAGES = {
        "idle": "accela_idle",
        "library": "accela_icon",
        "zip_import": "accela_idle",
        "downloading": "accela_downloading",
        "paused": "accela_warning",
        "installing": "accela_installing",
        "steam_restart_pending": "accela_steam",
        "update_available": "accela_update",
        "updating": "accela_update",
        "cloud_sync": "accela_cloud",
        "success": "accela_success",
        "error": "accela_error",
    }

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.presence_factory = Presence
        self.rpc = None
        self.connected = False
        self.client_id = ""
        self.started_at = int(time.time())
        self.last_payload: Optional[dict[str, Any]] = None
        self.last_push_at = 0.0
        self.minimum_update_interval = 5.0

        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.timeout.connect(self.update_presence)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(30000)
        self.reconnect_timer.timeout.connect(self._attempt_reconnect)

        self.reload_settings()

    def reload_settings(self) -> None:
        enabled = self.settings.value("discord_presence_enabled", True, type=bool)
        client_id = self._get_client_id()

        if not enabled:
            self._disconnect(schedule_reconnect=False)
            return

        if self.presence_factory is None:
            logger.warning("Discord Rich Presence enabled, but pypresence is missing.")
            self._disconnect(schedule_reconnect=False)
            return

        if not client_id:
            logger.info(
                "Discord Rich Presence aguardando Client ID. Defina ACCELA_DISCORD_CLIENT_ID ou configure nas opções avançadas."
            )
            self._disconnect(schedule_reconnect=False)
            return

        if self.rpc and self.connected and self.client_id == client_id:
            self.timer.start()
            self.update_presence(force=True)
            return

        self._disconnect(schedule_reconnect=False)
        self.client_id = client_id
        self._connect()

    def update_presence(self, force: bool = False) -> None:
        if not self.connected or not self.rpc:
            return

        payload = self._build_payload()
        if not force and payload == self.last_payload:
            return

        now = time.time()
        if not force and (now - self.last_push_at) < self.minimum_update_interval:
            return

        try:
            self.rpc.update(**payload)
            self.last_payload = payload
            self.last_push_at = now
        except Exception as exc:
            logger.warning("Failed to update Discord Rich Presence: %s", exc)
            self._disconnect(schedule_reconnect=True)

    def _attempt_reconnect(self) -> None:
        if self.connected:
            self.reconnect_timer.stop()
            return
        if not self.client_id:
            self.client_id = self._get_client_id()
        if not self.client_id:
            return
        self._connect()

    def _connect(self) -> None:
        if self.presence_factory is None or not self.client_id:
            return

        try:
            self.rpc = self.presence_factory(self.client_id)
            self.rpc.connect()
            self.connected = True
            self.started_at = int(time.time())
            self.last_payload = None
            self.timer.start()
            self.reconnect_timer.stop()
            self.update_presence(force=True)
            logger.info("Discord Rich Presence connected successfully.")
        except Exception as exc:
            logger.warning("Failed to initialize Discord Rich Presence: %s", exc)
            self._disconnect(schedule_reconnect=True)

    def _get_client_id(self) -> str:
        configured = self.settings.value("discord_presence_client_id", "", type=str).strip()
        if configured:
            return configured
        return os.environ.get(self.DEFAULT_CLIENT_ID_ENV, "").strip()

    def _build_payload(self) -> dict[str, Any]:
        details, state, key = self._build_activity_state()
        payload: dict[str, Any] = {
            "details": details,
            "state": state,
            "start": self.started_at,
        }

        large_image = self.settings.value(
            "discord_presence_large_image", self.DEFAULT_LARGE_IMAGE, type=str
        ).strip() or self.DEFAULT_LARGE_IMAGE
        if large_image:
            payload["large_image"] = large_image
            payload["large_text"] = self.DEFAULT_ASSET_TEXT

        explicit_small_image = self.settings.value(
            "discord_presence_small_image", "", type=str
        ).strip()
        small_image = explicit_small_image or self.DEFAULT_SMALL_IMAGES.get(key, "accela_icon")
        if small_image:
            payload["small_image"] = small_image
            payload["small_text"] = state

        payload["buttons"] = [
            {"label": "GitHub", "url": self.DEFAULT_REPO_URL},
            {"label": "Baixar ACCELA", "url": self.DEFAULT_RELEASES_URL},
        ]
        return payload

    def _build_activity_state(self) -> tuple[str, str, str]:
        update_manager = getattr(self.main_window, "update_manager", None)
        task_manager = getattr(self.main_window, "task_manager", None)
        job_queue = getattr(self.main_window, "job_queue", None)
        cloud_manager = getattr(self.main_window, "cloud_save_manager", None)
        game_manager = getattr(self.main_window, "game_manager", None)

        if update_manager is not None and getattr(update_manager, "_install_in_progress", False):
            release = update_manager.latest_release or {}
            target = release.get("display_name", "nova versão")
            return "Atualizando ACCELA", f"Aplicando {target}", "updating"

        if update_manager is not None and update_manager.is_update_available():
            release = update_manager.latest_release or {}
            target = release.get("display_name", "nova versão")
            return "Update disponível", f"Pronto para instalar {target}", "update_available"

        if cloud_manager is not None and getattr(cloud_manager, "_batch_state", {}):
            batch_count = len(getattr(cloud_manager, "_batch_state", {}))
            label = "lote" if batch_count == 1 else "lotes"
            return "Sincronizando saves", f"{batch_count} {label} em execução", "cloud_sync"

        queue_count = len(getattr(job_queue, "job_queue", []) or [])
        if task_manager is not None and task_manager.is_processing:
            current_name = self._current_game_label(task_manager)
            if task_manager.is_download_paused:
                return "Download pausado", current_name, "paused"

            progress_text = self._progress_text()
            speed_text = self._speed_text()
            state = "Instalando arquivos"
            key = "installing"
            if progress_text or speed_text:
                fragments = [item for item in (progress_text, speed_text) if item]
                state = " • ".join(fragments) or state
                key = "downloading"
            elif queue_count:
                state = f"Fila restante: {queue_count}"
            return f"Baixando {current_name}", state, key

        if queue_count:
            return "Organizando a fila", f"{queue_count} item(ns) aguardando", "zip_import"

        games_count = len(getattr(game_manager, "games", []) or [])
        if games_count:
            label = "jogo instalado" if games_count == 1 else "jogos instalados"
            return "Gerenciando biblioteca", f"{games_count} {label}", "library"

        return "Na central de jogos", "Pronto para instalar", "idle"

    @staticmethod
    def _current_game_label(task_manager) -> str:
        current_name = ""
        if getattr(task_manager, "game_data", None):
            current_name = task_manager.game_data.get("game_name", "")
        if not current_name and task_manager.current_job:
            current_name = os.path.splitext(os.path.basename(task_manager.current_job))[0]
        return current_name or "conteúdo"

    def _progress_text(self) -> str:
        progress_bar = getattr(self.main_window, "progress_bar", None)
        if progress_bar is None or not progress_bar.isVisible():
            return ""
        if progress_bar.maximum() <= 0:
            return ""
        value = progress_bar.value()
        if value < 0:
            return ""
        return f"{value}% concluído"

    def _speed_text(self) -> str:
        speed_label = getattr(self.main_window, "speed_label", None)
        if speed_label is None or not speed_label.isVisible():
            return ""
        return (speed_label.text() or "").strip()

    def _disconnect(self, schedule_reconnect: bool) -> None:
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
        if schedule_reconnect and self.settings.value("discord_presence_enabled", True, type=bool):
            self.reconnect_timer.start()
        else:
            self.reconnect_timer.stop()

    def shutdown(self) -> None:
        self._disconnect(schedule_reconnect=False)
