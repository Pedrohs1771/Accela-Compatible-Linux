import logging
import math
import os
import platform
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal, QMetaObject, pyqtSlot, Q_ARG
from PyQt6.QtGui import QIntValidator, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# --- Import Handling with Fallbacks ---
try:
    from core import morrenus_api
except ImportError:
    morrenus_api = None

try:
    from core.steam_helpers import slssteam_api_send
except ImportError:

    def slssteam_api_send(_cmd):
        return None


try:
    from utils.helpers import get_base_path
except ImportError:

    def get_base_path():
        return Path(".")


try:
    from managers.image_fetcher import ImageFetcher
except ImportError:
    try:
        from utils.image_fetcher import ImageFetcher
    except ImportError:
        ImageFetcher = None

try:
    from managers.db_manager import DatabaseManager
except ImportError:
    DatabaseManager = None

try:
    from utils.yaml_config_manager import (
        add_fake_app_id,
        get_fake_app_ids,
        get_fake_appid,
        get_user_config_path,
        is_slssteam_config_management_enabled,
        is_slssteam_mode_enabled,
        remove_fake_app_id,
    )
except ImportError:
    # Dummy fallbacks to prevent crash if module is missing
    def add_fake_app_id(*_args, **_kwargs):
        return False

    def get_fake_app_ids(*_args, **_kwargs):
        return []

    def get_fake_appid(*_args, **_kwargs):
        return None

    def get_user_config_path():
        return Path("config.yaml")

    def is_slssteam_config_management_enabled():
        return False

    def is_slssteam_mode_enabled():
        return False

    def remove_fake_app_id(*_args, **_kwargs):
        return False


logger = logging.getLogger(__name__)


def format_game_display_name(game_data: dict) -> str:
    """Return the display name for a game, including the LumaTools marker."""
    name = game_data.get("game_name", "Desconhecido")
    if game_data.get("is_lumatools_install"):
        return f"{name} [LumaTools]"
    return name


class GameItemWidget(QWidget):
    """
    Custom widget for displaying a game item in the library list.
    Layout: [ Image ] [ Name/Size/Status ]
    """

    def __init__(
        self, game_data: dict, size_str: str, accent_color: str, background_color: str
    ):
        super().__init__()
        self.game_data = game_data
        self.accent_color = accent_color
        self.background_color = background_color
        self._init_ui(size_str)

    def _init_ui(self, size_str: str) -> None:
        """Initialize the UI components."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # --- Image Section ---
        self.image_label = QLabel()
        self.image_label.setFixedSize(230, 108)  # Standard Steam Header Ratio
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        name = self.game_data.get("game_name", "Desconhecido")
        display_name = format_game_display_name(self.game_data)
        self.image_label.setText(name[:2].upper())

        self.image_label.setStyleSheet(
            f"background-color: {self.background_color}; "
            f"color: {self.accent_color}; "
            f"border-radius: 4px; "
        )
        layout.addWidget(self.image_label)

        # --- Info Section (Vertical) ---
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 5, 0, 5)
        info_layout.setSpacing(2)

        # Game name
        name_label = QLabel(display_name)
        name_label.setStyleSheet(
            f"font-weight: bold; font-size: 14px; color: {self.accent_color};"
        )
        name_label.setWordWrap(True)
        info_layout.addWidget(name_label)

        # Size
        size_label = QLabel(f"Tamanho: {size_str}")
        size_label.setStyleSheet(f"color: {self.accent_color};")
        info_layout.addWidget(size_label)

        # Update status
        self._add_status_label(info_layout)

        info_layout.addStretch()
        layout.addLayout(info_layout)

    def _add_status_label(self, layout: QVBoxLayout) -> None:
        """Add the update status label based on game data."""
        update_status = self.game_data.get("update_status", "cannot_determine")
        status_label = QLabel()

        status_map = {
            "update_available": ("Nova versão disponível", self.accent_color),
            "up_to_date": ("Atualizado", "#00FF00"),
            "checking": ("Verificando atualizações...", "#FFA500"),
        }

        text, color = status_map.get(
            update_status, ("Não foi possível verificar atualizações", "#AAAAAA")
        )

        status_label.setText(text)
        status_label.setStyleSheet(f"color: {color}; font-style: italic;")
        layout.addWidget(status_label)

    def set_image(self, pixmap: QPixmap) -> None:
        """Sets the image on the label, scaling it nicely."""
        if not pixmap or pixmap.isNull():
            return

        scaled = pixmap.scaled(
            self.image_label.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def sizeHint(self) -> QSize:
        """Return size hint that matches the desired row height."""
        return QSize(400, 118)


class GameLibraryDialog(QDialog):
    """Dialog to display and manage the game library."""

    goldberg_check_complete = pyqtSignal(bool)  # is_applied
    manifest_download_complete = pyqtSignal(str, str, dict)  # fpath, error, game_data
    uninstall_complete = pyqtSignal(bool, str)  # success, error_message

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.game_manager = getattr(main_window, "game_manager", None)
        self.settings = getattr(main_window, "settings", None)
        self.executor = ThreadPoolExecutor(max_workers=4)

        # Load theme colors
        self.accent_color = "#C06C84"
        self.background_color = "#000000"

        if self.settings:
            self.accent_color = self.settings.value("accent_color", "#C06C84")
            self.background_color = self.settings.value("background_color", "#000000")

        # State tracking
        self._active_fetchers = {}
        self._image_cache = {}
        self._dialog_open = False
        self._refreshing = False
        self._closing = False
        self._scanning = False
        self._checking_updates = False
        self._download_progress_dialog = None
        self._uninstall_progress_dialog = None
        self._details_dialog = None

        self._setup_window()
        self._setup_ui()
        self._connect_signals()

        # Initial Load
        self._refresh_game_list()

    def _setup_window(self) -> None:
        """Configure main window properties and styles."""
        self.setWindowTitle("Biblioteca")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.resize(750, 500)

        self.setStyleSheet(
            f"""
            QDialog {{ background-color: {self.background_color}; color: {self.accent_color}; }}
            
            QListWidget {{ 
                background-color: {self.background_color}; 
                border: none; 
                border-radius: 4px; 
            }}
            QListWidget::item {{ 
                border-bottom: 1px solid #333; 
                color: {self.accent_color};
            }}
            QListWidget::item:selected {{ 
                background-color: #1A1A1A; 
            }}
            
            QLabel {{ color: {self.accent_color}; }}
            
            QComboBox {{ 
                background-color: {self.background_color}; 
                color: {self.accent_color}; 
                padding: 4px; 
                border: none; 
            }}
            QComboBox::drop-down {{ border: none; }}
            QComboBox QAbstractItemView {{
                background-color: {self.background_color};
                color: {self.accent_color};
                selection-background-color: #222;
                border: none;
            }}
        """
        )

    def _setup_ui(self) -> None:
        """Create and arrange UI elements."""
        layout = QVBoxLayout(self)

        # --- Top Bar ---
        top_layout = QHBoxLayout()

        self.scan_button = QPushButton("Escanear bibliotecas")
        self.scan_button.clicked.connect(self._scan_for_games)
        top_layout.addWidget(self.scan_button)

        top_layout.addStretch()

        source_label = QLabel("Fonte:")
        top_layout.addWidget(source_label)

        self.source_combo = QComboBox()
        self.source_combo.addItem("Todos", "all")
        self.source_combo.addItem("LumaTools", "lumatools")
        self.source_combo.addItem("Steam", "steam")
        if self.game_manager:
            current_filter = getattr(self.game_manager, "source_filter", "all")
            index = self.source_combo.findData(current_filter)
            if index >= 0:
                self.source_combo.setCurrentIndex(index)
        self.source_combo.currentIndexChanged.connect(self._on_source_filter_changed)
        top_layout.addWidget(self.source_combo)

        sort_label = QLabel("Ordenar por:")
        top_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Instalados recentemente", "recently_installed")
        self.sort_combo.addItem("Nome (A-Z)", "name_asc")
        self.sort_combo.addItem("Nome (Z-A)", "name_desc")
        self.sort_combo.addItem("Tamanho (menor)", "size_asc")
        self.sort_combo.addItem("Tamanho (maior)", "size_desc")
        self.sort_combo.addItem("AppID", "appid")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        top_layout.addWidget(self.sort_combo)

        layout.addLayout(top_layout)

        # --- Games List ---
        self.games_list = QListWidget()
        self.games_list.setSpacing(2)
        self.games_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        layout.addWidget(self.games_list)

        # --- Footer ---
        self.info_label = QLabel("0 jogos da Steam instalados encontrados")
        layout.addWidget(self.info_label)

    def _connect_signals(self) -> None:
        """Connect GameManager and local signals."""
        if not self.game_manager:
            return

        self.game_manager.scan_complete.connect(
            self._on_scan_complete, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.library_updated.connect(
            self._refresh_game_list, Qt.ConnectionType.UniqueConnection
        )
        self.game_manager.game_update_status_changed.connect(
            self._on_game_update_status_changed, Qt.ConnectionType.UniqueConnection
        )

        self.games_list.itemClicked.connect(self._on_item_selected)
        self.goldberg_check_complete.connect(self._on_goldberg_check_complete)
        self.manifest_download_complete.connect(self._on_manifest_download_complete)
        self.uninstall_complete.connect(self._on_uninstall_complete)

    # --- Scanning & Updates ---

    def _scan_for_games(self) -> None:
        if self._scanning or not self.game_manager:
            return

        self._scanning = True
        self.scan_button.setEnabled(False)
        self.scan_button.setText("Escaneando...")
        self.info_label.setText("Escaneando bibliotecas da Steam...")
        self._refreshing = True
        self.games_list.clear()

        self.game_manager.scan_steam_libraries_async()

    def _on_scan_complete(self, count: int) -> None:
        self.scan_button.setEnabled(True)
        self.scan_button.setText("Escanear bibliotecas")

        if count > 0:
            self._checking_updates = True
            QTimer.singleShot(100, self._check_if_updates_complete)
            return

        self.info_label.setText(f"Escaneamento concluído: {count} jogo(s) da Steam instalado(s) encontrado(s).")
        self._scanning = False
        # Force refresh to clear "Scanning..." state if 0 found
        self._refresh_game_list()

    def _check_if_updates_complete(self) -> None:
        if not self._checking_updates:
            return

        # Check if any items are still in "checking" state
        checking = False
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            game_data = item.data(Qt.ItemDataRole.UserRole)
            if game_data and game_data.get("update_status") == "checking":
                checking = True
                break

        if checking:
            QTimer.singleShot(500, self._check_if_updates_complete)
            return

        self._checking_updates = False
        self._scanning = False
        self._refresh_game_list()

    def _on_game_update_status_changed(self, appid: str, update_status: str) -> None:
        if self._closing or not self.isVisible():
            return

        # Find matching item
        item = None
        for i in range(self.games_list.count()):
            it = self.games_list.item(i)
            game_data = it.data(Qt.ItemDataRole.UserRole)
            if game_data and game_data.get("appid") == appid:
                item = it
                break

        if not item:
            return

        self._update_item_status(item, appid, update_status)

    def _update_item_status(
        self, item: QListWidgetItem, appid: str, update_status: str
    ) -> None:
        """Update specific item status logic extracted to flatten logic."""
        game_data = item.data(Qt.ItemDataRole.UserRole)
        game_data["update_status"] = update_status
        item.setData(Qt.ItemDataRole.UserRole, game_data)

        # Update widget
        widget = self.games_list.itemWidget(item)
        if not isinstance(widget, GameItemWidget):
            return

        size_str = GameLibraryDialog._format_size(game_data.get("size_on_disk", 0))
        new_widget = GameItemWidget(
            game_data, size_str, self.accent_color, self.background_color
        )

        # Preserve image if it was loaded
        if appid in self._image_cache:
            pixmap = QPixmap()
            pixmap.loadFromData(self._image_cache[appid])
            new_widget.set_image(pixmap)

        self.games_list.setItemWidget(item, new_widget)

    # --- List Management ---

    def _on_sort_changed(self) -> None:
        self._refresh_game_list()

    def _on_source_filter_changed(self) -> None:
        if not self.game_manager:
            return
        self.game_manager.set_source_filter(self.source_combo.currentData())

    @staticmethod
    def _get_sort_key(game, sort_option):
        """Helper for sorting keys."""
        if sort_option in ("name_asc", "name_desc"):
            return game.get("game_name", "").lower()
        if sort_option in ("size_asc", "size_desc"):
            return game.get("size_on_disk", 0)
        if sort_option == "appid":
            try:
                return int(game.get("appid", 0))
            except (ValueError, TypeError):
                return 0
        if sort_option == "recently_installed":
            path = (
                game.get("lumatools_marker_path")
                or game.get("depot_downloader_path")
                or game.get("appmanifest_path")
                or game.get("install_path", "")
            )
            if path and os.path.exists(path):
                return os.path.getmtime(path)
            return 0
        return game.get("game_name", "").lower()

    def _sort_games(self, games: list) -> list:
        sort_option = self.sort_combo.currentData()
        reverse = sort_option in ("name_desc", "size_desc", "recently_installed")
        return sorted(
            games,
            key=lambda g: GameLibraryDialog._get_sort_key(g, sort_option),
            reverse=reverse,
        )

    def _refresh_game_list(self) -> None:
        if self._closing:
            return

        self._refreshing = True
        self.games_list.clear()

        if not self.game_manager:
            self._refreshing = False
            return

        games = self.game_manager.get_all_games()
        games = self._sort_games(games)
        total_size = 0
        lumatools_count = 0

        for game in games:
            if game.get("is_lumatools_install"):
                lumatools_count += 1
            total_size += self._add_game_to_list(game)

        self.info_label.setText(
            f"{len(games)} jogo(s) da Steam encontrado(s) ({lumatools_count} gerenciado(s) pelo LumaTools) - "
            f"Tamanho total: {GameLibraryDialog._format_size(total_size)}"
        )
        self._refreshing = False

    def _add_game_to_list(self, game: dict) -> int:
        """Creates and adds a single game widget to the list. Returns size."""
        size = game.get("size_on_disk", 0)
        widget = GameItemWidget(
            game,
            GameLibraryDialog._format_size(size),
            self.accent_color,
            self.background_color,
        )
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, game)
        item.setSizeHint(widget.sizeHint())
        self.games_list.addItem(item)
        self.games_list.setItemWidget(item, widget)

        app_id = str(game.get("appid", "0"))
        if app_id in ("0", "N/A", "unknown"):
            self.executor.submit(self._resolve_and_update_item, item, game)
        else:
            self._fetch_item_image(item, app_id)

        return size

    def _resolve_and_update_item(self, item: QListWidgetItem, game_data: dict) -> None:
        """Resolve AppID in a background thread and update the item."""
        name = game_data.get("game_name")
        resolved_appid = self._resolve_appid_by_name(name)
        if resolved_appid:
            game_data["appid"] = resolved_appid
            QTimer.singleShot(
                0, lambda: self._update_item_with_resolved_id(item, game_data)
            )

    @staticmethod
    def _resolve_appid_by_name(name: str) -> str | None:
        """Search the local database for an AppID by name."""
        if not name or not DatabaseManager:
            return None
        try:
            db = DatabaseManager()
            if not db.conn:
                return None

            cur = db.conn.cursor()
            cur.execute("SELECT appid FROM apps WHERE name = ? COLLATE NOCASE", (name,))
            row = cur.fetchone()
            if row:
                return str(row[0])
        except Exception as e:
            logger.debug(f"DB lookup failed for '{name}': {e}")
        return None

    def _update_item_with_resolved_id(
        self, item: QListWidgetItem, game_data: dict
    ) -> None:
        """Update the item on the main thread with the resolved AppID."""
        if self._closing:
            return
        item.setData(Qt.ItemDataRole.UserRole, game_data)
        self._fetch_item_image(item, game_data["appid"])

    def _on_item_selected(self, item: QListWidgetItem) -> None:
        """Handle click on list item."""
        if self._dialog_open or self._refreshing:
            return

        if not item:
            return

        game_data = item.data(Qt.ItemDataRole.UserRole)
        if not game_data:
            return

        # Debounce
        self._dialog_open = True
        QTimer.singleShot(500, lambda: setattr(self, "_dialog_open", False))

        self._show_game_details_dialog(game_data)

    # --- Image Handling ---

    def _fetch_item_image(self, _item: QListWidgetItem, app_id: str) -> None:
        if not ImageFetcher:
            return
        if app_id in self._active_fetchers:
            return

        url = ImageFetcher.get_header_image_url(app_id)
        if not url:
            return

        fetcher = ImageFetcher(url)
        fetcher.setProperty("app_id", app_id)
        self._active_fetchers[app_id] = fetcher

        fetcher.finished.connect(self._on_item_image_fetched)
        fetcher.finished.connect(lambda _, aid=app_id: self._cleanup_fetcher(aid))
        fetcher.start()

    def _cleanup_fetcher(self, app_id: str) -> None:
        if app_id in self._active_fetchers:
            del self._active_fetchers[app_id]

    def _on_item_image_fetched(self, image_data: bytes) -> None:
        if self._closing or not self.isVisible():
            return

        sender = self.sender()
        app_id = sender.property("app_id")
        if not app_id:
            return

        if not image_data:
            # If image fetch failed, trigger a background refresh of the URL
            QTimer.singleShot(0, lambda: self._trigger_header_refresh(app_id))
            return

        self._image_cache[app_id] = image_data

        # Find item and widget
        for i in range(self.games_list.count()):
            item = self.games_list.item(i)
            self._update_item_image_if_match(item, app_id, image_data)

    def _check_appid_match(self, data: dict, app_id: str) -> bool:
        """Helper to check if a game's AppID matches the target AppID."""
        game_appid = str(data.get("appid", "0"))
        if game_appid == app_id:
            return True
        if game_appid in ("0", "N/A", "unknown"):
            resolved = self._resolve_appid_by_name(data.get("game_name"))
            return resolved == app_id
        return False

    def _update_item_image_if_match(self, item, app_id, image_data):
        """Helper to check if list item matches app_id and update image."""
        data = item.data(Qt.ItemDataRole.UserRole)
        if self._check_appid_match(data, app_id):
            widget = self.games_list.itemWidget(item)
            if isinstance(widget, GameItemWidget):
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                widget.set_image(pixmap)

    def _trigger_header_refresh(self, app_id: str) -> None:
        """Trigger background refresh of header URL from API."""

        def fetch_and_update():
            try:
                from utils.image_fetcher import ImageFetcher

                return ImageFetcher.fetch_header_from_web_api(app_id)
            except Exception as e:
                logger.warning(f"Header refresh failed for {app_id}: {e}")
            return None

        def on_complete(future_result):
            try:
                url = future_result.result()
                if url and not self._closing:
                    QTimer.singleShot(
                        0, lambda: self._apply_header_refresh(app_id, url)
                    )
            except RuntimeError:
                pass

        future = self.executor.submit(fetch_and_update)
        future.add_done_callback(on_complete)

    def _apply_header_refresh(self, app_id: str, api_url: str) -> None:
        """Update DB and retry fetch with new URL."""
        if self._closing or not self.isVisible():
            return

        try:
            from managers.db_manager import DatabaseManager

            db = DatabaseManager()
            db.upsert_app_info(app_id, {"header_url": api_url})

            # Retry fetch
            if app_id not in self._active_fetchers:
                fetcher = ImageFetcher(api_url)
                fetcher.setProperty("app_id", app_id)
                self._active_fetchers[app_id] = fetcher
                fetcher.finished.connect(self._on_item_image_fetched)
                fetcher.finished.connect(
                    lambda _, aid=app_id: self._cleanup_fetcher(aid)
                )
                fetcher.start()
        except RuntimeError as e:
            logger.warning(f"Failed to apply header refresh: {e}")

    # --- Game Details Dialog ---

    def _show_game_details_dialog(self, game_data: dict) -> None:
        """Show detailed game info in a tabbed dialog."""
        self._details_dialog = QDialog(self)
        self._details_dialog.setWindowTitle("Detalhes do jogo")
        self._details_dialog.setMinimumWidth(500)
        self._details_dialog.setModal(True)

        # Consistent styling using background_color
        self._details_dialog.setStyleSheet(
            self.styleSheet()
            + f"""
            QTabWidget::pane {{ border: none; background-color: {self.background_color}; }}
            QTabBar::tab {{ 
                background: {self.background_color}; 
                color: #888; 
                padding: 8px 16px; 
            }}
            QTabBar::tab:selected {{ 
                color: {self.accent_color}; 
                border-bottom: 2px solid {self.accent_color}; 
            }}
            QWidget {{ background-color: {self.background_color}; }}
        """
        )

        main_layout = QVBoxLayout(self._details_dialog)
        tab_widget = QTabWidget()

        self._create_overview_tab(tab_widget, game_data, self._details_dialog)
        self._create_opencloudsave_tab(tab_widget, game_data, self._details_dialog)
        self._create_uninstall_tab(tab_widget, game_data, self._details_dialog)
        self._create_tools_tab(tab_widget, game_data, self._details_dialog)

        main_layout.addWidget(tab_widget)
        self._details_dialog.exec()
        self._details_dialog = None

    def _create_overview_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Overview tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        # Header Info
        name_lbl = QLabel(format_game_display_name(game_data))
        name_lbl.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {self.accent_color};"
        )
        layout.addWidget(name_lbl)

        status_text = {
            "update_available": "Nova versão disponível",
            "up_to_date": "Atualizado",
            "checking": "Verificando atualizações...",
        }.get(game_data.get("update_status"), "Desconhecido")

        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(f"color: {self.accent_color}; font-style: italic;")
        layout.addWidget(status_lbl)

        # Info Grid
        form = QFormLayout()

        def _lbl(text):
            label = QLabel(text)
            label.setStyleSheet(f"color: {self.accent_color};")
            return label

        form.addRow(_lbl("App ID:"), _lbl(str(game_data.get("appid"))))
        form.addRow(_lbl("Origem:"), _lbl(str(game_data.get("source", "Steam"))))
        size = GameLibraryDialog._format_size(game_data.get("size_on_disk", 0))
        form.addRow(_lbl("Tamanho:"), _lbl(size))
        form.addRow(_lbl("Caminho:"), _lbl(str(game_data.get("install_path"))))
        layout.addLayout(form)

        # Linux FakeAppID
        if platform.system() == "Linux":
            self._add_fake_appid_controls(layout, game_data)

        # Validate/Update Button
        validate_btn = QPushButton()
        is_update = game_data.get("update_status") == "update_available"
        validate_btn.setText("Baixar atualização" if is_update else "Validar arquivos")
        validate_btn.clicked.connect(
            lambda: self._fetch_game_manifest(game_data, dialog)
        )
        layout.addWidget(validate_btn)

        # Footer Actions
        btn_layout = QHBoxLayout()
        open_btn = QPushButton("Abrir pasta")
        open_btn.clicked.connect(
            lambda: GameLibraryDialog._open_folder(game_data.get("install_path"))
        )
        btn_layout.addWidget(open_btn)

        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(dialog.accept)
        btn_layout.addWidget(close_btn)

        layout.addStretch()
        layout.addLayout(btn_layout)
        tab_widget.addTab(tab, "Visão geral")

    def _create_opencloudsave_tab(self, tab_widget, game_data, dialog) -> None:
        """Create per-game OpenCloudSave controls."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(12)

        cloud_manager = getattr(self.main_window, "cloud_save_manager", None)
        appid = str(game_data.get("appid", "0"))
        game_name = game_data.get("game_name", "Desconhecido")

        if not cloud_manager or appid in ("0", "N/A", "unknown"):
            lbl = QLabel("OpenCloudSave indisponível para este jogo.")
            lbl.setStyleSheet(f"color: {self.accent_color};")
            layout.addWidget(lbl)
            layout.addStretch()
            tab_widget.addTab(tab, "OpenCloudSave")
            return

        entry = cloud_manager.get_game_config(appid, game_name)
        detected_paths = cloud_manager.discover_save_paths(game_data)
        configured_paths = entry.get("save_paths") or detected_paths

        enabled_checkbox = QCheckBox("Ativar sincronização deste jogo")
        enabled_checkbox.setStyleSheet(f"color: {self.accent_color};")
        enabled_checkbox.setChecked(entry.get("enabled", False))
        layout.addWidget(enabled_checkbox)

        remote_input = QLineEdit()
        remote_input.setPlaceholderText("Subpasta remota do jogo")
        remote_input.setText(entry.get("remote_subdir", ""))
        layout.addWidget(QLabel("Subpasta remota"))
        layout.addWidget(remote_input)

        path_editor = QTextEdit()
        path_editor.setPlaceholderText("Um caminho por linha")
        path_editor.setMinimumHeight(160)
        path_editor.setPlainText("\n".join(configured_paths))
        layout.addWidget(QLabel("Caminhos de save"))
        layout.addWidget(path_editor)

        status_label = QLabel(cloud_manager.get_status_text(appid))
        status_label.setWordWrap(True)
        status_label.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(status_label)

        btn_row = QHBoxLayout()

        detect_btn = QPushButton("Redetectar")

        def _redetect_paths():
            paths = cloud_manager.discover_save_paths(game_data)
            if paths:
                path_editor.setPlainText("\n".join(paths))
                status_label.setText("Caminhos detectados novamente.")
            else:
                status_label.setText(
                    "Nenhum caminho foi detectado. Você pode adicionar manualmente."
                )

        detect_btn.clicked.connect(_redetect_paths)
        btn_row.addWidget(detect_btn)

        add_btn = QPushButton("Adicionar pasta")

        def _add_directory():
            chosen = QFileDialog.getExistingDirectory(
                self, "Selecionar pasta de save", game_data.get("install_path", "")
            )
            if not chosen:
                return
            existing = [line.strip() for line in path_editor.toPlainText().splitlines() if line.strip()]
            if chosen not in existing:
                existing.append(chosen)
                path_editor.setPlainText("\n".join(existing))

        add_btn.clicked.connect(_add_directory)
        btn_row.addWidget(add_btn)

        save_btn = QPushButton("Salvar")

        def _collect_paths():
            return [
                line.strip()
                for line in path_editor.toPlainText().splitlines()
                if line.strip()
            ]

        def _save_cloud_config():
            cloud_manager.update_game_config(
                appid=appid,
                game_name=game_name,
                enabled=enabled_checkbox.isChecked(),
                save_paths=_collect_paths(),
                remote_subdir=remote_input.text().strip(),
            )
            status_label.setText("Configuração do OpenCloudSave salva.")
            QMessageBox.information(
                self, "OpenCloudSave", "Configuração salva para este jogo."
            )

        save_btn.clicked.connect(_save_cloud_config)
        btn_row.addWidget(save_btn)

        layout.addLayout(btn_row)

        sync_row = QHBoxLayout()
        upload_btn = QPushButton("Upload agora")
        download_btn = QPushButton("Download agora")
        open_btn = QPushButton("Abrir primeira pasta")

        def _open_first_path():
            paths = _collect_paths()
            if paths:
                GameLibraryDialog._open_folder(paths[0])

        open_btn.clicked.connect(_open_first_path)

        def _run_upload():
            _save_cloud_config()
            status_label.setText("Enviando saves para a nuvem...")
            cloud_manager.sync_game_upload(
                appid=appid,
                game_name=game_name,
                game_data=game_data,
                save_paths=_collect_paths(),
                remote_subdir=remote_input.text().strip(),
            )

        def _run_download():
            _save_cloud_config()
            status_label.setText("Baixando saves da nuvem...")
            cloud_manager.sync_game_download(
                appid=appid,
                game_name=game_name,
                game_data=game_data,
                save_paths=_collect_paths(),
                remote_subdir=remote_input.text().strip(),
            )

        upload_btn.clicked.connect(_run_upload)
        download_btn.clicked.connect(_run_download)
        sync_row.addWidget(upload_btn)
        sync_row.addWidget(download_btn)
        sync_row.addWidget(open_btn)
        layout.addLayout(sync_row)

        def _update_sync_status(finished_appid: str, success: bool, message: str) -> None:
            if finished_appid != appid:
                return
            if success:
                status_label.setText(cloud_manager.get_status_text(appid))
                QMessageBox.information(self, "OpenCloudSave", message)
            else:
                status_label.setText(f"Erro: {message}")
                QMessageBox.warning(self, "OpenCloudSave", message)

        cloud_manager.sync_finished.connect(_update_sync_status)

        footer = QLabel(
            "Dica: use um remoto rclone como Google Drive ou OneDrive na aba OpenCloudSave das configurações."
        )
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(footer)

        layout.addStretch()
        tab_widget.addTab(tab, "OpenCloudSave")

    def _add_fake_appid_controls(self, layout, game_data) -> None:
        """Helper to add Linux FakeAppID UI controls."""
        if not is_slssteam_config_management_enabled():
            return

        hbox = QHBoxLayout()
        checkbox = QCheckBox("Adicionar ao SLSonline como:")
        checkbox.setStyleSheet(f"color: {self.accent_color};")
        checkbox.setToolTip("Adiciona aos FakeAppIds no config.yaml do SLSsteam")
        hbox.addWidget(checkbox)

        hbox.addStretch()

        inp = QLineEdit()
        inp.setPlaceholderText("Spacewar (480)")
        inp.setFixedWidth(150)
        inp.setValidator(QIntValidator())
        hbox.addWidget(inp)

        save_btn = QPushButton("Salvar")
        save_btn.setFixedWidth(70)
        hbox.addWidget(save_btn)

        layout.addLayout(hbox)

        appid = str(game_data.get("appid", "0"))
        if appid in ("0", "N/A", "unknown", "480"):
            checkbox.setEnabled(False)
            inp.setEnabled(False)
            save_btn.setEnabled(False)
            return

        # Check initial state
        config = get_user_config_path()
        if config.exists():
            existing_fake_id = get_fake_appid(config, appid)
            if existing_fake_id:
                checkbox.setChecked(True)
                inp.setText(existing_fake_id)
            else:
                checkbox.setChecked(False)

        # Connect logic
        def _toggle(state):
            fake_id = inp.text().strip() or "480"
            name = game_data.get("game_name", "Desconhecido")
            if state == Qt.CheckState.Checked.value:
                # Ensure clean slate
                current_in_config = get_fake_appid(config, appid)
                if current_in_config:
                    remove_fake_app_id(config, appid, current_in_config)

                if not add_fake_app_id(config, appid, name, fake_id):
                    checkbox.setChecked(False)
            else:
                current_in_config = get_fake_appid(config, appid)
                if current_in_config:
                    if not remove_fake_app_id(config, appid, current_in_config):
                        checkbox.setChecked(True)

        def _update_fake_id():
            if checkbox.isChecked():
                fake_id = inp.text().strip() or "480"
                name = game_data.get("game_name", "Desconhecido")

                current_fake_id = get_fake_appid(config, appid)
                if current_fake_id:
                    remove_fake_app_id(config, appid, current_fake_id)

                add_fake_app_id(config, appid, name, fake_id)
                QMessageBox.information(self, "Sucesso", "AppID atualizado com sucesso.")

        checkbox.stateChanged.connect(_toggle)
        save_btn.clicked.connect(_update_fake_id)

    def _create_uninstall_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Uninstall tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        lbl = QLabel("Remover este jogo e seus arquivos?")
        lbl.setStyleSheet(f"color: {self.accent_color};")
        layout.addWidget(lbl)

        opts = {}
        if platform.system() == "Linux":
            opts["compat"] = QCheckBox("Remover dados do Proton/Wine")
            opts["saves"] = QCheckBox("Remover saves na nuvem")
            opts["compat"].setStyleSheet(f"color: {self.accent_color};")
            opts["saves"].setStyleSheet(f"color: {self.accent_color};")
            layout.addWidget(opts["compat"])
            layout.addWidget(opts["saves"])

        btn = QPushButton("Desinstalar jogo")
        btn.clicked.connect(lambda: self._uninstall_game(game_data, dialog, opts))
        layout.addWidget(btn)
        layout.addStretch()

        tab_widget.addTab(tab, "Desinstalar")

    def _create_tools_tab(self, tab_widget, game_data, dialog) -> None:
        """Helper to create the Tools tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        path = game_data.get("install_path")
        name = game_data.get("game_name")
        appid = str(game_data.get("appid", ""))

        # Steamless
        sl_btn = QPushButton("Remover DRM (Steamless)")
        sl_btn.clicked.connect(
            lambda: self.main_window.task_manager.run_steamless_for_game(path, name)
        )
        layout.addWidget(sl_btn)

        # ACF Fix
        fix_btn = QPushButton("Corrigir instalação (remover .acf)")
        fix_btn.clicked.connect(lambda: self._fix_game_install(game_data))
        layout.addWidget(fix_btn)

        # Goldberg
        self.gb_btn = QPushButton("Verificando status do Goldberg...")
        self.gb_btn.setEnabled(False)
        layout.addWidget(self.gb_btn)

        # Online-Fix
        self.of_btn = QPushButton("Baixar Online Fix (Multiplayer)")
        self.of_btn.setStyleSheet(f"border: 1px solid {self.accent_color};")
        layout.addWidget(self.of_btn)

        self.ryuu_btn = QPushButton("Aplicar Ryuu Fix")
        self.ryuu_btn.setToolTip("Baixa e aplica o fix Ryuu usando o jogo selecionado.")
        layout.addWidget(self.ryuu_btn)

        undo_fix_btn = QPushButton("Desfazer último fix")
        undo_fix_btn.clicked.connect(lambda: self._undo_last_fix_for_game(game_data))
        layout.addWidget(undo_fix_btn)

        def _on_of_click():
            from src.core.online_fix_api import OnlineFixAPI
            from src.core.online_fix_injector import OnlineFixInjector
            api = OnlineFixAPI()
            injector = OnlineFixInjector()
            self.of_btn.setText("Buscando fix...")
            self.of_btn.setEnabled(False)
            
            def _async_of():
                try:
                    page = api.search_game(name)
                    if not page:
                        QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Jogo não encontrado no Online-Fix.me"))
                        return
                    
                    folder_url = api.get_fix_download_link(page)
                    if not folder_url:
                        QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Link de download não encontrado."))
                        return
                    
                    files = api.get_direct_files(folder_url)
                    if not files:
                        QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Nenhum arquivo de fix (.zip/.rar) encontrado na pasta."))
                        return
                    
                    # Pegar o primeiro arquivo (geralmente o fix principal)
                    file_url = files[0]
                    save_path = os.path.join(get_base_path(), "downloads", os.path.basename(file_url))
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    
                    QMetaObject.invokeMethod(self, "_on_of_status", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Baixando fix..."))
                    if api.download_file(file_url, save_path):
                        QMetaObject.invokeMethod(self, "_on_of_status", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Injetando fix..."))
                        success, found_dlls, launch_options, _ = injector.inject_fix(path, save_path)
                        if success:
                            try:
                                from core.fix_planner import record_online_fix_layer
                            except ImportError:
                                from src.core.fix_planner import record_online_fix_layer
                            record_online_fix_layer(
                                path,
                                appid=appid,
                                game_name=name,
                                found_dlls=found_dlls,
                                launch_options=launch_options,
                            )
                            QMetaObject.invokeMethod(self, "_on_of_success", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Fix Online aplicado com sucesso! Verifique o arquivo LUMA_ONLINE_FIX_INFO.txt na pasta do jogo."))
                        else:
                            QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Falha ao injetar os arquivos do fix."))
                    else:
                        QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, "Falha ao baixar o arquivo de fix."))
                except Exception as e:
                    QMetaObject.invokeMethod(self, "_on_of_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, f"Erro: {str(e)}"))

            self.executor.submit(_async_of)

        self.of_btn.clicked.connect(_on_of_click)
        self.ryuu_btn.clicked.connect(lambda: self._apply_ryuu_fix_for_game(game_data))

        # Start background check
        self.executor.submit(self._check_goldberg_async, path)

        def _on_gb_click():
            if not self.main_window or not self.main_window.task_manager:
                return

            # Re-check status synchronously for the action (since we need current state)
            # Or better, rely on button text/state which we updated
            is_applied = "Remover" in self.gb_btn.text()

            if is_applied:
                self.main_window.task_manager.remove_goldberg_from_game(
                    path, appid, name, show_dialog=True
                )
            else:
                self.main_window.task_manager.apply_goldberg_to_game(
                    path, appid, name, show_dialog=True
                )

            # Re-trigger async check to update button
            self.gb_btn.setText("Atualizando status...")
            self.gb_btn.setEnabled(False)
            self.executor.submit(self._check_goldberg_async, path)

        self.gb_btn.clicked.connect(_on_gb_click)

        layout.addStretch()
        tab_widget.addTab(tab, "Ferramentas")

    def _check_goldberg_async(self, path: str) -> None:
        """Background task to check Goldberg status."""
        is_applied = GameLibraryDialog._is_goldberg_applied(path)
        self.goldberg_check_complete.emit(is_applied)

    @pyqtSlot(str)
    def _on_of_status(self, msg: str):
        self.of_btn.setText(msg)

    @pyqtSlot(str)
    def _on_of_success(self, msg: str):
        self.of_btn.setText("Fix Aplicado!")
        self.of_btn.setEnabled(True)
        QMessageBox.information(self, "Sucesso", msg)

    @pyqtSlot(str)
    def _on_of_error(self, msg: str):
        self.of_btn.setText("Baixar Online Fix (Multiplayer)")
        self.of_btn.setEnabled(True)
        QMessageBox.warning(self, "Erro", msg)

    def _apply_ryuu_fix_for_game(self, game_data: dict) -> None:
        try:
            from core.fix_planner import apply_ryuu_fix
            from core.ryuu_client import RyuuClient, load_ryuu_auth_key
        except ImportError:
            from src.core.fix_planner import apply_ryuu_fix
            from src.core.ryuu_client import RyuuClient, load_ryuu_auth_key

        appid = str(game_data.get("appid", "")).strip()
        path = game_data.get("install_path")
        name = game_data.get("game_name", "Jogo")

        if not appid.isdigit() or appid == "0" or not path:
            QMessageBox.warning(self, "Ryuu Fix", "Não consegui identificar esse jogo.")
            return

        if not load_ryuu_auth_key():
            QMessageBox.information(
                self,
                "Ryuu Fix",
                "Ryuu não conectado. Cole sua chave em Configurações > Integrações.",
            )
            if self.main_window and hasattr(self.main_window, "open_settings"):
                self.main_window.open_settings("ryuu")
            return

        self.ryuu_btn.setEnabled(False)
        self.ryuu_btn.setText("Aplicando Ryuu Fix...")

        def _async_ryuu():
            try:
                output_dir = Path(get_base_path()) / "ryuu_fixes"
                fix_path = RyuuClient().download(appid, output_dir, branch="public")
                result = apply_ryuu_fix(
                    path,
                    fix_path,
                    appid=appid,
                    game_name=name,
                    branch="public",
                    preserve_online_fix=True,
                )
                skipped = result.get("skipped_conflicts") or []
                msg = (
                    "Ryuu Fix aplicado. Arquivos protegidos do OnlineFix foram mantidos."
                    if skipped
                    else "Ryuu Fix aplicado."
                )
                QMetaObject.invokeMethod(
                    self,
                    "_on_ryuu_success",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, msg),
                )
            except Exception:
                logger.exception("Falha ao aplicar Ryuu Fix pela biblioteca")
                QMetaObject.invokeMethod(
                    self,
                    "_on_ryuu_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, "Não consegui baixar/aplicar o fix Ryuu. Verifique sua key ou tente novamente."),
                )

        self.executor.submit(_async_ryuu)

    @pyqtSlot(str)
    def _on_ryuu_success(self, msg: str):
        self.ryuu_btn.setText("Ryuu Fix aplicado")
        self.ryuu_btn.setEnabled(True)
        QMessageBox.information(self, "Ryuu Fix", msg)

    @pyqtSlot(str)
    def _on_ryuu_error(self, msg: str):
        self.ryuu_btn.setText("Aplicar Ryuu Fix")
        self.ryuu_btn.setEnabled(True)
        QMessageBox.warning(self, "Ryuu Fix", msg)

    def _undo_last_fix_for_game(self, game_data: dict) -> None:
        try:
            from core.fix_planner import undo_last_fix
        except ImportError:
            from src.core.fix_planner import undo_last_fix

        path = game_data.get("install_path")
        if not path:
            QMessageBox.warning(self, "Fixes", "Não consegui identificar a pasta do jogo.")
            return

        result = undo_last_fix(path)
        restored = len(result.get("restored_files") or [])
        removed = len(result.get("removed_files") or [])
        if not restored and not removed:
            QMessageBox.information(self, "Fixes", "Não há fix para desfazer.")
            return
        QMessageBox.information(
            self,
            "Fixes",
            f"Rollback concluído. Restaurados: {restored}. Removidos: {removed}.",
        )

    def _on_goldberg_check_complete(self, is_applied: bool) -> None:
        """Slot to update UI after background check."""
        # Ensure the dialog/button still exists and is relevant
        if not hasattr(self, "gb_btn"):
            return

        self.gb_btn.setText("Remover Goldberg" if is_applied else "Aplicar Goldberg")
        self.gb_btn.setEnabled(True)

        if is_applied:
            self.gb_btn.setStyleSheet(
                f"border: 1px solid {self.accent_color}; color: {self.accent_color};"
            )
        else:
            self.gb_btn.setStyleSheet("")

    # --- Actions ---

    def _fetch_game_manifest(self, game_data: dict, dialog: QDialog) -> None:
        app_id = str(game_data.get("appid", "0"))

        if app_id in ("0", "N/A", "unknown"):
            QMessageBox.warning(self, "Erro", "App ID inválido.")
            return

        name = game_data.get("game_name", "Desconhecido")
        status = game_data.get("update_status")

        # Determine if we can use local cache
        local_path = None
        if status != "update_available":
            fpath = (
                get_base_path() / "morrenus_manifests" / f"lumatools_fetch_{app_id}.zip"
            )
            if fpath.exists():
                local_path = str(fpath)

        if not local_path:
            self._handle_download_manifest(app_id, name, game_data, dialog)
        else:
            self._submit_job(local_path, game_data, dialog)

    def _handle_download_manifest(self, app_id, name, game_data, dialog):
        """Logic separated to flatten nesting in fetch_game_manifest."""
        if not self._confirm_action(
            "Confirmar download",
            f"Baixar o manifesto de '{name}'?\nIsso consumirá sua cota da API.",
        ):
            return

        if not morrenus_api:
            QMessageBox.critical(self, "Erro", "Módulo da API ausente.")
            return

        self._download_progress_dialog = QProgressDialog(
            f"Baixando {name}...", "Cancelar", 0, 0, self
        )
        self._download_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._download_progress_dialog.show()

        # Start async download
        self.executor.submit(self._download_manifest_async, app_id, game_data)

    def _download_manifest_async(self, app_id: str, game_data: dict) -> None:
        """Background task to download manifest."""
        try:
            fpath, error = morrenus_api.download_manifest(app_id)
            self.manifest_download_complete.emit(
                str(fpath) if fpath else "", str(error) if error else "", game_data
            )
        except Exception as e:
            self.manifest_download_complete.emit("", str(e), game_data)

    def _on_manifest_download_complete(
        self, fpath: str, error: str, game_data: dict
    ) -> None:
        """Slot to handle manifest download completion."""
        if self._download_progress_dialog:
            self._download_progress_dialog.close()
            self._download_progress_dialog = None

        if fpath:
            # If we have a valid path, submit the job
            # We need to access the dialog passed to _fetch_game_manifest, but it's not stored.
            # However, we stored _details_dialog in _show_game_details_dialog.
            if self._details_dialog:
                self._submit_job(fpath, game_data, self._details_dialog)
        else:
            QMessageBox.critical(self, "Erro", f"Falha: {error}")

    def _submit_job(self, filepath: str, game_data: dict, dialog: QDialog) -> None:
        """Submit the job to the main window queue."""
        metadata = {
            "appid": game_data.get("appid"),
            "library_path": game_data.get("library_path"),
            "install_path": game_data.get("install_path"),
        }
        self.main_window.job_queue.add_job(filepath, metadata)
        dialog.accept()
        self.accept()

    @staticmethod
    def _open_folder(path: str) -> None:
        if not path or not os.path.exists(path):
            return
        try:
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])
        except OSError:
            pass

    def _confirm_action(self, title: str, message: str) -> bool:
        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _uninstall_game(self, game_data: dict, dialog: QDialog, opts: dict) -> None:
        if not self.game_manager:
            return

        msg = self.game_manager.get_uninstall_confirmation_message(game_data)
        if not self._confirm_action("Confirmar desinstalação", msg):
            return

        # Extract boolean states from checkboxes
        c_data = opts.get("compat").isChecked() if "compat" in opts else False
        c_saves = opts.get("saves").isChecked() if "saves" in opts else False

        self._uninstall_progress_dialog = QProgressDialog(
            "Desinstalando jogo...", None, 0, 0, self
        )
        self._uninstall_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._uninstall_progress_dialog.show()

        # Start async uninstall
        self.executor.submit(self._uninstall_game_async, game_data, c_data, c_saves)

    def _uninstall_game_async(
        self, game_data: dict, c_data: bool, c_saves: bool
    ) -> None:
        """Background task to uninstall game."""
        try:
            success, err = self.game_manager.uninstall_game(
                game_data, remove_compatdata=c_data, remove_saves=c_saves
            )
            self.uninstall_complete.emit(success, str(err) if err else "")
        except Exception as e:
            self.uninstall_complete.emit(False, str(e))

    def _on_uninstall_complete(self, success: bool, error: str) -> None:
        """Slot to handle uninstall completion."""
        if self._uninstall_progress_dialog:
            self._uninstall_progress_dialog.close()
            self._uninstall_progress_dialog = None

        if success:
            QMessageBox.information(self, "Sucesso", "Jogo desinstalado.")
            if self._details_dialog:
                self._details_dialog.accept()
        else:
            QMessageBox.critical(self, "Erro", f"Falha: {error}")

    def _fix_game_install(self, game_data: dict) -> None:
        path = game_data.get("library_path")
        appid = str(game_data.get("appid", ""))

        if not path or not appid or appid == "0":
            return

        acf = os.path.join(path, "steamapps", f"appmanifest_{appid}.acf")
        if not os.path.exists(acf):
            QMessageBox.warning(self, "Erro", "Arquivo de manifesto não encontrado.")
            return

        if not self._confirm_action(
            "Confirmar", "Remover o arquivo de manifesto? A Steam irá verificar os arquivos novamente."
        ):
            return

        os.remove(acf)
        QMessageBox.information(self, "Concluído", "Manifesto removido.")
        if sys.platform == "linux":
            slssteam_api_send(f"install|{appid}|0")

    @staticmethod
    def _is_goldberg_applied(game_dir: str) -> bool:
        """Check for Goldberg backup files (.valve)."""
        if not game_dir or game_dir == "N/A" or not os.path.exists(game_dir):
            return False

        for root, _, files in os.walk(game_dir):
            for fname in files:
                if fname.lower() in (
                    "steam_api.dll.valve",
                    "steam_api64.dll.valve",
                    "libsteam_api.so.valve",
                    "libsteam_api64.so.valve",
                ):
                    return True
        return False

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        if size_bytes == 0:
            return "0 B"
        size_names = ["B", "KB", "MB", "GB", "TB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"

    def closeEvent(self, event) -> None:
        """Cleanup resources on close."""
        self._closing = True
        for fetcher in self._active_fetchers.values():
            fetcher.stop()
        self._active_fetchers.clear()
        self.executor.shutdown(wait=False)
        super().closeEvent(event)
