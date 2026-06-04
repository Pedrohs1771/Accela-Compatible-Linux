import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import ZipFile

import requests

from PyQt6.QtCore import Q_ARG, QByteArray, QEvent, QMetaObject, QTimer, Qt, pyqtSlot
from PyQt6.QtGui import QBrush, QColor, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from core.fix_planner import apply_ryuu_fix
from core.ryuu_client import RyuuClient, load_ryuu_auth_key
from core.steam_helpers import get_steam_libraries
from utils.helpers import get_base_path

logger = logging.getLogger(__name__)


class RyuuFixesDialog(QDialog):
    """Small Ryuu launcher for installed games, without manual AppID/branch fields."""

    TOOL_APPIDS = {
        "228980",  # Steamworks Common Redistributables
        "1391110",  # Steam Linux Runtime - Soldier
        "1628350",  # Steam Linux Runtime - Sniper
        "1493710",  # Proton Experimental
    }
    TOOL_NAME_PARTS = (
        "proton",
        "steam linux runtime",
        "steamlinuxruntime",
        "steamworks common redistributables",
        "steamworks shared",
        "steamworks sdk",
        "redistributable",
        "runtime",
        "dedicated server",
        "sdk",
        "wallpaper engine",
        "wallpaper_engine",
        "steam controller configs",
    )

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window
        self.game_manager = getattr(main_window, "game_manager", None)
        self.executor = ThreadPoolExecutor(max_workers=2)
        self.games = []
        self.filtered_games = []
        self.selected_game = None
        self._suppress_search_refresh = False
        self._image_request_appid = ""

        self.setWindowTitle("Ryuu Fixes")
        self.setMinimumWidth(560)
        self._setup_ui()
        self._load_games()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        self.key_status_label = QLabel()
        layout.addWidget(self.key_status_label)

        self.status_label = QLabel("Escolha um jogo instalado.\nO Luma detecta AppID e branch automaticamente.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.show_steam_checkbox = QCheckBox("Mostrar jogos Steam normais")
        self.show_steam_checkbox.setToolTip("Por padrão, a lista mostra só jogos gerenciados pelo LumaTools.")
        self.show_steam_checkbox.stateChanged.connect(self._refresh_filtered_games)
        layout.addWidget(self.show_steam_checkbox)

        layout.addWidget(QLabel("Escolha um jogo instalado:"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar jogo...")
        self.search_input.textChanged.connect(self._refresh_filtered_games)
        self.search_input.installEventFilter(self)
        layout.addWidget(self.search_input)

        self.games_list = QListWidget()
        self.games_list.setMaximumHeight(220)
        self.games_list.itemSelectionChanged.connect(self._on_selection_changed)
        self.games_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.games_list)

        self.card = QFrame()
        self.card.setObjectName("ryuuGameCard")
        self.card.setFrameShape(QFrame.Shape.StyledPanel)
        self.card.setStyleSheet(
            "QFrame#ryuuGameCard { border: 1px solid palette(highlight); border-radius: 6px; padding: 8px; }"
        )
        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        self.card_image = QLabel("Sem imagem")
        self.card_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card_image.setFixedSize(184, 86)
        self.card_image.setStyleSheet("border: 1px solid palette(mid);")
        card_layout.addWidget(self.card_image)

        card_text = QVBoxLayout()
        self.selected_title_label = QLabel("Jogo selecionado: nenhum")
        self.selected_title_label.setWordWrap(True)
        self.selected_meta_label = QLabel("Escolha um item da lista.")
        self.selected_meta_label.setWordWrap(True)
        card_text.addWidget(self.selected_title_label)
        card_text.addWidget(self.selected_meta_label)
        card_text.addStretch()
        card_layout.addLayout(card_text, 1)
        layout.addWidget(self.card)

        self.details_button = QToolButton()
        self.details_button.setText("▸ Detalhes técnicos")
        self.details_button.setCheckable(True)
        self.details_button.setAutoRaise(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.details_button.toggled.connect(self._toggle_details)
        layout.addWidget(self.details_button)

        self.details_label = QLabel("")
        self.details_label.setWordWrap(True)
        self.details_label.setVisible(False)
        layout.addWidget(self.details_label)

        self.apply_button = QPushButton("Aplicar Ryuu Fix")
        self.apply_button.setDefault(True)
        self.apply_button.setMinimumHeight(38)
        self.apply_button.clicked.connect(self._primary_action)
        layout.addWidget(self.apply_button)

        button_row = QHBoxLayout()
        self.settings_button = QPushButton("Configurar Ryuu")
        self.settings_button.clicked.connect(self._open_ryuu_settings)
        button_row.addWidget(self.settings_button)

        self.close_button = QPushButton("Fechar")
        self.close_button.clicked.connect(self.close)
        button_row.addWidget(self.close_button)
        layout.addLayout(button_row)

    def _load_games(self) -> None:
        self.games = []
        self.games_list.clear()

        if not self.game_manager:
            self.status_label.setText("Biblioteca indisponível.")
            self.apply_button.setEnabled(False)
            return

        for game in getattr(self.game_manager, "games", []) or self.game_manager.get_all_games():
            appid = str(game.get("appid", "")).strip()
            resolved_dir = self._resolve_game_dir(game)
            if appid.isdigit() and appid != "0" and resolved_dir and not self._is_tool_or_runtime(game):
                game = dict(game)
                game["install_path"] = str(resolved_dir)
                self.games.append(game)

        self._refresh_key_status()
        self._refresh_filtered_games()
        if not self.games:
            self.status_label.setText("Nenhum jogo instalado com AppID detectado foi encontrado.")

    def _is_tool_or_runtime(self, game: dict) -> bool:
        appid = str(game.get("appid", "")).strip()
        name = str(game.get("game_name", "")).strip().lower()
        if appid in self.TOOL_APPIDS:
            return True
        if name == "common":
            return True
        return any(part in name for part in self.TOOL_NAME_PARTS)

    def _resolve_game_dir(self, game: dict) -> Path | None:
        """Resolve a real installed game directory from current metadata or Steam ACF."""
        appid = str(game.get("appid", "")).strip()

        raw_path = str(game.get("install_path", "")).strip()
        if raw_path:
            candidate = Path(raw_path)
            if candidate.is_dir():
                return candidate

        appmanifest_path = str(game.get("appmanifest_path", "")).strip()
        acf_candidates = []
        if appmanifest_path:
            acf_candidates.append(Path(appmanifest_path))

        for library in get_steam_libraries() or []:
            library_path = Path(library)
            acf_candidates.append(library_path / "steamapps" / f"appmanifest_{appid}.acf")
            acf_candidates.append(library_path / f"appmanifest_{appid}.acf")

        for acf in acf_candidates:
            if not acf.exists():
                continue
            installdir = self._read_acf_value(acf, "installdir")
            if not installdir:
                continue
            common_dir = acf.parent / "common"
            candidate = common_dir / installdir
            if candidate.is_dir():
                return candidate

        install_dir = str(game.get("install_dir", "")).strip()
        game_name = str(game.get("game_name", "")).strip()
        for name in [install_dir, game_name]:
            if not name:
                continue
            for library in get_steam_libraries() or []:
                library_path = Path(library)
                candidates = [
                    library_path / "steamapps" / "common" / name,
                    library_path / "common" / name,
                ]
                for candidate in candidates:
                    if candidate.is_dir():
                        return candidate

        logger.info(
            "Ryuu skipped %s (%s): install directory could not be resolved",
            game.get("game_name", "Jogo"),
            appid,
        )
        return None

    @staticmethod
    def _read_acf_value(acf_path: Path, key: str) -> str:
        try:
            content = acf_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""
        match = re.search(rf'"{re.escape(key)}"\s+"([^"]*)"', content, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    def _refresh_key_status(self) -> bool:
        configured = bool(load_ryuu_auth_key())
        self.key_status_label.setText("Ryuu: configurado ✓" if configured else "Ryuu: não configurado ⚠")
        self.apply_button.setText("Aplicar Ryuu Fix" if configured else "Configurar Ryuu")
        return configured

    def _refresh_filtered_games(self) -> None:
        if self._suppress_search_refresh:
            return

        query = self.search_input.text().strip().lower()
        include_steam = self.show_steam_checkbox.isChecked()
        previous_appid = str((self.selected_game or {}).get("appid", ""))

        self.filtered_games = []
        self.games_list.clear()
        self.games_list.setVisible(True)
        self.selected_game = None

        for game in self.games:
            if not include_steam and not game.get("is_lumatools_install"):
                continue
            if query and query not in str(game.get("game_name", "")).lower():
                continue
            self.filtered_games.append(game)

        for game in sorted(self.filtered_games, key=lambda item: item.get("game_name", "").lower()):
            name = game.get("game_name", "Jogo")
            source = "LumaTools" if game.get("is_lumatools_install") else "Steam"
            item = QListWidgetItem(self._item_text(game, selected=False))
            item.setToolTip(f"{name}\nFonte: {source}")
            item.setData(Qt.ItemDataRole.UserRole, game)
            self.games_list.addItem(item)
            if str(game.get("appid", "")) == previous_appid:
                item.setSelected(True)

        if not self.games_list.count():
            self._set_selected_game(None)
            self.status_label.setText("Nenhum jogo compatível encontrado para esse filtro.")
        elif not self.games_list.selectedItems():
            self._set_selected_game(None)
            self.status_label.setText("Escolha um jogo da lista ou pressione Enter para selecionar o primeiro resultado.")

    def _open_ryuu_settings(self) -> None:
        if self.main_window and hasattr(self.main_window, "open_settings"):
            self.main_window.open_settings("ryuu")
        self._refresh_key_status()

    def _primary_action(self) -> None:
        if not self._refresh_key_status():
            self._open_ryuu_settings()
            return
        self._apply_selected_game()

    def _on_selection_changed(self) -> None:
        items = self.games_list.selectedItems()
        self._set_selected_game(items[0].data(Qt.ItemDataRole.UserRole) if items else None, selected_item=items[0] if items else None)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._set_selected_game(item.data(Qt.ItemDataRole.UserRole), selected_item=item)
        if self._refresh_key_status():
            self._apply_selected_game()

    def _item_text(self, game: dict, selected: bool) -> str:
        name = game.get("game_name", "Jogo")
        source = "LumaTools" if game.get("is_lumatools_install") else "Steam"
        check = "  ✓" if selected else ""
        return f"{name}{check}  ·  {source}"

    def _refresh_item_checks(self, selected_appid: str) -> None:
        for index in range(self.games_list.count()):
            item = self.games_list.item(index)
            game = item.data(Qt.ItemDataRole.UserRole)
            selected = str(game.get("appid", "")) == selected_appid
            item.setText(self._item_text(game, selected=selected))

    def _set_selected_game(self, game: dict | None, selected_item: QListWidgetItem | None = None) -> None:
        self.selected_game = game
        if not game:
            self.selected_title_label.setText("Jogo selecionado: nenhum")
            self.selected_meta_label.setText("Escolha um item da lista.")
            self.card_image.setPixmap(QPixmap())
            self.card_image.setText("Sem imagem")
            self.details_label.setText("")
            self.apply_button.setEnabled(False)
            return

        name = game.get("game_name", "Jogo")
        appid = str(game.get("appid", "")).strip()
        source = "LumaTools" if game.get("is_lumatools_install") else "Steam"
        self._suppress_search_refresh = True
        self.search_input.setText(name)
        self._suppress_search_refresh = False
        self.selected_title_label.setText(name)
        self.selected_meta_label.setText(f"AppID detectado automaticamente\nFonte: {source}\nRyuu: pronto")
        self.details_label.setText(f"AppID: {appid}\nBranch: public\nFonte: {source}")
        self.apply_button.setEnabled(True)
        self._refresh_item_checks(appid)
        self._pulse_item(selected_item)
        self._load_card_image(game)
        self._refresh_key_status()

    def _pulse_item(self, item: QListWidgetItem | None) -> None:
        if not item:
            return
        highlight = QColor(self.palette().highlight().color())
        item.setBackground(QBrush(highlight.lighter(145)))
        QTimer.singleShot(150, lambda: item.setBackground(QBrush()))

    def _load_card_image(self, game: dict) -> None:
        appid = str(game.get("appid", "")).strip()
        if not appid:
            return
        self._image_request_appid = appid
        self.card_image.setPixmap(QPixmap())
        self.card_image.setText("Carregando...")

        def worker():
            data = self._download_card_image(appid)
            QMetaObject.invokeMethod(
                self,
                "_on_card_image_loaded",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, appid),
                Q_ARG(QByteArray, QByteArray(data or b"")),
            )

        self.executor.submit(worker)

    def _download_card_image(self, appid: str) -> bytes:
        cache_dir = Path(get_base_path()) / "cache" / "ryuu_cards"
        cache_path = cache_dir / f"{appid}.img"
        if cache_path.exists():
            try:
                return cache_path.read_bytes()
            except Exception:
                logger.debug("Failed to read cached Ryuu card for %s", appid, exc_info=True)

        sgdb_key = ""
        settings = getattr(self.main_window, "settings", None)
        if settings:
            sgdb_key = settings.value("sgdb_api_key", "", type=str).strip()

        if sgdb_key:
            try:
                headers = {"Authorization": f"Bearer {sgdb_key}"}
                game_response = requests.get(
                    f"https://www.steamgriddb.com/api/v2/games/steam/{appid}",
                    headers=headers,
                    timeout=8,
                )
                game_response.raise_for_status()
                game_id = game_response.json()["data"]["id"]
                grid_response = requests.get(
                    f"https://www.steamgriddb.com/api/v2/grids/game/{game_id}",
                    headers=headers,
                    params={"types": "static", "limit": 1},
                    timeout=8,
                )
                grid_response.raise_for_status()
                grids = grid_response.json().get("data") or []
                if grids:
                    image_response = requests.get(grids[0]["url"], timeout=8)
                    image_response.raise_for_status()
                    data = image_response.content
                    cache_dir.mkdir(parents=True, exist_ok=True)
                    cache_path.write_bytes(data)
                    return data
            except Exception:
                logger.debug("SteamGridDB card lookup failed for %s", appid, exc_info=True)

        try:
            fallback = requests.get(
                f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
                timeout=8,
            )
            fallback.raise_for_status()
            data = fallback.content
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(data)
            return data
        except Exception:
            logger.debug("Steam header fallback failed for %s", appid, exc_info=True)
            return b""

    @pyqtSlot(str, QByteArray)
    def _on_card_image_loaded(self, appid: str, data: QByteArray) -> None:
        if appid != self._image_request_appid:
            return
        pixmap = QPixmap()
        if data and pixmap.loadFromData(bytes(data)):
            scaled = pixmap.scaled(
                self.card_image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.card_image.setText("")
            self.card_image.setPixmap(scaled)
        else:
            self.card_image.setPixmap(QPixmap())
            self.card_image.setText(f"AppID\n{appid}")

    def _toggle_details(self, checked: bool) -> None:
        self.details_button.setText("▾ Detalhes técnicos" if checked else "▸ Detalhes técnicos")
        self.details_label.setVisible(checked)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.search_input and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.games_list.count():
                    self.games_list.setCurrentRow(0)
                    item = self.games_list.currentItem()
                    if item:
                        self._set_selected_game(item.data(Qt.ItemDataRole.UserRole), selected_item=item)
                    return True
            if event.key() == Qt.Key.Key_Escape:
                self.games_list.setVisible(False)
                return True
        return super().eventFilter(watched, event)

    def _apply_selected_game(self) -> None:
        game = self.selected_game
        if not game:
            QMessageBox.warning(self, "Ryuu Fix", "Selecione um jogo instalado.")
            return

        if not load_ryuu_auth_key():
            QMessageBox.information(
                self,
                "Ryuu Fix",
                "Ryuu não conectado. Cole sua chave em Configurações > Integrações.",
            )
            self._open_ryuu_settings()
            return

        self.apply_button.setEnabled(False)
        self.apply_button.setText("Aplicando...")
        self.status_label.setText(f"Baixando e aplicando Ryuu Fix em {game.get('game_name', 'Jogo')}...")

        def worker():
            try:
                appid = str(game.get("appid", "")).strip()
                game_name = game.get("game_name", "Jogo")
                game_dir = self._resolve_game_dir(game)
                if not game_dir:
                    raise FileNotFoundError(
                        f"Pasta do jogo nao encontrada ou nao instalada: {game_name} ({appid})"
                    )
                output_dir = Path(get_base_path()) / "ryuu_fixes"
                fix_path = RyuuClient().download(appid, output_dir, branch="public")
                if self._is_manifest_bundle(fix_path):
                    QMetaObject.invokeMethod(
                        self,
                        "_queue_ryuu_manifest_job",
                        Qt.ConnectionType.QueuedConnection,
                        Q_ARG(str, str(fix_path)),
                        Q_ARG(str, game_name),
                    )
                    return

                result = apply_ryuu_fix(
                    game_dir,
                    fix_path,
                    appid=appid,
                    game_name=game_name,
                    branch="public",
                    preserve_online_fix=True,
                )
                skipped = result.get("skipped_conflicts") or []
                message = (
                    "Ryuu Fix aplicado. Arquivos protegidos do OnlineFix foram mantidos."
                    if skipped
                    else "Ryuu Fix aplicado."
                )
                QMetaObject.invokeMethod(
                    self,
                    "_on_apply_success",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, message),
                )
            except Exception:
                logger.exception("Failed to apply Ryuu Fix")
                QMetaObject.invokeMethod(
                    self,
                    "_on_apply_error",
                    Qt.ConnectionType.QueuedConnection,
                    Q_ARG(str, "Não consegui baixar/aplicar o fix Ryuu. Verifique sua key ou tente novamente."),
                )

        self.executor.submit(worker)

    @staticmethod
    def _is_manifest_bundle(path: Path) -> bool:
        if path.suffix.lower() != ".zip":
            return False
        try:
            with ZipFile(path) as archive:
                names = [name.lower() for name in archive.namelist()]
        except Exception:
            return False
        has_lua = any(name.endswith(".lua") for name in names)
        has_manifest = any(name.endswith(".manifest") for name in names)
        return has_lua and has_manifest

    @pyqtSlot(str, str)
    def _queue_ryuu_manifest_job(self, fix_path: str, game_name: str) -> None:
        if not self.main_window:
            self._on_apply_error("Ryuu Fix baixado, mas a fila do Luma não está disponível.")
            return

        metadata = {
            "source": "ryuu",
            "auto_select_depots": True,
            "steam_restart_after": True,
            "library_path": (self.selected_game or {}).get("library_path", ""),
        }
        job_queue = getattr(self.main_window, "job_queue", None)
        if job_queue is not None and hasattr(job_queue, "add_job"):
            job_queue.add_job(fix_path, metadata=metadata)
        elif hasattr(self.main_window, "add_job_safely"):
            self.main_window.add_job_safely(fix_path)
        else:
            self._on_apply_error("Ryuu Fix baixado, mas a fila do Luma não está disponível.")
            return

        message = f"Ryuu Fix de {game_name} enviado para download/update automático."
        self.apply_button.setEnabled(True)
        self.apply_button.setText("Aplicar Ryuu Fix")
        self.status_label.setText(message)
        QTimer.singleShot(0, self.close)

    @pyqtSlot(str)
    def _on_apply_success(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.apply_button.setText("Aplicar Ryuu Fix")
        self.status_label.setText(message)
        QMessageBox.information(self, "Ryuu Fix", message)

    @pyqtSlot(str)
    def _on_apply_error(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.apply_button.setText("Aplicar Ryuu Fix")
        self.status_label.setText(message)
        QMessageBox.warning(self, "Ryuu Fix", message)

    def closeEvent(self, event) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
