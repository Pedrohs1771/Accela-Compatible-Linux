import json
import logging
import subprocess
from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.dialog_helpers import create_standard_buttons
from utils.helpers import create_checkbox_setting, get_base_path
from utils.settings import get_settings

logger = logging.getLogger(__name__)


class UpdateCenterDialog(QDialog):
    """Dedicated update center dialog kept outside the settings tabs."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Update Center")
        self.setMinimumWidth(900)
        self.setMinimumHeight(520)
        self.resize(980, 560)

        self.main_window = parent
        self.settings = get_settings()

        self.github_updates_checkbox = None
        self.github_auto_update_checkbox = None
        self.github_signed_updates_checkbox = None
        self.github_repo_input = None
        self.advanced_updates_toggle = None
        self.advanced_updates_container = None
        self.update_current_version_label = None
        self.update_state_heading = None
        self.update_environment_label = None
        self.update_status_label = None
        self.update_security_label = None
        self.update_backup_label = None
        self.update_now_button = None
        self.update_rollback_button = None

        self._apply_dialog_style()
        self._setup_ui()

    def _apply_dialog_style(self) -> None:
        accent = self.settings.value("accent_color", "#C06C84")
        bg = self.settings.value("background_color", "#000000")
        soft = "#A6A6A6"
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {bg};
            }}
            QLabel, QCheckBox, QLineEdit, QPushButton, QGroupBox {{
                font-size: 13px;
                font-family: "DejaVu Sans Mono";
            }}
            QLabel {{
                color: #D6D6D6;
            }}
            QGroupBox {{
                border: 1px solid rgba(255, 255, 255, 0.14);
                margin-top: 14px;
                padding-top: 16px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: {accent};
                font-size: 14px;
                font-weight: 700;
            }}
            QLineEdit {{
                min-height: 36px;
                padding: 6px 10px;
                border: 1px solid {accent};
                color: {accent};
                background-color: {bg};
                selection-background-color: {accent};
            }}
            QPushButton {{
                min-height: 36px;
                padding: 6px 12px;
                border: 1px solid {accent};
                color: {accent};
                background-color: {bg};
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.06);
            }}
            QPushButton:disabled {{
                color: {soft};
                border-color: rgba(255, 255, 255, 0.18);
            }}
            """
        )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        updates_group = QGroupBox("Atualizações pelo GitHub")
        updates_layout = QVBoxLayout()
        updates_layout.setSpacing(10)

        self.update_current_version_label = QLabel("Versão atual: --")
        self.update_current_version_label.setStyleSheet(
            "font-size: 15px; font-weight: 700;"
        )
        updates_layout.addWidget(self.update_current_version_label)

        self.update_state_heading = QLabel("Status: aguardando verificação")
        self.update_state_heading.setStyleSheet(
            "font-size: 17px; font-weight: 700; color: #D6D6D6;"
        )
        updates_layout.addWidget(self.update_state_heading)

        self.update_environment_label = QLabel("Sistema: analisando ambiente local...")
        self.update_environment_label.setWordWrap(True)
        self.update_environment_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        updates_layout.addWidget(self.update_environment_label)

        self.github_updates_checkbox = create_checkbox_setting(
            "Verificar atualizações ao abrir",
            "github_updates_enabled",
            True,
            self,
            "Consulta o repositório no GitHub quando o ACCELA inicia.",
        )
        updates_layout.addWidget(self.github_updates_checkbox)

        self.github_auto_update_checkbox = create_checkbox_setting(
            "Instalar atualização automaticamente",
            "github_auto_update",
            False,
            self,
            "Baixa e aplica a release mais recente sem pedir confirmação extra.",
        )
        updates_layout.addWidget(self.github_auto_update_checkbox)

        self.github_signed_updates_checkbox = create_checkbox_setting(
            "Exigir assinatura válida no update",
            "github_signed_updates_only",
            True,
            self,
            "Bloqueia updates sem manifesto assinado e verificação de integridade.",
        )
        updates_layout.addWidget(self.github_signed_updates_checkbox)

        self.advanced_updates_toggle = QCheckBox("Mostrar opções avançadas")
        self.advanced_updates_toggle.toggled.connect(self._toggle_advanced_updates)
        updates_layout.addWidget(self.advanced_updates_toggle)

        self.advanced_updates_container = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_updates_container)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(QLabel("Repositório"))
        self.github_repo_input = QLineEdit()
        self.github_repo_input.setText(
            self.settings.value(
                "github_updates_repo",
                "Pedrohs1771/Accela-Compatible-Linux",
                type=str,
            )
        )
        self.github_repo_input.setPlaceholderText("usuario/repositorio")
        advanced_layout.addWidget(self.github_repo_input)
        self.advanced_updates_container.setVisible(False)
        updates_layout.addWidget(self.advanced_updates_container)

        self.update_status_label = QLabel("Aguardando verificação.")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        updates_layout.addWidget(self.update_status_label)

        self.update_security_label = QLabel("Assinatura: aguardando verificação.")
        self.update_security_label.setWordWrap(True)
        self.update_security_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        updates_layout.addWidget(self.update_security_label)

        self.update_backup_label = QLabel("Rollback: analisando backups locais...")
        self.update_backup_label.setWordWrap(True)
        self.update_backup_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        updates_layout.addWidget(self.update_backup_label)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)

        check_button = QPushButton("Verificar agora")
        check_button.clicked.connect(self._check_for_updates_now)
        buttons_layout.addWidget(check_button)

        self.update_now_button = QPushButton("Atualizar agora")
        self.update_now_button.clicked.connect(self._install_update_now)
        self.update_now_button.setEnabled(False)
        buttons_layout.addWidget(self.update_now_button)

        apply_later_button = QPushButton("Aplicar ao fechar")
        apply_later_button.clicked.connect(self._enable_auto_update)
        buttons_layout.addWidget(apply_later_button)

        self.update_rollback_button = QPushButton("Voltar backup")
        self.update_rollback_button.clicked.connect(self._rollback_latest_backup)
        self.update_rollback_button.setEnabled(False)
        buttons_layout.addWidget(self.update_rollback_button)

        updates_layout.addLayout(buttons_layout)
        updates_group.setLayout(updates_layout)
        layout.addWidget(updates_group)

        buttons = create_standard_buttons(self.accept, self.reject)
        layout.addWidget(buttons)

        self._wire_update_manager()

    def _toggle_advanced_updates(self, checked: bool) -> None:
        if self.advanced_updates_container is not None:
            self.advanced_updates_container.setVisible(checked)

    def _wire_update_manager(self) -> None:
        manager = getattr(self.main_window, "update_manager", None)
        if manager is None:
            self._refresh_update_section(None)
            return

        manager.status_changed.connect(self._refresh_update_section)
        self._refresh_update_section(manager.status_message)
        self._refresh_local_environment()

    def _refresh_update_section(self, message: Optional[str]) -> None:
        manager = getattr(self.main_window, "update_manager", None)
        if self.update_current_version_label is not None:
            version = manager.current_version if manager is not None else "--"
            self.update_current_version_label.setText(f"Versão atual: {version}")

        if self.update_status_label is not None and message:
            self.update_status_label.setText(message)

        if self.update_state_heading is not None:
            state_title = "Status: aguardando verificação"
            if manager is not None:
                if getattr(manager, "_install_in_progress", False):
                    state_title = "Status: preparando atualização"
                elif manager.is_update_available():
                    state_title = "Status: atualização disponível"
                else:
                    state_title = "Status: ACCELA atualizado"
            self.update_state_heading.setText(state_title)

        if self.update_security_label is not None:
            security = (
                manager.get_security_summary()
                if manager is not None
                else "Assinatura: indisponível."
            )
            self.update_security_label.setText(security)

        if self.update_backup_label is not None:
            summary = (
                manager.get_backup_summary()
                if manager is not None
                else "Rollback: indisponível."
            )
            self.update_backup_label.setText(summary)

        if self.update_now_button is not None:
            update_available = manager.is_update_available() if manager is not None else False
            self.update_now_button.setEnabled(manager is not None and update_available)

        if self.update_rollback_button is not None:
            self.update_rollback_button.setEnabled(
                manager is not None and bool(manager.available_backups())
            )

    def _refresh_local_environment(self) -> None:
        if self.update_environment_label is None:
            return

        install_script = get_base_path() / "install.sh"
        if not install_script.exists():
            self.update_environment_label.setText(
                "Sistema: diagnóstico local indisponível até a próxima reinstalação."
            )
            return

        try:
            result = subprocess.run(
                ["bash", str(install_script), "--diagnose", "--json"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout).strip() or "falhou")

            data = json.loads(result.stdout)
            deps = data.get("missing_dependencies") or []
            deps_text = ", ".join(deps) if deps else "nenhuma"
            self.update_environment_label.setText(
                "Sistema detectado: "
                f"{data.get('system', '--')} | "
                f"Steam: {data.get('steam_mode', '--')} | "
                f"GPU: {data.get('gpu', '--')} | "
                f"Pendências: {deps_text} | "
                f"Modo recomendado: {data.get('recommended_mode', '--')}"
            )
        except Exception as exc:
            self.update_environment_label.setText(
                f"Sistema: não foi possível gerar o diagnóstico local ({exc})."
            )

    def _save_update_settings(self) -> None:
        self.settings.setValue(
            "github_updates_enabled",
            self.github_updates_checkbox.isChecked(),
        )
        self.settings.setValue(
            "github_auto_update",
            self.github_auto_update_checkbox.isChecked(),
        )
        self.settings.setValue(
            "github_updates_repo",
            self.github_repo_input.text().strip() or "Pedrohs1771/Accela-Compatible-Linux",
        )
        self.settings.setValue(
            "github_signed_updates_only",
            self.github_signed_updates_checkbox.isChecked(),
        )

    def accept(self) -> None:
        self._save_update_settings()
        if self.main_window and hasattr(self.main_window, "update_manager"):
            self.main_window.update_manager.reload_settings()
        super().accept()

    def _check_for_updates_now(self) -> None:
        manager = getattr(self.main_window, "update_manager", None)
        if manager is None:
            QMessageBox.warning(self, "Updates", "Gerenciador de updates indisponível.")
            return

        self._save_update_settings()
        manager.reload_settings()
        manager.check_for_updates_async(interactive=True)
        self._refresh_update_section("Verificando atualizações no GitHub...")

    def _install_update_now(self) -> None:
        manager = getattr(self.main_window, "update_manager", None)
        if manager is None:
            QMessageBox.warning(self, "Updates", "Gerenciador de updates indisponível.")
            return
        if not manager.latest_release:
            QMessageBox.information(
                self,
                "Updates",
                "Nenhuma atualização disponível no momento.",
            )
            return
        manager.install_update()

    def _enable_auto_update(self) -> None:
        self.github_auto_update_checkbox.setChecked(True)
        self._save_update_settings()
        QMessageBox.information(
            self,
            "Updates",
            "O ACCELA vai preparar a próxima atualização automaticamente quando a fila estiver ociosa.",
        )

    def _rollback_latest_backup(self) -> None:
        manager = getattr(self.main_window, "update_manager", None)
        if manager is None:
            QMessageBox.warning(self, "Updates", "Gerenciador de updates indisponível.")
            return

        if not manager.available_backups():
            QMessageBox.information(
                self,
                "Updates",
                "Nenhum backup disponível para rollback.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Rollback",
            "O ACCELA será fechado para restaurar o backup mais recente. Continuar?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        manager.rollback_to_latest_backup()
