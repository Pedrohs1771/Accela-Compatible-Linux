import atexit
import logging
import os
import sys
import threading
from collections import deque
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import (
    QAction,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QSizePolicy,
    QSystemTrayIcon,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
)

from components.custom_widgets import ScaledFontLabel, ScaledLabel
from managers.audio_manager import AudioManager
from managers.cloud_save_manager import CloudSaveManager
from managers.discord_presence_manager import DiscordPresenceManager
from managers.game_manager import GameManager
from managers.gif_manager import GIFManager
from managers.job_queue_manager import JobQueueManager
from managers.system_integration_manager import SystemIntegrationManager
from managers.task_manager import TaskManager
from managers.update_manager import UpdateManager
from managers.ui_state_manager import UIStateManager
from ui.bottom_titlebar import BottomTitleBar
from ui.dialogs.credits import CreditsDialog
from ui.dialogs.fetchmanifest import FetchManifestDialog
from ui.dialogs.gamelibrary import GameLibraryDialog
from ui.dialogs.lain import LainMinigameDialog
from ui.dialogs.settings import SettingsDialog
from ui.dialogs.status import StatusDialog
from ui.dialogs.update_center import UpdateCenterDialog
from utils.logger import qt_log_handler
from utils.paths import Paths
from utils.settings import get_settings
from core.morrenus_api import download_manifest

logger = logging.getLogger(__name__)


class ResizeHandle(QWidget):
    """Transparent widget used to resize the frameless window."""

    def __init__(self, edge_name: str, main_window: "MainWindow"):
        super().__init__(main_window)
        self.edge_name = edge_name
        self.main_window = main_window
        self.resizing = False
        self.resize_start_pos = None
        self.resize_start_geom = None
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return

        window = self.main_window.windowHandle()
        edge = self._get_qt_edge()

        # Try system resize first (Wayland/Windows native)
        if window and window.isExposed() and window.startSystemResize(edge):
            event.accept()
            return

        # Fallback for X11/other
        self.resizing = True
        self.resize_start_pos = event.globalPosition().toPoint()
        self.resize_start_geom = self.main_window.geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.resizing:
            return

        delta = event.globalPosition().toPoint() - self.resize_start_pos
        geom = self.resize_start_geom
        x, y, w, h = geom.x(), geom.y(), geom.width(), geom.height()

        if "right" in self.edge_name:
            w += delta.x()
        if "bottom" in self.edge_name:
            h += delta.y()
        if "left" in self.edge_name:
            x += delta.x()
            w -= delta.x()
        if "top" in self.edge_name:
            y += delta.y()
            h -= delta.y()

        w = max(w, self.main_window.minimumWidth())
        h = max(h, self.main_window.minimumHeight())

        self.main_window.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.resizing:
            self.releaseMouse()
            self.resizing = False
        event.accept()

    def _get_qt_edge(self) -> Qt.Edge:
        edge_map = {
            "left": Qt.Edge.LeftEdge,
            "right": Qt.Edge.RightEdge,
            "top": Qt.Edge.TopEdge,
            "bottom": Qt.Edge.BottomEdge,
            "top_left": Qt.Edge.LeftEdge,
            "top_right": Qt.Edge.RightEdge,
            "bottom_left": Qt.Edge.LeftEdge,
            "bottom_right": Qt.Edge.RightEdge,
        }
        return edge_map.get(self.edge_name, Qt.Edge.RightEdge)


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.resize_handles: Dict[str, ResizeHandle] = {}
        self.key_sequence = deque(maxlen=4)
        self.target_sequence = ["l", "a", "i", "n"]
        self.start_hidden = start_hidden
        self.settings = None
        self.accent_color = None
        self.background_color = None
        self.task_manager = None
        self.gif_manager = None
        self.ui_state = None
        self.job_queue = None
        self.audio_manager = None
        self.game_manager = None
        self.system_integration = None
        self.cloud_save_manager = None
        self.discord_presence_manager = None
        self.update_manager = None
        self.exit_shortcut = None
        self.sequence_timeout = None
        self.central_widget = None
        self.layout = None
        self.titlebar_position = None
        self.bottom_titlebar = None
        self.main_container = None
        self.main_layout = None
        self.drop_zone_container = None
        self.drop_zone_layout = None
        self.drop_zone_gif = None
        self.drop_text_label = None
        self.progress_container = None
        self.progress_layout = None
        self.progress_bar = None
        self.speed_label = None
        self.bottom_widget = None
        self.bottom_layout = None
        self.log_output = None
        self.tray_icon = None
        self.tray_menu = None
        self._force_close = False
        self._tray_notice_shown = False

        self._setup_window_properties()
        self._initialize_managers()
        self._setup_ui()
        self._setup_system_tray()
        self._setup_runtime_integrations()
        self._setup_resize_handles()
        if self.ui_state:
            self.ui_state.apply_style_settings()
        self._setup_key_sequence_detector()
        self._setup_exit_shortcut()

    def _setup_window_properties(self) -> None:
        """Configure basic window properties."""
        self.setObjectName("accela")
        self.setWindowRole("accela")
        self.setWindowTitle("ACCELA")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setGeometry(100, 100, 800, 600)

        icon_path = Paths.resource("logo/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            logger.warning(f"Could not find window icon at: {icon_path}")

        if sys.platform == "win32":
            MainWindow._setup_windows_taskbar()

    def _setup_exit_shortcut(self) -> None:
        """Setup Ctrl+Q shortcut to exit the application."""
        self.exit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.exit_shortcut.activated.connect(self.close)
        logger.info("Ctrl+Q exit shortcut registered")

    def _setup_key_sequence_detector(self) -> None:
        """Setup key sequence detection for Easter egg."""
        self.sequence_timeout = QTimer(self)
        self.sequence_timeout.setSingleShot(True)
        self.sequence_timeout.timeout.connect(self.key_sequence.clear)

    def keyPressEvent(self, event) -> None:
        """Override keyPressEvent to detect key sequences."""
        key_text = event.text().lower()

        if key_text:
            self.key_sequence.append(key_text)
            # Reset sequence after 3 seconds of inactivity
            self.sequence_timeout.start(3000)

            if list(self.key_sequence) == self.target_sequence:
                self._on_lain_sequence_activated()
                self.key_sequence.clear()

        super().keyPressEvent(event)

    def _on_lain_sequence_activated(self) -> None:
        """Handle L->A->I->N sequence activation."""
        logger.info("LAIN sequence detected!")
        self.open_lain_minigame()

    def open_lain_minigame(self) -> None:
        """Open the Serial Experiments Lain minigame."""
        dialog = LainMinigameDialog(self)
        dialog.game_completed.connect(self.on_minigame_completed)
        dialog.exec()

    def on_minigame_completed(self, score: int) -> None:
        """Handle minigame completion."""
        logger.info(f"Lain minigame completed with score: {score}")
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("The Wired")
        msg_box.setText(f"Conexão encerrada\n\nPontuação final: {score}")
        msg_box.exec()

    @staticmethod
    def _setup_windows_taskbar() -> None:
        """Windows-specific taskbar configuration."""
        try:
            import ctypes

            app_id = "god.is.in.the.wired.accela"
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not set AppUserModelID: {e}")

    def _initialize_managers(self) -> None:
        """Initialize all manager classes."""
        self.settings = get_settings()

        self.accent_color = self.settings.value("accent_color", "#C06C84")
        self.background_color = self.settings.value("background_color", "#000000")

        self.task_manager = TaskManager(self)
        self.gif_manager = GIFManager(self)
        self.ui_state = UIStateManager(self)
        self.job_queue = JobQueueManager(self)
        self.audio_manager = AudioManager(self)
        self.game_manager = GameManager(self)
        self.system_integration = SystemIntegrationManager(self)
        self.cloud_save_manager = CloudSaveManager(self)
        self.discord_presence_manager = DiscordPresenceManager(self)
        self.update_manager = UpdateManager(self)

        logger.info("Starting initial game library scan...")
        self.game_manager.scan_steam_libraries_async()

    def _setup_runtime_integrations(self) -> None:
        """Connect runtime integration managers to the main window."""
        if self.system_integration:
            self.system_integration.steam_closed.connect(self._handle_steam_closed)
        if self.update_manager:
            self.update_manager.update_available_changed.connect(
                self._handle_update_available_changed
            )
            self.update_manager.notification_requested.connect(
                self._show_background_notice
            )
            self.update_manager.schedule_startup_check()

    def _setup_system_tray(self) -> None:
        """Create a system tray icon for stealth mode and quick access."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.info("System tray is not available in this session.")
            return

        icon = self.windowIcon()
        if icon.isNull():
            icon_path = Paths.resource("logo/icon.png")
            if icon_path.exists():
                icon = QIcon(str(icon_path))

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("ACCELA")
        self.tray_menu = QMenu(self)

        show_action = QAction("Mostrar ACCELA", self)
        show_action.triggered.connect(self.show_from_tray)
        self.tray_menu.addAction(show_action)

        library_action = QAction("Biblioteca", self)
        library_action.triggered.connect(self._show_library_from_tray)
        self.tray_menu.addAction(library_action)

        settings_action = QAction("Configurações", self)
        settings_action.triggered.connect(self._show_settings_from_tray)
        self.tray_menu.addAction(settings_action)

        self.tray_menu.addSeparator()

        quit_action = QAction("Sair", self)
        quit_action.triggered.connect(lambda: self.request_quit("tray_menu"))
        self.tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide_to_tray()
            else:
                self.show_from_tray()

    def apply_startup_visibility(self) -> None:
        """Apply stealth mode after the window has been initialized."""
        if not self.start_hidden:
            return

        if self.tray_icon is not None:
            self.hide_to_tray(show_message=False)
            logger.info("ACCELA started hidden in the system tray.")
        else:
            self.showMinimized()
            logger.info("ACCELA started minimized because no system tray is available.")

    def hide_to_tray(self, show_message: bool = True) -> None:
        if self.tray_icon is None:
            self.showMinimized()
            return

        self.hide()
        if show_message and not self._tray_notice_shown:
            self._tray_notice_shown = True
            self.tray_icon.showMessage(
                "ACCELA em modo stealth",
                "O launcher continua na bandeja do sistema.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def add_job_safely(self, path: str) -> None:
        if not path:
            return
        logger.info(f"Adding to queue: {os.path.basename(path)}")
        self.job_queue.add_job(path)

    def queue_manifest_download(self, appid: int) -> None:
        if not appid:
            return

        def threaded_manifest_download() -> None:
            try:
                logger.info(
                    f"Downloading manifest for AppID {appid} (Background Thread)"
                )
                zip_file, error = download_manifest(appid)
                if error:
                    logger.error(f"Failed to download manifest: {error}")
                    return

                QTimer.singleShot(0, lambda: self.add_job_safely(zip_file))
            except Exception as exc:
                logger.error(f"Threaded download failed: {exc}", exc_info=True)

        threading.Thread(target=threaded_manifest_download, daemon=True).start()

    def handle_external_command(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return

        zip_files = payload.get("zip_files") or []
        appid = payload.get("appid")
        activate = payload.get("activate", True)

        if activate:
            self.show_from_tray()

        if appid:
            try:
                self.queue_manifest_download(int(appid))
            except (TypeError, ValueError):
                logger.warning(f"Invalid AppID received from external request: {appid}")

        for zip_file in zip_files:
            if zip_file and os.path.exists(zip_file):
                self.add_job_safely(zip_file)

    def _show_library_from_tray(self) -> None:
        self.show_from_tray()
        self.open_game_library()

    def _show_settings_from_tray(self) -> None:
        self.show_from_tray()
        self.open_settings()

    def request_quit(self, reason: str = "user") -> None:
        logger.info("Shutting down ACCELA. Reason: %s", reason)
        self._force_close = True
        self.close()

    def _handle_steam_closed(self) -> None:
        """Handle Steam being closed while ACCELA is running."""
        auto_close = self.settings.value("auto_close_with_steam", False, type=bool)
        if not auto_close:
            return

        auto_sync = self.settings.value(
            "opencloudsave_auto_sync_on_steam_exit", True, type=bool
        )
        if self.cloud_save_manager and auto_sync:
            self.cloud_save_manager.sync_all_configured_games(
                on_complete=lambda: self.request_quit("steam_closed")
            )
            return

        self.request_quit("steam_closed")

    def _setup_ui(self) -> None:
        """Setup the main UI components."""
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.titlebar_position = self.settings.value(
            "titlebar_position", "bottom", type=str
        )

        if self.titlebar_position == "top":
            self.bottom_titlebar = BottomTitleBar(self)
            self.layout.addWidget(self.bottom_titlebar)

        self._create_main_content()
        self._create_bottom_section()
        self.update_gif_display()

        if self.titlebar_position != "top":
            self.bottom_titlebar = BottomTitleBar(self)
            self.layout.addWidget(self.bottom_titlebar)
        self._handle_update_available_changed(
            self.update_manager.is_update_available() if self.update_manager else False
        )

        self.setAcceptDrops(True)

    def _setup_resize_handles(self) -> None:
        """Setup invisible resize handles for all edges and corners."""
        edges = [
            "top_left",
            "top_right",
            "bottom_left",
            "bottom_right",
            "left",
            "right",
            "top",
            "bottom",
        ]

        for name in edges:
            handle = ResizeHandle(name, self)
            handle.setCursor(MainWindow._get_cursor_for_edge(name))
            self.resize_handles[name] = handle

        self._update_resize_handles_geometry()

    @staticmethod
    def _get_cursor_for_edge(edge: str) -> Qt.CursorShape:
        """Get appropriate cursor for each resize edge."""
        cursors = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
        }
        return cursors.get(edge, Qt.CursorShape.ArrowCursor)

    def _update_resize_handles_geometry(self) -> None:
        """Calculate and set geometry for all resize handles."""
        if not self.resize_handles:
            return

        w, h = self.width(), self.height()
        hw = 6  # Handle width

        # Define geometry calculations for each handle type
        geometries = {
            "top_left": (0, 0, hw, hw),
            "top_right": (w - hw, 0, hw, hw),
            "bottom_left": (0, h - hw, hw, hw),
            "bottom_right": (w - hw, h - hw, hw, hw),
            "left": (0, hw, hw, h - 2 * hw),
            "right": (w - hw, hw, hw, h - 2 * hw),
            "top": (hw, 0, w - 2 * hw, hw),
            "bottom": (hw, h - hw, w - 2 * hw, hw),
        }

        for name, (x, y, width, height) in geometries.items():
            if name in self.resize_handles:
                self.resize_handles[name].setGeometry(x, y, width, height)

    def resizeEvent(self, event) -> None:
        """Update resize handle positions when window is resized."""
        super().resizeEvent(event)
        self._update_resize_handles_geometry()

    def _create_main_content(self) -> None:
        """Create the main content area with drop zone."""
        self.main_container = QWidget()
        self.main_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.layout.addWidget(self.main_container, 3)

        self.main_layout = QVBoxLayout(self.main_container)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self._create_drop_zone()
        self._create_progress_section()

    def _create_drop_zone(self) -> None:
        """Create the drag and drop area."""
        self.drop_zone_container = QWidget()
        self.drop_zone_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.drop_zone_layout = QVBoxLayout(self.drop_zone_container)
        self.drop_zone_layout.setContentsMargins(0, 0, 0, 0)
        self.drop_zone_layout.setSpacing(0)

        self.drop_zone_gif = ScaledLabel()
        self.drop_zone_gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone_gif.setMinimumHeight(150)
        self.drop_zone_gif.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self.drop_text_label = ScaledFontLabel("Arraste e solte o ZIP aqui")
        self.drop_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.drop_text_label.setMinimumHeight(32)
        self.drop_text_label.setMaximumHeight(48)

        self.drop_zone_layout.addWidget(self.drop_zone_gif, 9)
        self.drop_zone_layout.addWidget(self.drop_text_label, 1)
        self.main_layout.addWidget(self.drop_zone_container, 10)

    def _create_progress_section(self) -> None:
        """Create the progress bar and speed label."""
        self.progress_container = QWidget()
        self.progress_layout = QVBoxLayout(self.progress_container)
        self.progress_layout.setContentsMargins(20, 5, 20, 5)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self._update_progress_bar_style()
        self.progress_layout.addWidget(self.progress_bar)

        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.speed_label.setVisible(False)
        self.progress_layout.addWidget(self.speed_label)

        self.main_layout.addWidget(self.progress_container, 1)

    def _create_bottom_section(self) -> None:
        """Create the bottom section with queue and logs."""
        self.bottom_widget = QWidget()
        self.bottom_layout = QHBoxLayout(self.bottom_widget)
        self.bottom_layout.setContentsMargins(5, 5, 5, 5)

        self.ui_state.setup_queue_panel()
        self.bottom_layout.addWidget(self.ui_state.queue_widget, 1)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        qt_log_handler.new_record.connect(self.log_output.append)
        self.bottom_layout.addWidget(self.log_output, 1)

        self.layout.addWidget(self.bottom_widget, 1)
        self.ui_state.queue_widget.setVisible(False)

    def update_gif_display(self, enabled: Optional[bool] = None) -> None:
        """Update GIF display visibility and adjust window layout."""
        if enabled is None:
            enabled = self.settings.value("gif_display_enabled", True, type=bool)

        if enabled:
            if self.height() < 400:
                self.resize(self.width(), max(400, self.height()))
            self.main_layout.setStretchFactor(self.drop_zone_gif, 9)
            self.drop_zone_gif.setVisible(True)
            self.layout.setStretchFactor(self.main_container, 3)
            self.layout.setStretchFactor(self.bottom_widget, 1)
        else:
            current_height = self.height()
            gif_height = self.drop_zone_gif.height()
            new_height = max(200, current_height - gif_height)
            self.resize(self.width(), new_height)
            self.main_layout.setStretchFactor(self.drop_zone_gif, 0)
            self.drop_zone_gif.setVisible(False)
            self.layout.setStretchFactor(self.main_container, 1)
            self.layout.setStretchFactor(self.bottom_widget, 3)

        self.update()
        logger.info(f"GIF display updated: {'enabled' if enabled else 'disabled'}")

    def update_progress_bar_style(self) -> None:
        self._update_progress_bar_style()

    def _update_progress_bar_style(self) -> None:
        """Update progress bar styling."""
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                max-height: 10px;
                border: 1px solid {self.accent_color};
                border-radius: 5px;
                text-align: center;
                color: #FFFFFF;
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 5px;
            }}
        """
        )

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec()

    def open_update_center(self) -> None:
        dialog = UpdateCenterDialog(self)
        dialog.exec()

    def _handle_update_available_changed(self, available: bool) -> None:
        if self.bottom_titlebar is not None:
            self.bottom_titlebar.set_update_badge_visible(available)
        if self.tray_icon is not None:
            self.tray_icon.setToolTip(
                "ACCELA • update disponível" if available else "ACCELA"
            )

    def _show_background_notice(self, title: str, message: str) -> None:
        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )
            return
        if self.isVisible():
            popup = QMessageBox(self)
            popup.setWindowTitle(title)
            popup.setText(message)
            popup.setStandardButtons(QMessageBox.StandardButton.Ok)
            popup.setModal(False)
            popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            popup.show()
            return
        logger.info("%s: %s", title, message)

    def open_fetch_dialog(self) -> None:
        self.ui_state.fetch_dialog = FetchManifestDialog(self)
        self.ui_state.fetch_dialog.exec()
        self.ui_state.fetch_dialog = None

    def open_game_library(self) -> None:
        dialog = GameLibraryDialog(self)
        dialog.exec()

    def open_status_dialog(self) -> None:
        dialog = StatusDialog(self)
        dialog.exec()

    def open_credits_dialog(self) -> None:
        dialog = CreditsDialog(self)
        dialog.exec()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if not event.mimeData().hasUrls():
            return

        urls = event.mimeData().urls()
        has_zip = any(
            url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
            for url in urls
        )

        if has_zip:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        new_jobs = [
            url.toLocalFile()
            for url in urls
            if url.isLocalFile() and url.toLocalFile().lower().endswith(".zip")
        ]

        if not new_jobs:
            return

        logger.info(f"Added {len(new_jobs)} file(s) to the queue via drag-drop.")
        for job_path in new_jobs:
            self.job_queue.add_job(job_path)

    def closeEvent(self, event) -> None:
        """Handle application shutdown."""
        close_to_tray = self.settings.value("close_to_tray", True, type=bool)
        if not self._force_close and self.tray_icon is not None and close_to_tray:
            event.ignore()
            self.hide_to_tray()
            return

        try:
            if self.discord_presence_manager:
                self.discord_presence_manager.shutdown()
            if self.tray_icon:
                self.tray_icon.hide()
            MainWindow._cleanup_logging()
            self.task_manager.cleanup()
            self.job_queue.clear()
            self.game_manager.cleanup()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        super().closeEvent(event)

    def reposition_titlebar(self, position: str) -> None:
        """Dynamically reposition the titlebar without restart."""
        if not hasattr(self, "bottom_titlebar") or not self.bottom_titlebar:
            return

        self.layout.removeWidget(self.bottom_titlebar)
        self.bottom_titlebar.setParent(None)

        if position == "top":
            self.layout.insertWidget(0, self.bottom_titlebar)
        else:
            self.layout.addWidget(self.bottom_titlebar)

        self.titlebar_position = position
        logger.info(f"Titlebar repositioned to: {position}")

    @staticmethod
    def _cleanup_logging() -> None:
        """Clean up logging system."""
        try:
            atexit.unregister(logging.shutdown)
            logging.getLogger().removeHandler(qt_log_handler)
            qt_log_handler.close()
            logger.info("QtLogHandler removed and atexit hook unregistered.")
            logging.shutdown()
        except Exception as e:
            print(f"Error during custom logger shutdown: {e}")
