from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

import requests
from PyQt6 import sip
from PyQt6.QtCore import QSize, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QPixmap
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.content_manager import ContentManager, ContentPackagePreview
from core.ryuu_client import RyuuClient, RyuuClientError, load_ryuu_auth_key
from core.workshop_manager import WorkshopManager
from utils.helpers import get_base_path
from utils.image_fetcher import ImageFetcher

logger = logging.getLogger(__name__)


class DlcCard(QWidget):
    def __init__(self, appid: str, name: str, accent: str, checked: bool = True):
        super().__init__()
        self.appid = str(appid)
        self.checkbox = None
        self.title_label = None
        self.image_label = None

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        self.checkbox = QLabel("✓" if checked else "")
        self.checkbox.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.checkbox.setFixedSize(26, 26)
        self.checkbox.setStyleSheet(
            f"border: 1px solid {accent}; color: {accent}; font-weight: bold;"
        )
        root.addWidget(self.checkbox)

        self.image_label = QLabel("DLC")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(92, 44)
        self.image_label.setStyleSheet(
            f"background: #111; border: 1px solid {accent}; color: {accent};"
        )
        root.addWidget(self.image_label)

        text = QVBoxLayout()
        self.title_label = QLabel(name)
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet("font-weight: bold;")
        appid_label = QLabel(f"AppID {self.appid}")
        appid_label.setStyleSheet("color: #888;")
        text.addWidget(self.title_label)
        text.addWidget(appid_label)
        root.addLayout(text, 1)

    def set_checked(self, checked: bool) -> None:
        self.checkbox.setText("✓" if checked else "")

    def set_name(self, name: str) -> None:
        self.title_label.setText(name)

    def set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class WorkshopResultCard(QWidget):
    def __init__(self, result: dict, accent: str):
        super().__init__()
        self.result = result
        self.image_label = None

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        self.image_label = QLabel("MOD")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setFixedSize(116, 64)
        self.image_label.setStyleSheet(
            f"background: #111; border: 1px solid {accent}; color: {accent};"
        )
        root.addWidget(self.image_label)

        text = QVBoxLayout()
        title = QLabel(result.get("title") or f"Workshop {result.get('workshop_id')}")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: bold;")
        meta = QLabel(f"ID {result.get('workshop_id')}")
        meta.setStyleSheet("color: #888;")
        text.addWidget(title)
        text.addWidget(meta)
        root.addLayout(text, 1)

    def set_image(self, data: bytes) -> None:
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )


class ContentManagerDialog(QDialog):
    zip_preview_ready = pyqtSignal(object)
    dlc_preview_ready = pyqtSignal(object, str)
    dlc_catalog_ready = pyqtSignal(object, str, object)
    dlc_names_ready = pyqtSignal(object)
    operation_failed = pyqtSignal(str)
    operation_done = pyqtSignal(str)
    workshop_registry_changed = pyqtSignal()
    workshop_search_ready = pyqtSignal(object)
    queue_job_requested = pyqtSignal(str, object)
    dlc_buttons_enabled = pyqtSignal(bool)
    workshop_button_enabled = pyqtSignal(bool)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.settings = getattr(main_window, "settings", None)
        self.content_manager = ContentManager()
        self.workshop_manager: WorkshopManager = (
            getattr(main_window, "workshop_manager", None) or WorkshopManager()
        )
        self.current_preview: ContentPackagePreview | None = None
        self.current_dlc_preview: ContentPackagePreview | None = None
        self.current_dlc_source = "content_zip"
        self.current_workshop_results: list[dict] = []
        self.dlc_cards: dict[str, DlcCard] = {}
        self.dlc_checked: set[str] = set()
        self._image_fetchers: list[ImageFetcher] = []
        self.games = self._load_games()

        self.accent_color = "#C06C84"
        self.background_color = "#000000"
        if self.settings:
            self.accent_color = self.settings.value("accent_color", self.accent_color)
            self.background_color = self.settings.value(
                "background_color", self.background_color
            )

        self._setup_window()
        self._setup_ui()
        self._connect_signals()
        self._refresh_workshop_list()
        QTimer.singleShot(0, self._load_selected_game_content)

    def _setup_window(self) -> None:
        self.setWindowTitle("DLC e Workshop - LumaTools")
        self.resize(880, 660)
        self.setMinimumSize(760, 540)
        self.setStyleSheet(
            f"""
            QDialog, QWidget {{
                background-color: {self.background_color};
                color: {self.accent_color};
            }}
            QFrame#heroCard, QFrame#panel {{
                background-color: #070707;
                border: 1px solid {self.accent_color};
            }}
            QLineEdit, QTextEdit, QListWidget, QComboBox {{
                background-color: #050505;
                color: {self.accent_color};
                border: 1px solid {self.accent_color};
                padding: 7px;
            }}
            QPushButton {{
                background-color: #111;
                color: {self.accent_color};
                border: 1px solid {self.accent_color};
                padding: 8px 12px;
            }}
            QPushButton:disabled {{
                color: #666;
                border-color: #444;
            }}
            QListWidget::item:selected {{
                background: rgba(192, 108, 132, 0.24);
            }}
            QTabWidget::pane {{
                border: 1px solid {self.accent_color};
            }}
            QTabBar::tab {{
                background: #050505;
                color: {self.accent_color};
                padding: 8px 14px;
            }}
            QTabBar::tab:selected {{
                background: #171017;
            }}
            """
        )

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_dlc_tab(), "DLC")
        self.tabs.addTab(self._build_workshop_tab(), "Workshop")
        self.tabs.addTab(self._build_zip_tab(), "Importar Manifest")
        root.addWidget(self.tabs)

        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Fechar")
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _build_game_combo(self) -> QComboBox:
        combo = QComboBox()
        for game in self.games:
            label = f"{game.get('game_name', 'Jogo')} ({game.get('appid')})"
            combo.addItem(label, game)
        return combo

    def _build_dlc_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.dlc_game_combo = self._build_game_combo()
        self.dlc_game_combo.currentIndexChanged.connect(self._load_selected_game_content)
        top.addWidget(QLabel("Jogo da biblioteca:"))
        top.addWidget(self.dlc_game_combo, 1)
        self.fetch_ryuu_dlc_btn = QPushButton("Buscar DLC no Ryuu")
        self.fetch_ryuu_dlc_btn.clicked.connect(self._fetch_ryuu_dlc)
        top.addWidget(self.fetch_ryuu_dlc_btn)
        layout.addLayout(top)

        self.hero_card = QFrame()
        self.hero_card.setObjectName("heroCard")
        hero = QHBoxLayout(self.hero_card)
        self.hero_image = QLabel("JOGO")
        self.hero_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hero_image.setFixedSize(220, 102)
        self.hero_image.setStyleSheet(
            f"background: #111; border: 1px solid {self.accent_color};"
        )
        hero.addWidget(self.hero_image)
        hero_text = QVBoxLayout()
        self.hero_title = QLabel("Selecione um jogo")
        self.hero_title.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.hero_subtitle = QLabel("O Luma detecta AppID e branch automaticamente.")
        self.hero_status = QLabel("DLC: aguardando jogo")
        hero_text.addWidget(self.hero_title)
        hero_text.addWidget(self.hero_subtitle)
        hero_text.addWidget(self.hero_status)
        hero_text.addStretch()
        hero.addLayout(hero_text, 1)
        layout.addWidget(self.hero_card)

        self.dlc_list = QListWidget()
        self.dlc_list.setSpacing(6)
        self.dlc_list.itemClicked.connect(self._toggle_dlc_item)
        layout.addWidget(self.dlc_list, 1)

        actions = QHBoxLayout()
        select_all_btn = QPushButton("Selecionar tudo")
        select_all_btn.clicked.connect(lambda: self._set_all_dlc_checked(True))
        actions.addWidget(select_all_btn)
        clear_btn = QPushButton("Desmarcar")
        clear_btn.clicked.connect(lambda: self._set_all_dlc_checked(False))
        actions.addWidget(clear_btn)
        actions.addStretch()
        self.apply_dlc_btn = QPushButton("Ativar DLCs selecionadas")
        self.apply_dlc_btn.setEnabled(False)
        self.apply_dlc_btn.clicked.connect(self._apply_selected_dlcs)
        actions.addWidget(self.apply_dlc_btn)
        layout.addLayout(actions)
        return tab

    def _build_zip_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        row = QHBoxLayout()
        self.zip_path_input = QLineEdit()
        self.zip_path_input.setPlaceholderText("Selecionar ZIP com .lua e .manifest")
        row.addWidget(self.zip_path_input)
        browse_btn = QPushButton("Procurar")
        browse_btn.clicked.connect(self._browse_zip)
        row.addWidget(browse_btn)
        layout.addLayout(row)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setText("Nenhum pacote selecionado.")
        layout.addWidget(self.preview_text)

        row2 = QHBoxLayout()
        preview_btn = QPushButton("Preview")
        preview_btn.clicked.connect(self._preview_zip)
        row2.addWidget(preview_btn)
        self.apply_zip_btn = QPushButton("Aplicar conteudo")
        self.apply_zip_btn.setEnabled(False)
        self.apply_zip_btn.clicked.connect(self._apply_zip_content)
        row2.addWidget(self.apply_zip_btn)
        repair_btn = QPushButton("Reparar ultimo conteudo")
        repair_btn.clicked.connect(self._repair_last_content)
        row2.addWidget(repair_btn)
        row2.addStretch()
        layout.addLayout(row2)
        return tab

    def _build_workshop_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        top = QHBoxLayout()
        self.workshop_game_combo = self._build_game_combo()
        top.addWidget(QLabel("Jogo:"))
        top.addWidget(self.workshop_game_combo, 1)
        layout.addLayout(top)

        search = QHBoxLayout()
        self.workshop_search_input = QLineEdit()
        self.workshop_search_input.setPlaceholderText("Pesquisar mods por nome")
        self.workshop_search_input.returnPressed.connect(self._search_workshop)
        search.addWidget(self.workshop_search_input)
        self.search_workshop_btn = QPushButton("Pesquisar")
        self.search_workshop_btn.clicked.connect(self._search_workshop)
        search.addWidget(self.search_workshop_btn)
        layout.addLayout(search)

        direct = QHBoxLayout()
        self.workshop_url_input = QLineEdit()
        self.workshop_url_input.setPlaceholderText("Ou cole link/ID do Workshop")
        direct.addWidget(self.workshop_url_input)
        self.download_workshop_btn = QPushButton("Baixar")
        self.download_workshop_btn.clicked.connect(self._download_workshop)
        direct.addWidget(self.download_workshop_btn)
        layout.addLayout(direct)

        self.workshop_status = QLabel(self._steamcmd_status_text())
        layout.addWidget(self.workshop_status)

        self.workshop_results = QListWidget()
        self.workshop_results.setSpacing(6)
        self.workshop_results.itemDoubleClicked.connect(
            lambda _item: self._download_selected_workshop()
        )
        layout.addWidget(self.workshop_results, 1)

        result_actions = QHBoxLayout()
        self.download_selected_workshop_btn = QPushButton("Baixar mod selecionado")
        self.download_selected_workshop_btn.clicked.connect(self._download_selected_workshop)
        result_actions.addWidget(self.download_selected_workshop_btn)
        result_actions.addStretch()
        layout.addLayout(result_actions)

        registry_panel = QFrame()
        registry_panel.setObjectName("panel")
        registry_layout = QVBoxLayout(registry_panel)
        registry_layout.addWidget(QLabel("Mods instalados pelo Luma:"))
        self.mods_list = QListWidget()
        self.mods_list.setMaximumHeight(120)
        registry_layout.addWidget(self.mods_list)
        actions = QHBoxLayout()
        refresh_btn = QPushButton("Atualizar lista")
        refresh_btn.clicked.connect(self._refresh_workshop_list)
        actions.addWidget(refresh_btn)
        open_dir_btn = QPushButton("Abrir pasta selecionada")
        open_dir_btn.clicked.connect(self._open_selected_mod_folder)
        actions.addWidget(open_dir_btn)
        actions.addStretch()
        registry_layout.addLayout(actions)
        layout.addWidget(registry_panel)
        return tab

    def _connect_signals(self) -> None:
        self.zip_preview_ready.connect(self._show_zip_preview)
        self.dlc_preview_ready.connect(self._show_dlc_preview)
        self.dlc_catalog_ready.connect(self._show_dlc_preview_with_names)
        self.dlc_names_ready.connect(self._apply_dlc_names)
        self.operation_failed.connect(self._show_error)
        self.operation_done.connect(self._show_done)
        self.workshop_registry_changed.connect(self._refresh_workshop_list)
        self.workshop_search_ready.connect(self._show_workshop_results)
        self.queue_job_requested.connect(self._queue_job)
        self.dlc_buttons_enabled.connect(self._set_dlc_buttons_enabled)
        self.workshop_button_enabled.connect(self._set_workshop_buttons_enabled)

    def _load_games(self) -> list[dict]:
        manager = getattr(self.main_window, "game_manager", None)
        if not manager:
            return []
        games = []
        blocked_terms = (
            "proton",
            "steam linux runtime",
            "steamworks common redistributables",
            "steam controller configs",
        )
        for game in manager.get_all_games():
            appid = str(game.get("appid") or "")
            install_path = str(game.get("install_path") or "")
            name = str(game.get("game_name") or "")
            if not appid or appid in {"0", "N/A", "unknown"}:
                continue
            if any(term in name.lower() for term in blocked_terms):
                continue
            if install_path and not Path(install_path).exists():
                continue
            games.append(game)
        return sorted(games, key=lambda item: item.get("game_name", "").lower())

    @staticmethod
    def _format_preview(preview: ContentPackagePreview) -> str:
        lines = [
            f"ZIP detectado: {preview.filename}",
            "",
            "Jogo:",
            f"{preview.game_name}",
            "",
            "Conteudo detectado:",
            f"- AppID base: {preview.appid}",
            f"- Depots: {', '.join(preview.depots) if preview.depots else 'nenhum'}",
            f"- DLCs/Apps adicionais: {len(preview.dlcs)}",
            f"- Manifests: {len(preview.manifests)}",
        ]
        if preview.dlcs:
            lines.append(f"- DLC AppIDs: {', '.join(preview.dlcs)}")
        return "\n".join(lines)

    def _ryuu_status_text(self) -> str:
        return "Ryuu: configurado" if load_ryuu_auth_key() else "Ryuu: nao configurado"

    def _steamcmd_status_text(self) -> str:
        steamcmd = self.workshop_manager.find_steamcmd()
        return f"SteamCMD: {steamcmd}" if steamcmd else "SteamCMD: nao encontrado"

    def _selected_game(self, combo: QComboBox) -> dict | None:
        data = combo.currentData()
        return data if isinstance(data, dict) else None

    def _game_header_url(self, game: dict) -> str:
        appid = str(game.get("appid") or "")
        return str(game.get("header_url") or ImageFetcher.get_header_image_url(appid))

    def _load_image_into_label(self, label: QLabel, url: str, size: QSize | None = None) -> None:
        if not url:
            return
        fetcher = ImageFetcher(url)
        self._image_fetchers.append(fetcher)

        def apply_image(data: bytes, target=label, target_size=size, owner=fetcher):
            try:
                if sip.isdeleted(target):
                    return
                pixmap = QPixmap()
                if data and pixmap.loadFromData(data):
                    final_size = target_size or target.size()
                    target.setPixmap(
                        pixmap.scaled(
                            final_size,
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
            except RuntimeError:
                logger.debug("Ignoring late image callback for deleted label")
            finally:
                if owner in self._image_fetchers:
                    self._image_fetchers.remove(owner)

        fetcher.finished.connect(apply_image)
        fetcher.start()

    def _load_selected_game_content(self) -> None:
        game = self._selected_game(self.dlc_game_combo)
        if not game:
            return
        name = str(game.get("game_name") or "Jogo")
        appid = str(game.get("appid") or "")
        self.hero_title.setText(name)
        self.hero_subtitle.setText(f"AppID {appid} detectado automaticamente.")
        self.hero_status.setText(f"{self._ryuu_status_text()} | consultando DLCs...")
        self._clear_dlc_list("Consultando catalogo de DLCs...")
        self.hero_image.setPixmap(QPixmap())
        self.hero_image.setText("JOGO")
        self._load_image_into_label(self.hero_image, self._game_header_url(game), self.hero_image.size())

        def worker():
            try:
                preview, source = self._find_package_for_game(appid)
                if preview and preview.dlcs:
                    catalog = self.content_manager.build_dlc_preview(
                        appid=appid,
                        game_name=name,
                        dlcs=list(preview.dlcs),
                        source="Ryuu/ZIP" if source == "ryuu" else "ZIP",
                        filename=preview.filename,
                        zip_path=preview.zip_path,
                    )
                    self.dlc_catalog_ready.emit(catalog, catalog.source, {})
                    return

                try:
                    steam_names, official_name = self.content_manager.fetch_store_dlc_catalog(appid)
                except Exception:
                    logger.debug("Steam DLC catalog lookup failed for %s", appid, exc_info=True)
                    steam_names, official_name = {}, ""
                merged_names = dict(steam_names)
                merged_dlcs = list(steam_names.keys())
                source_parts: list[str] = []
                if merged_dlcs:
                    source_parts.append("Steam")
                if preview and preview.dlcs:
                    for dlc_id in preview.dlcs:
                        if str(dlc_id) not in merged_dlcs:
                            merged_dlcs.append(str(dlc_id))
                    source_parts.append("Ryuu/ZIP" if source == "ryuu" else "ZIP")

                if merged_dlcs:
                    catalog = self.content_manager.build_dlc_preview(
                        appid=appid,
                        game_name=official_name or name,
                        dlcs=merged_dlcs,
                        source="+".join(source_parts) if source_parts else "steam_store",
                        filename=preview.filename if preview else "Steam DLC catalog",
                        zip_path=preview.zip_path if preview else "",
                    )
                    self.dlc_catalog_ready.emit(catalog, catalog.source, merged_names)
                    return

                self.dlc_catalog_ready.emit(None, "steam_store", {})
            except Exception as exc:
                self.operation_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _find_package_for_game(self, appid: str) -> tuple[ContentPackagePreview | None, str]:
        base = get_base_path()
        candidates: list[tuple[Path, str]] = []
        registry = self.content_manager.load_registry()
        for record in reversed(registry.get("packages", [])):
            if str(record.get("appid")) == str(appid):
                path = Path(str(record.get("zip_path") or ""))
                if path.exists():
                    candidates.append((path, str(record.get("source") or "content_zip")))

        search_paths = [
            base / "hubcap_manifests" / f"lumatools_fetch_{appid}.zip",
            base / "ryuu_content" / appid,
            base / "ryuu_fixes" / appid,
        ]
        for path in search_paths:
            if path.is_file():
                candidates.append((path, "content_zip"))
            elif path.is_dir():
                for zip_path in sorted(path.glob("*.zip"), reverse=True):
                    candidates.append((zip_path, "ryuu"))

        for path, source in candidates:
            try:
                preview = self.content_manager.preview_zip(path)
            except Exception:
                logger.debug("Ignoring invalid content package %s", path, exc_info=True)
                continue
            if str(preview.appid) == str(appid) and preview.dlcs:
                return preview, ("ryuu" if source == "ryuu" else "content_zip")
        return None, "content_zip"

    def _clear_dlc_list(self, message: str) -> None:
        self.dlc_list.clear()
        self.dlc_cards.clear()
        self.dlc_checked.clear()
        item = QListWidgetItem(message)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self.dlc_list.addItem(item)
        self.apply_dlc_btn.setEnabled(False)

    def _show_dlc_preview_with_names(
        self,
        preview: ContentPackagePreview | None,
        source: str,
        names: dict[str, str],
    ) -> None:
        self._show_dlc_preview(preview, source)
        if names:
            self._apply_dlc_names(names)

    def _show_dlc_preview(self, preview: ContentPackagePreview | None, source: str) -> None:
        self.current_dlc_preview = preview
        self.current_dlc_source = source
        self.dlc_list.clear()
        self.dlc_cards.clear()
        self.dlc_checked.clear()

        if not preview:
            self.hero_status.setText(f"{self._ryuu_status_text()} | nenhuma DLC detectada")
            self.apply_dlc_btn.setEnabled(False)
            self._clear_dlc_list(
                "Nenhuma DLC oficial detectada para este jogo. Se tiver pacote Ryuu, use Buscar DLC no Ryuu."
            )
            return

        self.hero_status.setText(
            f"{len(preview.dlcs)} DLC(s) detectada(s) | fonte: {source}"
        )
        if not preview.dlcs:
            self._clear_dlc_list("Pacote encontrado, mas nenhuma DLC/App adicional foi detectada.")
            return

        self.dlc_checked = set(str(dlc_id) for dlc_id in preview.dlcs)
        for dlc_id in preview.dlcs:
            item = QListWidgetItem()
            card = DlcCard(str(dlc_id), f"DLC {dlc_id}", self.accent_color, checked=True)
            item.setData(Qt.ItemDataRole.UserRole, str(dlc_id))
            item.setSizeHint(QSize(500, 76))
            self.dlc_list.addItem(item)
            self.dlc_list.setItemWidget(item, card)
            self.dlc_cards[str(dlc_id)] = card
            self._load_image_into_label(
                card.image_label,
                ImageFetcher.get_capsule_image_url(dlc_id),
                card.image_label.size(),
            )
        self.apply_dlc_btn.setEnabled(True)
        self._fetch_dlc_names(preview.dlcs)

    def _fetch_dlc_names(self, dlc_ids: list[str]) -> None:
        ids = [str(item) for item in dlc_ids[:40]]
        if not ids:
            return

        def worker():
            names: dict[str, str] = {}
            try:
                response = requests.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": ",".join(ids), "filters": "basic"},
                    timeout=12,
                    headers={"User-Agent": "Mozilla/5.0 LumaTools"},
                )
                response.raise_for_status()
                payload = response.json()
                for appid, data in payload.items():
                    if data.get("success") and data.get("data", {}).get("name"):
                        names[str(appid)] = str(data["data"]["name"])
            except Exception:
                logger.debug("DLC name lookup failed", exc_info=True)
            self.dlc_names_ready.emit(names)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_dlc_names(self, names: dict[str, str]) -> None:
        for appid, name in names.items():
            card = self.dlc_cards.get(str(appid))
            if card:
                card.set_name(name)

    def _toggle_dlc_item(self, item: QListWidgetItem) -> None:
        dlc_id = item.data(Qt.ItemDataRole.UserRole)
        if not dlc_id:
            return
        dlc_text = str(dlc_id)
        if dlc_text in self.dlc_checked:
            self.dlc_checked.remove(dlc_text)
        else:
            self.dlc_checked.add(dlc_text)
        card = self.dlc_cards.get(dlc_text)
        if card:
            card.set_checked(dlc_text in self.dlc_checked)
        self.apply_dlc_btn.setEnabled(bool(self.dlc_checked))

    def _set_all_dlc_checked(self, checked: bool) -> None:
        self.dlc_checked = set(self.dlc_cards.keys()) if checked else set()
        for dlc_id, card in self.dlc_cards.items():
            card.set_checked(dlc_id in self.dlc_checked)
        self.apply_dlc_btn.setEnabled(bool(self.dlc_checked))

    def _fetch_ryuu_dlc(self) -> None:
        game = self._selected_game(self.dlc_game_combo)
        if not game:
            self._show_error("Selecione um jogo instalado.")
            return
        if not load_ryuu_auth_key():
            self._show_error("Configure a chave Ryuu nas integracoes.")
            return

        appid = str(game.get("appid"))
        output_dir = get_base_path() / "ryuu_content" / appid
        self._set_dlc_buttons_enabled(False)
        self.hero_status.setText("Ryuu: baixando pacote DLC...")

        def worker():
            try:
                fix_path = RyuuClient().download(appid, output_dir, branch="public")
                preview = self.content_manager.preview_zip(fix_path)
                self.content_manager.register_package(preview, source="ryuu", status="ready")
                if not preview.dlcs:
                    self.operation_done.emit(
                        "Pacote Ryuu baixado, mas ele nao expõe DLCs/AppIDs adicionais."
                    )
                    self.dlc_preview_ready.emit(None, "ryuu")
                    return
                self.dlc_catalog_ready.emit(preview, "ryuu", {})
                self.operation_done.emit("DLC Ryuu carregada. Selecione e ative.")
            except (RyuuClientError, Exception) as exc:
                self.operation_failed.emit(f"Nao consegui buscar DLC no Ryuu: {exc}")
            finally:
                self.dlc_buttons_enabled.emit(True)

        threading.Thread(target=worker, daemon=True).start()

    def _apply_selected_dlcs(self) -> None:
        if not self.current_dlc_preview:
            self._show_error("Nenhum pacote DLC carregado.")
            return
        game = self._selected_game(self.dlc_game_combo)
        if not game:
            self._show_error("Selecione um jogo instalado.")
            return
        game_dir = game.get("install_path")
        if not game_dir:
            self._show_error("Pasta do jogo nao encontrada.")
            return
        selected = sorted(self.dlc_checked)
        if not selected:
            self._show_error("Selecione pelo menos uma DLC.")
            return

        names = {
            dlc_id: self.dlc_cards[dlc_id].title_label.text()
            for dlc_id in selected
            if dlc_id in self.dlc_cards
        }
        if sys.platform == "linux" and self.settings:
            self.settings.setValue("library_mode", True)
            self.settings.setValue("sls_config_management", True)
        try:
            info = self.content_manager.activate_dlcs(
                self.current_dlc_preview,
                game_dir,
                selected,
                dlc_names=names,
                source=self.current_dlc_source,
            )
        except Exception as exc:
            self._show_error(f"Nao consegui ativar as DLCs: {exc}")
            return

        self.hero_status.setText(
            f"{len(selected)} DLC(s) ativada(s). Reinicie a Steam para aplicar."
        )
        reply = QMessageBox.question(
            self,
            "DLC ativada",
            (
                f"{len(selected)} DLC(s) foram ativadas para {info.get('game_name')}.\n\n"
                "Nenhum arquivo do jogo foi sobrescrito.\n"
                "Deseja reiniciar a Steam agora para aplicar?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            job_queue = getattr(self.main_window, "job_queue", None)
            if job_queue and hasattr(job_queue, "_perform_steam_restart"):
                threading.Thread(target=job_queue._perform_steam_restart, daemon=True).start()

    def _set_dlc_buttons_enabled(self, enabled: bool) -> None:
        self.fetch_ryuu_dlc_btn.setEnabled(enabled)
        self.apply_dlc_btn.setEnabled(enabled and bool(self.dlc_checked))

    def _stop_image_fetchers(self) -> None:
        for fetcher in list(self._image_fetchers):
            try:
                fetcher.stop()
            except Exception:
                logger.debug("Failed to stop image fetcher", exc_info=True)
        self._image_fetchers.clear()

    def _browse_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar pacote", str(Path.home()), "ZIP (*.zip)"
        )
        if path:
            self.zip_path_input.setText(path)
            self._preview_zip()

    def _preview_zip(self) -> None:
        path = self.zip_path_input.text().strip()
        if not path:
            self._show_error("Selecione um ZIP primeiro.")
            return

        def worker():
            try:
                preview = self.content_manager.preview_zip(path)
                self.zip_preview_ready.emit(preview)
            except Exception as exc:
                self.operation_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _show_zip_preview(self, preview: ContentPackagePreview) -> None:
        self.current_preview = preview
        self.preview_text.setText(self._format_preview(preview))
        self.apply_zip_btn.setEnabled(preview.is_valid)

    def _apply_zip_content(self) -> None:
        if not self.current_preview:
            self._show_error("Nenhum preview valido.")
            return
        metadata = {
            "source": "content_zip",
            "auto_select_depots": True,
            "content_preview": self.current_preview.filename,
        }
        self.content_manager.register_package(
            self.current_preview, source="local_zip", status="queued"
        )
        self.queue_job_requested.emit(self.current_preview.zip_path, metadata)
        self.operation_done.emit("Conteudo enviado para a fila do Luma.")

    def _repair_last_content(self) -> None:
        registry = self.content_manager.load_registry()
        for record in reversed(registry.get("packages", [])):
            zip_path = record.get("zip_path")
            if zip_path and Path(zip_path).exists():
                metadata = {
                    "source": "content_zip",
                    "auto_select_depots": True,
                    "content_preview": record.get("filename", Path(zip_path).name),
                    "repair": True,
                }
                self.queue_job_requested.emit(zip_path, metadata)
                self.operation_done.emit("Ultimo conteudo reenviado para reparo.")
                return
        self._show_error("Nenhum pacote local registrado para reparar.")

    def _queue_job(self, path: str, metadata: object) -> None:
        data = metadata if isinstance(metadata, dict) else {}
        self.main_window.job_queue.add_job(path, data)

    def _search_workshop(self) -> None:
        game = self._selected_game(self.workshop_game_combo)
        query = self.workshop_search_input.text().strip()
        if not game:
            self._show_error("Selecione um jogo instalado.")
            return
        if not query:
            self._show_error("Digite o nome do mod.")
            return
        self._set_workshop_buttons_enabled(False)
        self.workshop_status.setText("Workshop: pesquisando...")
        self.workshop_results.clear()

        def worker():
            try:
                results = self.workshop_manager.search_items(game.get("appid"), query)
                self.workshop_search_ready.emit(results)
            except Exception as exc:
                self.operation_failed.emit(f"Falha na busca Workshop: {exc}")
            finally:
                self.workshop_button_enabled.emit(True)

        threading.Thread(target=worker, daemon=True).start()

    def _show_workshop_results(self, results: list[dict]) -> None:
        self.current_workshop_results = results
        self.workshop_results.clear()
        if not results:
            self.workshop_status.setText("Workshop: nenhum mod encontrado.")
            return
        self.workshop_status.setText(f"Workshop: {len(results)} resultado(s).")
        for result in results:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, result)
            item.setSizeHint(QSize(500, 88))
            card = WorkshopResultCard(result, self.accent_color)
            self.workshop_results.addItem(item)
            self.workshop_results.setItemWidget(item, card)
            image = result.get("image") or ""
            if image:
                self._load_image_into_label(card.image_label, image, card.image_label.size())

    def _selected_workshop_result(self) -> dict | None:
        item = self.workshop_results.currentItem()
        if not item:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        return data if isinstance(data, dict) else None

    def _download_selected_workshop(self) -> None:
        result = self._selected_workshop_result()
        if not result:
            self._show_error("Selecione um resultado da Workshop.")
            return
        self.workshop_url_input.setText(str(result.get("workshop_id") or ""))
        self._download_workshop(result)

    def _download_workshop(self, result: dict | None = None) -> None:
        game = self._selected_game(self.workshop_game_combo)
        if not game:
            self._show_error("Selecione um jogo instalado.")
            return
        item_id = (
            str(result.get("workshop_id"))
            if result
            else self.workshop_manager.parse_workshop_id(self.workshop_url_input.text())
        )
        if not item_id:
            self._show_error("Link ou ID do Workshop invalido.")
            return
        game_dir = game.get("install_path")
        if not game_dir:
            self._show_error("Pasta do jogo nao encontrada.")
            return

        self._set_workshop_buttons_enabled(False)
        self.workshop_status.setText("Workshop: baixando via SteamCMD...")

        def worker():
            try:
                record = self.workshop_manager.download_item_sync(
                    game.get("appid"), item_id, game_dir=game_dir
                )
                if result and result.get("title"):
                    record = self.workshop_manager.register_item(
                        appid=str(game.get("appid")),
                        workshop_id=item_id,
                        download_path=record.get("download_path", ""),
                        installed_path=record.get("installed_path", ""),
                        title=str(result.get("title")),
                    )
                self.operation_done.emit(
                    f"Workshop {record.get('title') or record.get('workshop_id')} instalado."
                )
                self.workshop_registry_changed.emit()
            except Exception as exc:
                self.operation_failed.emit(str(exc))
            finally:
                self.workshop_button_enabled.emit(True)

        threading.Thread(target=worker, daemon=True).start()

    def _set_workshop_buttons_enabled(self, enabled: bool) -> None:
        self.search_workshop_btn.setEnabled(enabled)
        self.download_workshop_btn.setEnabled(enabled)
        self.download_selected_workshop_btn.setEnabled(enabled)

    def _refresh_workshop_list(self) -> None:
        self.mods_list.clear()
        for record in self.workshop_manager.load_registry():
            label = (
                f"{'[x]' if record.get('enabled') else '[ ]'} "
                f"{record.get('title', 'Workshop')} "
                f"({record.get('appid')} / {record.get('workshop_id')})"
            )
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, record)
            self.mods_list.addItem(item)

    def _open_selected_mod_folder(self) -> None:
        item = self.mods_list.currentItem()
        if not item:
            return
        record = item.data(Qt.ItemDataRole.UserRole) or {}
        path = record.get("installed_path") or record.get("download_path")
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_error(self, message: str) -> None:
        if hasattr(self, "workshop_status"):
            self.workshop_status.setText(message)
        if hasattr(self, "hero_status"):
            self.hero_status.setText(message)
        QMessageBox.warning(self, "DLC e Workshop", message)

    def _show_done(self, message: str) -> None:
        if hasattr(self, "workshop_status"):
            self.workshop_status.setText(message)
        if hasattr(self, "hero_status") and "DLC" in message:
            self.hero_status.setText(message)
        logger.info(message)

    def closeEvent(self, event) -> None:
        self._stop_image_fetchers()
        super().closeEvent(event)
