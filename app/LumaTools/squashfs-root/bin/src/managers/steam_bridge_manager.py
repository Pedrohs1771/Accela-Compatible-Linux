from __future__ import annotations

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

from core import steam_helpers
from utils.version import app_version

logger = logging.getLogger(__name__)

DEFAULT_STEAM_BRIDGE_PORT = 32175


def build_bridge_status(main_window: Any, port: int) -> dict[str, Any]:
    task_manager = getattr(main_window, "task_manager", None)
    job_queue = getattr(main_window, "job_queue", None)
    game_manager = getattr(main_window, "game_manager", None)
    settings = getattr(main_window, "settings", None)

    current_game = ""
    current_job = ""
    busy = False
    paused = False
    if task_manager is not None:
        busy = bool(getattr(task_manager, "is_processing", False))
        paused = bool(getattr(task_manager, "is_download_paused", False))
        current_job = os.path.basename(str(getattr(task_manager, "current_job", "") or ""))
        game_data = getattr(task_manager, "game_data", None) or {}
        current_game = str(game_data.get("game_name") or "")

    queue = getattr(job_queue, "job_queue", []) if job_queue is not None else []
    games = getattr(game_manager, "games", []) if game_manager is not None else []

    library_mode = False
    preferred_library = ""
    accent_color = "#C06C84"
    if settings is not None:
        library_mode = bool(settings.value("library_mode", False, type=bool))
        preferred_library = str(
            settings.value("preferred_steam_library_path", "", type=str) or ""
        )
        accent_color = str(settings.value("accent_color", accent_color, type=str))

    try:
        libraries = steam_helpers.get_steam_libraries()
    except Exception as exc:
        logger.debug("Failed to read Steam libraries for bridge status: %s", exc)
        libraries = []

    return {
        "ok": True,
        "app": "LumaTools",
        "version": app_version,
        "pid": os.getpid(),
        "port": port,
        "busy": busy,
        "paused": paused,
        "current_job": current_job,
        "current_game": current_game,
        "queue_count": len(queue or []),
        "games_count": len(games or []),
        "library_mode": library_mode,
        "preferred_library": preferred_library,
        "steam_libraries": libraries,
        "accent_color": accent_color,
    }


class SteamBridgeManager(QObject):
    """Small local HTTP bridge for visual Steam/Millennium integrations.

    The bridge is deliberately scoped to presence/status and bringing the app
    to the foreground. It does not expose license, injector or download control
    endpoints.
    """

    show_requested = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port = DEFAULT_STEAM_BRIDGE_PORT
        self.show_requested.connect(main_window.show_from_tray)

    def start(self) -> None:
        enabled = self.settings.value("steam_bridge_enabled", True, type=bool)
        if not enabled:
            logger.info("Steam visual bridge disabled by settings.")
            return

        try:
            configured_port = int(
                self.settings.value(
                    "steam_bridge_port", DEFAULT_STEAM_BRIDGE_PORT, type=int
                )
            )
        except (TypeError, ValueError):
            configured_port = DEFAULT_STEAM_BRIDGE_PORT
        self.port = max(1024, min(65535, configured_port))

        manager = self

        class Handler(BaseHTTPRequestHandler):
            def do_OPTIONS(self):  # noqa: N802
                self._send_empty(204)

            def do_GET(self):  # noqa: N802
                if self.path in {"/", "/health"}:
                    self._send_json({"ok": True, "app": "LumaTools"})
                elif self.path == "/status":
                    self._send_json(build_bridge_status(manager.main_window, manager.port))
                elif self.path == "/libraries":
                    self._send_json(
                        {"ok": True, "steam_libraries": steam_helpers.get_steam_libraries()}
                    )
                elif self.path == "/show":
                    manager.show_requested.emit()
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "not_found"}, 404)

            def do_POST(self):  # noqa: N802
                if self.path == "/show":
                    manager.show_requested.emit()
                    self._send_json({"ok": True})
                else:
                    self._send_json({"ok": False, "error": "not_found"}, 404)

            def log_message(self, _format, *args):
                return

            def _send_empty(self, status=204):
                self.send_response(status)
                self._send_headers()
                self.end_headers()

            def _send_json(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self._send_headers()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_headers(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Cache-Control", "no-store")

        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        except OSError as exc:
            logger.warning(
                "Could not start Steam visual bridge on 127.0.0.1:%s: %s",
                self.port,
                exc,
            )
            self.server = None
            return

        self.thread = threading.Thread(
            target=self.server.serve_forever,
            name="LumaToolsSteamBridge",
            daemon=True,
        )
        self.thread.start()
        logger.info("Steam visual bridge listening on http://127.0.0.1:%s", self.port)

    def cleanup(self) -> None:
        server = self.server
        if server is None:
            return
        self.server = None
        try:
            server.shutdown()
            server.server_close()
        except OSError as exc:
            logger.debug("Steam visual bridge shutdown error: %s", exc)
        self.thread = None
