import logging
import os
import sys
import threading
from collections import deque
from typing import Dict, Optional, cast

from PyQt6.QtCore import Qt, QTimer, QSize, QMetaObject, pyqtSlot
from PyQt6.QtGui import (
    QAction,
    QColor,
    QIcon,
    QKeySequence,
    QMouseEvent,
    QShortcut,
    QMovie,
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
    QFrame,
    QApplication,
)

from components.custom_widgets import ScaledFontLabel, ScaledLabel
from managers.audio_manager import AudioManager
from managers.cloud_save_manager import CloudSaveManager
from managers.discord_presence_manager import DiscordPresenceManager
from managers.game_manager import GameManager
from managers.gif_manager import GIFManager
from managers.job_queue_manager import JobQueueManager
from managers.steam_bridge_manager import SteamBridgeManager
from managers.system_integration_manager import SystemIntegrationManager
from managers.task_manager import TaskManager
from managers.update_manager import UpdateManager
from managers.ui_state_manager import UIStateManager
from ui.bottom_titlebar import BottomTitleBar
from ui.dialogs.content_manager import ContentManagerDialog
from ui.dialogs.credits import CreditsDialog
from ui.dialogs.fetchmanifest import FetchManifestDialog
from ui.dialogs.gamelibrary import GameLibraryDialog
from ui.dialogs.lain import LainMinigameDialog
from ui.dialogs.ryuu_fixes import RyuuFixesDialog
from ui.dialogs.settings import SettingsDialog
from ui.dialogs.status import StatusDialog
from ui.dialogs.update_center import UpdateCenterDialog
from utils.logger import qt_log_handler
from utils.paths import Paths
from utils.settings import get_settings
from utils.task_runner import TaskRunner
from core.manifest_downloader import ManifestDownloader
from core.workshop_manager import WorkshopManager

logger = logging.getLogger(__name__)

class ResizeHandle(QWidget):
    def __init__(self, edge_name: str, main_window: "MainWindow"):
        super().__init__(main_window)
        self.edge_name = edge_name
        self.main_window = main_window
        self.resizing = False
        self.setStyleSheet("background: transparent;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton: return
        window = self.main_window.windowHandle()
        if window and window.isExposed() and window.startSystemResize(self._get_qt_edge()):
            event.accept()
            return
        self.resizing = True
        self.resize_start_pos = event.globalPosition().toPoint()
        self.resize_start_geom = self.main_window.geometry()
        self.grabMouse()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.resizing: return
        delta = event.globalPosition().toPoint() - self.resize_start_pos
        geom = self.resize_start_geom
        x, y, w, h = geom.x(), geom.y(), geom.width(), geom.height()
        if "right" in self.edge_name: w += delta.x()
        if "bottom" in self.edge_name: h += delta.y()
        w = max(w, self.main_window.minimumWidth())
        h = max(h, self.main_window.minimumHeight())
        self.main_window.setGeometry(x, y, w, h)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self.resizing:
            self.releaseMouse()
            self.resizing = False
        event.accept()

    def _get_qt_edge(self) -> Qt.Edge:
        edge_map = {"right": Qt.Edge.RightEdge, "bottom": Qt.Edge.BottomEdge}
        return edge_map.get(self.edge_name, Qt.Edge.RightEdge)

class MainWindow(QMainWindow):
    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.resize_handles: Dict[str, ResizeHandle] = {}
        self.key_sequence = deque(maxlen=4)
        self.target_sequence = ["l", "a", "i", "n"]
        self.start_hidden = start_hidden
        self.settings = get_settings()
        self.accent_color = self.settings.value("accent_color", "#C06C84")
        self.background_color = self.settings.value("background_color", "#000000")
        self._force_close = False
        self._shutdown_started = False
        self._components_shutdown = False
        self.tray_icon = None
        
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
        self.setObjectName("lumatools")
        self.setWindowTitle("LumaTools")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setMinimumSize(820, 640)
        self.resize(920, 700)
        self.setAcceptDrops(True)
        icon_path = Paths.resource("logo/icon.png")
        if icon_path.exists(): self.setWindowIcon(QIcon(str(icon_path)))

    def _initialize_managers(self) -> None:
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
        self.steam_bridge_manager = SteamBridgeManager(self)
        self.manifest_downloader = ManifestDownloader()
        self.workshop_manager = WorkshopManager()
        self.game_manager.scan_steam_libraries_async()

    def _setup_ui(self) -> None:
        self.central_widget = QWidget()
        self.central_widget.setObjectName("central_widget")
        self.central_widget.setAutoFillBackground(True)
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_frame = QFrame()
        self.content_frame.setObjectName("content_frame")
        self.content_frame.setAutoFillBackground(True)
        self.content_frame.setFrameShape(QFrame.Shape.NoFrame)
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(28, 22, 28, 16)
        self.content_layout.setSpacing(10)
        
        self.drop_zone_container = QWidget()
        self.drop_zone_container.setObjectName("drop_zone_container")
        self.drop_zone_container.setAutoFillBackground(True)
        self.drop_zone_container.setMinimumHeight(382)
        self.drop_zone_container.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.drop_zone_layout = QVBoxLayout(self.drop_zone_container)
        self.drop_zone_layout.setContentsMargins(18, 12, 18, 12)
        self.drop_zone_layout.setSpacing(8)
        self.drop_zone_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        from components.custom_widgets import ScaledLabel
        self.drop_zone_gif = ScaledLabel()
        self.drop_zone_gif.setObjectName("drop_zone_gif")
        self.drop_zone_gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_zone_gif.setMinimumSize(400, 300)
        self.drop_zone_gif.setMaximumSize(500, 375)
        self.drop_zone_gif.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.drop_zone_layout.addWidget(
            self.drop_zone_gif,
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        
        self.drop_text_label = QLabel("Arraste e solte o ZIP aqui")
        self.drop_text_label.setObjectName("drop_text_label")
        self.drop_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_text_label.setMinimumHeight(32)
        self.drop_text_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.drop_zone_layout.addWidget(self.drop_text_label)
        self.content_layout.addWidget(self.drop_zone_container, 1)

        self.progress_container = QWidget()
        self.progress_container.setObjectName("progress_container")
        self.progress_container.setAutoFillBackground(True)
        self.progress_layout = QVBoxLayout(self.progress_container)
        self.progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_layout.setSpacing(4)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_layout.addWidget(self.progress_bar)
        
        self.speed_label = QLabel("")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_layout.addWidget(self.speed_label)
        self.content_layout.addWidget(self.progress_container)

        if self.ui_state:
            self.ui_state.setup_queue_panel()
            if self.ui_state.queue_widget is not None:
                self.ui_state.queue_widget.setVisible(False)
                self.content_layout.addWidget(self.ui_state.queue_widget)

        self.activity_header = QWidget()
        self.activity_header.setObjectName("activity_header")
        self.activity_header_layout = QHBoxLayout(self.activity_header)
        self.activity_header_layout.setContentsMargins(2, 0, 2, 0)
        self.activity_header_layout.setSpacing(8)
        self.activity_label = QLabel("ATIVIDADE")
        self.activity_label.setObjectName("activity_label")
        self.activity_status_label = QLabel("PRONTO")
        self.activity_status_label.setObjectName("activity_status_label")
        self.activity_status_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.activity_header_layout.addWidget(self.activity_label)
        self.activity_header_layout.addStretch(1)
        self.activity_header_layout.addWidget(self.activity_status_label)
        self.content_layout.addWidget(self.activity_header)

        self.log_output = QTextEdit()
        self.log_output.setObjectName("log_output")
        self.log_output.setReadOnly(True)
        self.log_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.log_output.document().setMaximumBlockCount(800)
        self.log_output.setMinimumHeight(128)
        self.log_output.setMaximumHeight(210)
        self.log_output.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.log_output.setStyleSheet(
            "background-color: #000000; color: #C06C84; border: none;"
        )
        self.content_layout.addWidget(self.log_output, 0)
        
        self.main_layout.addWidget(self.content_frame)
        self.bottom_titlebar = BottomTitleBar(self)
        self.main_layout.addWidget(self.bottom_titlebar)
        
        qt_log_handler.message_logged.connect(self.log_output.append)

    def update_progress_bar_style(self):
        accent = QColor(self.accent_color)
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 120)"
        self.progress_bar.setStyleSheet(
            f"""
            QProgressBar {{
                min-height: 8px;
                max-height: 8px;
                background-color: rgba(255, 255, 255, 10);
                border: 1px solid {border};
                border-radius: 3px;
                color: transparent;
                text-align: center;
            }}
            QProgressBar::chunk {{
                background-color: {self.accent_color};
                border-radius: 2px;
            }}
            """
        )

    def _setup_system_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon(self.windowIcon(), self)
        self.tray_icon.setToolTip("LumaTools")
        self.tray_menu = QMenu()
        self.tray_menu.addAction("Mostrar LumaTools", self.show_from_tray)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Biblioteca", self.open_game_library_from_tray)
        self.tray_menu.addAction("Baixar jogo / manifesto", self.open_fetch_dialog_from_tray)
        self.tray_menu.addAction("Status", self.open_status_dialog_from_tray)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Configurações", self.open_settings_from_tray)
        self.tray_menu.addAction("Central de updates", self.open_update_center_from_tray)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Sair", lambda: self.request_quit("tray"))
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self._handle_tray_activation)
        self.tray_icon.show()

    def _setup_runtime_integrations(self) -> None:
        if self.system_integration: self.system_integration.steam_closed.connect(self._handle_steam_closed)
        if self.update_manager: self.update_manager.update_available_changed.connect(self._handle_update_available_changed)
        if self.steam_bridge_manager: self.steam_bridge_manager.start()

    def _setup_resize_handles(self) -> None:
        for edge in ["right", "bottom"]:
            handle = ResizeHandle(edge, self)
            self.resize_handles[edge] = handle

    def _setup_key_sequence_detector(self) -> None:
        self.sequence_timeout = QTimer(self)
        self.sequence_timeout.setSingleShot(True)
        self.sequence_timeout.timeout.connect(self.key_sequence.clear)

    def _setup_exit_shortcut(self) -> None:
        self.exit_shortcut = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.exit_shortcut.activated.connect(self.close)

    def open_settings(self, focus_section: str = ""):
        if not isinstance(focus_section, str):
            focus_section = ""
        SettingsDialog(self, focus_section=focus_section).exec()

    def open_game_library(self): GameLibraryDialog(self).exec()
    def open_fetch_dialog(self): FetchManifestDialog(self).exec()
    def open_ryuu_fixes(self): RyuuFixesDialog(self).exec()
    def open_content_manager(self): ContentManagerDialog(self).exec()
    def open_status_dialog(self): StatusDialog(self).exec()
    def open_update_center(self): UpdateCenterDialog(self).exec()
    def open_credits_dialog(self): CreditsDialog(self).exec()
    def open_lain_minigame(self): LainMinigameDialog(self).exec()

    def _open_from_tray(self, opener) -> None:
        self.show_from_tray()
        QTimer.singleShot(0, opener)

    def open_settings_from_tray(self) -> None:
        self._open_from_tray(self.open_settings)

    def open_game_library_from_tray(self) -> None:
        self._open_from_tray(self.open_game_library)

    def open_fetch_dialog_from_tray(self) -> None:
        self._open_from_tray(self.open_fetch_dialog)

    def open_status_dialog_from_tray(self) -> None:
        self._open_from_tray(self.open_status_dialog)

    def open_update_center_from_tray(self) -> None:
        self._open_from_tray(self.open_update_center)

    def dragEnterEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(".zip"):
                event.acceptProposedAction()
                return
        event.ignore()

    def dropEvent(self, event):
        added = 0
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".zip") and os.path.exists(path):
                self.add_job_safely(path)
                added += 1

        if added:
            logger.info("Adicionado(s) %s ZIP(s) por arrastar e soltar.", added)
            event.acceptProposedAction()
            return

        QMessageBox.warning(
            self,
            "Arquivo inválido",
            "Arraste um arquivo .zip contendo .lua e .manifest.",
        )
        event.ignore()
    
    def reposition_titlebar(self, position): pass
    def update_gif_display(self, enabled): pass

    def show_from_tray(self):
        self.showNormal()
        self.activateWindow()

    def _handle_tray_activation(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_from_tray()

    def hide_to_tray(self, show_message=True):
        if self.tray_icon is None or not self.tray_icon.isVisible():
            self.showMinimized()
            return
        self.hide()

    def request_quit(self, source="unknown"):
        logger.info("Encerrando LumaTools. Origem: %s", source)
        self._shutdown_components()
        self._force_close = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(250, app.quit)

    def _shutdown_components(self):
        if self._components_shutdown:
            return
        self._components_shutdown = True
        self._shutdown_started = True

        for attr_name in (
            "gif_manager",
            "update_manager",
            "cloud_save_manager",
            "system_integration",
            "steam_bridge_manager",
            "discord_presence_manager",
            "audio_manager",
            "task_manager",
            "game_manager",
            "manifest_downloader",
        ):
            component = getattr(self, attr_name, None)
            if component is None:
                continue
            cleanup = getattr(component, "cleanup", None)
            stop = getattr(component, "stop", None)
            shutdown = getattr(component, "shutdown", None)
            try:
                if callable(cleanup):
                    cleanup()
                elif callable(shutdown):
                    shutdown()
                elif callable(stop):
                    stop()
            except Exception as exc:
                logger.debug("Erro ao encerrar %s: %s", attr_name, exc)

        try:
            TaskRunner.stop_all_active()
        except Exception as exc:
            logger.debug("Erro ao encerrar TaskRunners ativos: %s", exc)

        if self.tray_icon is not None:
            try:
                self.tray_icon.hide()
            except RuntimeError:
                pass

        try:
            self.settings.sync()
        except Exception as exc:
            logger.debug("Erro ao sincronizar settings no fechamento: %s", exc)

    def handle_external_command(self, payload):
        if payload.get("appid"): self.queue_manifest_download(payload["appid"])
        if payload.get("zip_files"):
            for z in payload["zip_files"]: self.add_job_safely(z)

    def queue_manifest_download(self, appid: int):
        threading.Thread(target=self._threaded_download, args=(appid,), daemon=True).start()

    def _threaded_download(self, appid):
        try:
            api_key = self.settings.value("morrenus_api_key", "")
            zip_file = self.manifest_downloader.fetch_manifest(str(appid), api_key)
            if zip_file: QTimer.singleShot(0, lambda: self.add_job_safely(zip_file))
        except Exception as e: logger.error(f"Download failed: {e}")

    @pyqtSlot(str)
    def add_job_safely(self, path):
        self.job_queue.add_job(path)

    @pyqtSlot()
    def reload_gifs_after_processing(self):
        if self.ui_state:
            self.ui_state.reload_movies()
        if self.bottom_titlebar:
            self.bottom_titlebar.reload_navi_animation(force=True)

    def _handle_steam_closed(self):
        if self.settings.value("close_with_steam", False, type=bool): self.request_quit("steam_closed")

    def _handle_update_available_changed(self, available):
        if available: logger.info("Nova atualização disponível!")

    def apply_startup_visibility(self):
        if self.start_hidden: self.hide_to_tray()

    def closeEvent(self, event):
        close_to_tray = self.settings.value("close_to_tray", True, type=bool)
        tray_available = self.tray_icon is not None and self.tray_icon.isVisible()

        if not self._force_close and close_to_tray and tray_available:
            self.hide_to_tray()
            event.ignore()
            return

        self._shutdown_components()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(250, app.quit)
