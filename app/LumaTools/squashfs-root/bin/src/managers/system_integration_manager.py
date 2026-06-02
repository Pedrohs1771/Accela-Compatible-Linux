import logging
import os
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)


class SystemIntegrationManager(QObject):
    """Manage Linux desktop integration and Steam lifecycle monitoring."""

    steam_closed = pyqtSignal()

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self._steam_was_running = None
        self._steam_monitor_timer = QTimer(self)
        self._steam_monitor_timer.setInterval(5000)
        self._steam_monitor_timer.timeout.connect(self._poll_steam_state)
        self.reload_settings()

    def reload_settings(self) -> None:
        """Apply current settings for autostart and Steam monitoring."""
        self.apply_autostart_setting()

        auto_close = self.settings.value("auto_close_with_steam", False, type=bool)
        if auto_close and psutil is not None:
            self._steam_monitor_timer.start()
            logger.info("Steam lifecycle monitoring enabled.")
        else:
            self._steam_monitor_timer.stop()
            self._steam_was_running = None
            if auto_close and psutil is None:
                logger.warning(
                    "psutil is unavailable; auto-close with Steam cannot be enabled."
                )

    def apply_autostart_setting(self) -> None:
        """Create or remove the desktop autostart entry."""
        if os.name != "posix":
            return

        enabled = self.settings.value("autostart_on_login", False, type=bool)
        autostart_path = self.get_autostart_path()

        if enabled:
            autostart_path.parent.mkdir(parents=True, exist_ok=True)
            autostart_path.write_text(self._build_autostart_desktop_entry(), encoding="utf-8")
            logger.info("Autostart desktop entry updated at %s", autostart_path)
        elif autostart_path.exists():
            autostart_path.unlink()
            logger.info("Autostart desktop entry removed from %s", autostart_path)

    @staticmethod
    def get_autostart_path() -> Path:
        return Path.home() / ".config" / "autostart" / "lumatools.desktop"

    def _build_autostart_desktop_entry(self) -> str:
        launcher_path = Path.home() / ".local" / "bin" / "lumatools"
        if not launcher_path.exists():
            launcher_path = Path.home() / ".local" / "share" / "LumaTools" / "LumaTools.AppImage"

        start_hidden = self.settings.value(
            "start_minimized_to_tray", True, type=bool
        )
        exec_line = str(launcher_path)
        if start_hidden:
            exec_line += " --start-hidden"

        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Version=1.0\n"
            "Name=LumaTools\n"
            "Comment=Launcher LumaTools para Linux\n"
            f"Exec={exec_line}\n"
            "Icon=lumatools\n"
            "Terminal=false\n"
            "Categories=Game;Utility;\n"
            "StartupNotify=false\n"
            "StartupWMClass=lumatools\n"
            "X-GNOME-Autostart-enabled=true\n"
        )

    def _poll_steam_state(self) -> None:
        """Emit when Steam transitions from running to closed."""
        steam_running = self._is_steam_running()

        if self._steam_was_running is None:
            self._steam_was_running = steam_running
            return

        if self._steam_was_running and not steam_running:
            logger.info("Steam was closed; notifying LumaTools for shutdown handling.")
            self._steam_was_running = False
            self.steam_closed.emit()
            return

        if steam_running:
            self._steam_was_running = True

    @staticmethod
    def _is_steam_running() -> bool:
        if psutil is None:
            return False

        names = {"steam", "steam.exe"}
        for proc in psutil.process_iter(["name", "cmdline"]):
            try:
                name = (proc.info.get("name") or "").lower()
                if name in names:
                    return True

                cmdline = proc.info.get("cmdline") or []
                joined = " ".join(cmdline).lower()
                if "steam.sh" in joined or "/steam" in joined:
                    return True
            except (psutil.Error, OSError, TypeError, ValueError):
                continue
        return False

    def cleanup(self) -> None:
        """Stop background monitoring during shutdown."""
        try:
            self._steam_monitor_timer.stop()
        except RuntimeError:
            pass
