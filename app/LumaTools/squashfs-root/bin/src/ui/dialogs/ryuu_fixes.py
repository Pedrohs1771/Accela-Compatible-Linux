import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.ryuu_client import (
    RyuuClient,
    RyuuClientError,
    load_ryuu_auth_key,
    mask_key,
    save_ryuu_auth_key,
    secrets_path,
)
from utils.helpers import get_base_path
from utils.task_runner import TaskRunner

logger = logging.getLogger(__name__)


class RyuuFixesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.task_runner = TaskRunner()
        self.setWindowTitle("Ryuu Fixes")
        self.setMinimumWidth(640)
        self.setMinimumHeight(420)
        self._init_ui()
        self._load_games()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        title = QLabel("Ryuu Fixes")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(title)

        hint = QLabel(
            "Baixe fixes do Ryuu para uma pasta local. O LumaTools não aplica automaticamente; "
            "use somente quando o jogo correto for detectado e você confirmar."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_input.setPlaceholderText("Cole sua auth_key do Ryuu")
        self.key_input.setText(load_ryuu_auth_key())
        form.addRow("Auth key:", self.key_input)

        key_buttons = QHBoxLayout()
        self.save_key_button = QPushButton("Salvar key local")
        self.save_key_button.clicked.connect(self.save_key)
        self.test_key_button = QPushButton("Testar key")
        self.test_key_button.clicked.connect(self.test_key)
        self.open_site_button = QPushButton("Obter key")
        self.open_site_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://generator.ryuu.lol/"))
        )
        key_buttons.addWidget(self.save_key_button)
        key_buttons.addWidget(self.test_key_button)
        key_buttons.addWidget(self.open_site_button)
        form.addRow("", key_buttons)

        self.game_combo = QComboBox()
        self.game_combo.setEditable(True)
        self.game_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        form.addRow("Jogo/AppID:", self.game_combo)

        self.branch_input = QLineEdit("public")
        form.addRow("Branch:", self.branch_input)

        self.type_combo = QComboBox()
        self.type_combo.addItem("ZIP completo", "")
        self.type_combo.addItem("Manifest", "manifest")
        self.type_combo.addItem("Lua", "lua")
        form.addRow("Tipo:", self.type_combo)

        layout.addLayout(form)

        action_row = QHBoxLayout()
        self.download_button = QPushButton("Baixar fix")
        self.download_button.clicked.connect(self.download_fix)
        self.request_button = QPushButton("Request game")
        self.request_button.clicked.connect(self.request_game)
        self.update_button = QPushButton("Request update")
        self.update_button.clicked.connect(self.request_update)
        action_row.addWidget(self.download_button)
        action_row.addWidget(self.request_button)
        action_row.addWidget(self.update_button)
        layout.addLayout(action_row)

        self.status_label = QLabel(f"Secrets: {secrets_path()}")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _load_games(self):
        self.game_combo.clear()
        games = []
        manager = getattr(self.parent_window, "game_manager", None)
        if manager is not None:
            games = list(getattr(manager, "games", []) or [])

        added = set()
        for game in sorted(games, key=lambda item: str(item.get("game_name", "")).lower()):
            appid = str(game.get("appid", "")).strip()
            if not appid or appid in {"0", "N/A", "unknown"} or appid in added:
                continue
            name = str(game.get("game_name", appid)).strip() or appid
            self.game_combo.addItem(f"{name} ({appid})", appid)
            added.add(appid)

        if not added:
            self.game_combo.setEditText("")
            self.game_combo.lineEdit().setPlaceholderText("Digite um AppID")

    def _appid(self) -> str:
        data = self.game_combo.currentData()
        if data:
            return str(data).strip()
        text = self.game_combo.currentText().strip()
        if "(" in text and ")" in text:
            text = text[text.rfind("(") + 1:text.rfind(")")]
        return "".join(ch for ch in text if ch.isdigit())

    def _client(self) -> RyuuClient:
        key = self.key_input.text().strip()
        if key:
            return RyuuClient(key)
        return RyuuClient()

    def save_key(self):
        key = self.key_input.text().strip()
        if not key:
            QMessageBox.warning(self, "Ryuu Fixes", "Cole uma auth_key primeiro.")
            return
        save_ryuu_auth_key(key)
        self.status_label.setText(f"Key salva localmente: {mask_key(key)}")

    def _run_worker(self, label: str, fn):
        self._set_busy(True, label)
        worker = self.task_runner.run(fn)
        worker.finished.connect(self._on_worker_done)
        worker.error.connect(self._on_worker_error)

    def test_key(self):
        self.save_key()
        self._run_worker("Testando key Ryuu...", lambda: self._client().test_key())

    def download_fix(self):
        appid = self._appid()
        if not appid:
            QMessageBox.warning(self, "Ryuu Fixes", "Selecione um jogo ou informe um AppID.")
            return

        answer = QMessageBox.question(
            self,
            "Ryuu Fixes",
            f"Baixar fix Ryuu para AppID {appid}? Ele será salvo localmente e não será aplicado automaticamente.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.save_key()
        file_type = self.type_combo.currentData()
        branch = self.branch_input.text().strip() or "public"
        output_dir = get_base_path() / "ryuu_fixes"
        self._run_worker(
            "Baixando fix Ryuu...",
            lambda: self._client().download(
                appid,
                Path(output_dir),
                file_type=file_type,
                branch=branch,
            ),
        )

    def request_game(self):
        appid = self._appid()
        if not appid:
            QMessageBox.warning(self, "Ryuu Fixes", "Informe um AppID.")
            return
        self.save_key()
        self._run_worker("Enviando request Ryuu...", lambda: self._client().request_game(appid))

    def request_update(self):
        appid = self._appid()
        if not appid:
            QMessageBox.warning(self, "Ryuu Fixes", "Informe um AppID.")
            return
        self.save_key()
        branch = self.branch_input.text().strip() or "public"
        self._run_worker(
            "Pedindo update Ryuu...",
            lambda: self._client().request_update(appid, branch),
        )

    def _set_busy(self, busy: bool, status: str = ""):
        for widget in (
            self.save_key_button,
            self.test_key_button,
            self.download_button,
            self.request_button,
            self.update_button,
            self.game_combo,
            self.branch_input,
            self.type_combo,
        ):
            widget.setEnabled(not busy)
        if status:
            self.status_label.setText(status)

    def _on_worker_done(self, result: Any):
        self._set_busy(False)
        self.status_label.setText(f"Concluído: {result}")
        QMessageBox.information(self, "Ryuu Fixes", f"Concluído:\n{result}")

    def _on_worker_error(self, error_info):
        self._set_busy(False)
        _, error, _ = error_info
        message = str(error)
        logger.error("Ryuu task failed: %s", message)
        QMessageBox.critical(self, "Ryuu Fixes", message)
        self.status_label.setText(f"Erro: {message}")

    def closeEvent(self, event):
        try:
            self.task_runner.stop()
        except RuntimeError:
            pass
        super().closeEvent(event)
