import json
import logging
import os
import shutil
import subprocess
import sys
import webbrowser

from datetime import datetime
from typing import Any, Optional, Tuple

from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QColor, QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFileDialog,
    QFontDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from core import morrenus_api
from ui.dialogs.custom_gifs import CustomGifsDialog
from ui.dialogs.dialog_helpers import create_standard_buttons
from utils.helpers import (
    create_checkbox_setting,
    create_font_setting,
    create_slider_setting,
    get_base_path,
    get_slscheevo_path,
    get_slscheevo_save_path,
    get_venv_python,
)
from utils.paths import Paths
from utils.settings import get_settings
from utils.yaml_config_manager import is_slssteam_mode_enabled

logger = logging.getLogger(__name__)


class MorrenusStatsWidget(QWidget):
    """Widget displaying Morrenus API user statistics."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = get_settings()
        self.username_label = None
        self.daily_usage_bar = None
        self.expiration_label = None
        self.total_calls_label = None
        self.status_label = None
        self.refresh_button = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI components."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 5, 0, 5)

        # Row 1: Username
        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.username_label = QLabel("Usuário: --")
        self.username_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row1.addWidget(self.username_label)
        main_layout.addLayout(row1)

        # Progress Bar
        self.daily_usage_bar = QProgressBar()
        self.daily_usage_bar.setRange(0, 100)
        self.daily_usage_bar.setValue(0)
        self.daily_usage_bar.setFormat("Diário: --")
        self.daily_usage_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)

        accent_color = self.settings.value("accent_color", "#C06C84")
        self.daily_usage_bar.setStyleSheet(
            f"""
            QProgressBar {{
                border: 1px solid #444;
                border-radius: 0px;
                text-align: center;
                color: #fff;
                background-color: #222;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {accent_color};
            }}
        """
        )
        main_layout.addWidget(self.daily_usage_bar)

        # Row 2: Stats
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        self.expiration_label = QLabel("Expira em: --")
        self.expiration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.expiration_label)

        self.total_calls_label = QLabel("Total: --")
        self.total_calls_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.total_calls_label)

        self.status_label = QLabel("Status: --")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row2.addWidget(self.status_label)

        main_layout.addLayout(row2)

        # Refresh button
        self.refresh_button = QPushButton("Atualizar")
        self.refresh_button.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.refresh_button.clicked.connect(self.refresh_stats)
        main_layout.addWidget(self.refresh_button)

    def refresh_stats(self) -> None:
        """Fetch and display latest stats from the API."""
        self.refresh_button.setEnabled(False)
        self.refresh_button.setText("Carregando...")

        stats = morrenus_api.get_user_stats()

        self.refresh_button.setEnabled(True)
        self.refresh_button.setText("Atualizar")

        if stats.get("error"):
            self._display_error_state()
        else:
            self._display_stats(stats)

    def _display_error_state(self) -> None:
        """Update UI to show error state."""
        self.username_label.setText("Usuário: Erro")
        self.total_calls_label.setText("Total: --")
        self.daily_usage_bar.setFormat("Diário: Erro")
        self.daily_usage_bar.setValue(0)
        self.expiration_label.setText("Expira em: --")
        self.status_label.setText("Status: Erro")

    def _display_stats(self, stats: dict) -> None:
        """Update UI with fetched statistics."""
        self.username_label.setText(f"Usuário: {stats.get('username', 'Desconhecido')}")
        self.total_calls_label.setText(f"Total: {stats.get('api_key_usage_count', 0)}")

        daily_usage = MorrenusStatsWidget._parse_int(stats.get("daily_usage", 0))
        daily_limit = MorrenusStatsWidget._parse_int(stats.get("daily_limit", 100))
        if daily_limit == 0:
            daily_limit = 100

        self.daily_usage_bar.setRange(0, daily_limit)
        self.daily_usage_bar.setValue(daily_usage)
        self.daily_usage_bar.setFormat(f"Diário: {daily_usage}/{daily_limit}")

        self._update_expiration_label(stats.get("api_key_expires_at", ""))

        status = "Ativo" if stats.get("can_make_requests", False) else "Bloqueado"
        self.status_label.setText(f"Status: {status}")

    @staticmethod
    def _parse_int(value: Any, default: int = 0) -> int:
        """Safely parse an integer value."""
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    def _update_expiration_label(self, expires_at: str) -> None:
        """Format and update the expiration label."""
        if not expires_at:
            self.expiration_label.setText("Expira em: Nunca")
            return

        try:
            dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            self.expiration_label.setText(f"Expira em: {dt.strftime('%d/%m/%Y')}")
        except ValueError:
            self.expiration_label.setText(f"Expira em: {expires_at[:10]}")


class SettingsDialog(QDialog):
    """Dialog for configuring application settings."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Configurações")
        self.setMinimumWidth(860)
        self.setMinimumHeight(720)
        self.resize(920, 760)
        self.settings = get_settings()
        self.main_window = parent
        self.accent_color = self.settings.value("accent_color", "#C06C84")
        self.main_layout = None
        self.tab_widget = None
        self.library_mode_checkbox = None
        self.auto_skip_single_choice_checkbox = None
        self.max_downloads_spinbox = None
        self.steamless_checkbox = None
        self.achievements_checkbox = None
        self.auto_apply_goldberg_checkbox = None
        self.application_shortcuts_checkbox = None
        self.sls_mode_checkbox = None
        self.sls_config_management_checkbox = None
        self.prompt_steam_restart_checkbox = None
        self.start_minimized_checkbox = None
        self.autostart_checkbox = None
        self.close_to_tray_checkbox = None
        self.auto_close_with_steam_checkbox = None
        self.opencloudsave_enabled_checkbox = None
        self.opencloudsave_auto_upload_checkbox = None
        self.opencloudsave_sync_on_steam_exit_checkbox = None
        self.opencloudsave_remote_input = None
        self.opencloudsave_rclone_input = None
        self.discord_presence_checkbox = None
        self.discord_client_id_input = None
        self.discord_large_image_input = None
        self.discord_small_image_input = None
        self.github_updates_checkbox = None
        self.github_auto_update_checkbox = None
        self.github_signed_updates_checkbox = None
        self.github_repo_input = None
        self.update_status_label = None
        self.update_security_label = None
        self.update_backup_label = None
        self.update_environment_label = None
        self.update_current_version_label = None
        self.update_now_button = None
        self.update_rollback_button = None
        self.block_steam_updates_checkbox = None
        self.download_slssteam_button = None
        self.slssteam_status_label = None
        self.slssteam_hash_warning_label = None
        self.play_etw_checkbox = None
        self.play_lall_checkbox = None
        self.play_50hz_hum_checkbox = None
        self.test_etw_button = None
        self.test_lall_button = None
        self.accent_color_button = None
        self.accent_reset_button = None
        self.bg_color_button = None
        self.bg_reset_button = None
        self.titlebar_position_checkbox = None
        self.sonic_mode_checkbox = None
        self.gif_display_checkbox = None
        self.ignore_color_warnings_checkbox = None
        self.current_font = QFont()
        self.sgdb_api_key_input = None
        self.morrenus_stats_widget = None
        self.morrenus_tab_initialized = False

        # Save original API keys for restore on cancel
        self._original_morrenus_key = self.settings.value(
            "morrenus_api_key", "", type=str
        )
        self._original_sgdb_key = self.settings.value("sgdb_api_key", "", type=str)

        self._user_accent_color = self.settings.value(
            "user_accent_color",
            self.settings.value("accent_color", "#C06C84"),
            type=str,
        )
        self._user_background_color = self.settings.value(
            "user_background_color",
            self.settings.value("background_color", "#000000"),
            type=str,
        )
        self._original_titlebar_position = self.settings.value(
            "titlebar_position", "bottom", type=str
        )
        self._original_gif_display_enabled = self.settings.value(
            "gif_display_enabled", True, type=bool
        )

        logger.debug("Opening SettingsDialog.")
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        self._apply_dialog_readability_style()
        self.main_layout = QVBoxLayout(self)

        self._create_tab_widget()
        self._setup_tabs()
        self.main_layout.addWidget(self.tab_widget)

        # Sync audio preview values
        if self.main_window and hasattr(self.main_window, "audio_manager"):
            # noinspection PyUnresolvedReferences
            self.main_window.audio_manager.sync_preview_values_from_settings()

        self._create_dialog_buttons()

    def _create_tab_widget(self) -> None:
        """Create and style the tab widget."""
        self.tab_widget = QTabWidget()
        self.tab_widget.tabBar().setExpanding(False)
        bg_color = self.settings.value("background_color", "#1E1E1E")
        self.tab_widget.setStyleSheet(
            f"""
            QTabWidget::pane {{
                border: none;
            }}
            QTabBar::tab {{
                background: {bg_color};
                color: #888888;
                padding: 10px 16px;
                border: none;
                font-size: 13px;
                font-weight: 700;
            }}
            QTabBar::tab:selected {{
                color: {self.accent_color};
                border-bottom: 2px solid {self.accent_color};
            }}
            QTabBar::tab:!selected {{
                color: #888888;
            }}
        """
        )

    def _setup_tabs(self) -> None:
        """Initialize and add all settings tabs."""
        self._create_downloads_tab()
        self._create_morrenus_tab()
        self._create_steam_tab()
        self._create_automation_tab()
        self._create_opencloudsave_tab()
        self._create_discord_tab()
        self._create_tools_tab()
        self._create_audio_tab()
        self._create_style_tab()

    def _apply_dialog_readability_style(self) -> None:
        bg_color = self.settings.value("background_color", "#000000")
        accent_color = self.settings.value("accent_color", "#C06C84")
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {bg_color};
            }}
            QLabel, QCheckBox, QPushButton, QLineEdit, QSpinBox, QGroupBox {{
                font-size: 13px;
                font-family: "DejaVu Sans Mono";
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
                color: {accent_color};
                font-size: 14px;
                font-weight: 700;
            }}
            QLineEdit, QSpinBox {{
                min-height: 36px;
                padding: 6px 10px;
                border: 1px solid {accent_color};
                color: {accent_color};
                background-color: {bg_color};
                selection-background-color: {accent_color};
            }}
            QPushButton {{
                min-height: 36px;
                padding: 6px 12px;
            }}
            """
        )

    def _create_dialog_buttons(self) -> None:
        """Create standard Ok/Cancel buttons."""
        buttons = create_standard_buttons(self.accept, self.reject)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.main_layout.addWidget(buttons)

    def _create_api_key_setting(
        self,
        label: str,
        placeholder: str,
        setting_key: str,
        help_url: Optional[str] = None,
        help_text: Optional[str] = None,
    ) -> Tuple[QVBoxLayout, QLineEdit]:
        """Create an API key input field with password toggle and help link."""
        layout = QVBoxLayout()
        layout.setSpacing(5)

        layout.addWidget(QLabel(label))

        input_layout = QHBoxLayout()
        input_layout.setSpacing(5)

        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText(placeholder)
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        current_key = self.settings.value(setting_key, "", type=str)
        api_key_input.setText(current_key)

        toggle_btn = QPushButton("Mostrar")
        toggle_btn.clicked.connect(
            lambda: SettingsDialog._toggle_api_key_visibility(api_key_input, toggle_btn)
        )

        input_layout.addWidget(api_key_input)
        input_layout.addWidget(toggle_btn)
        layout.addLayout(input_layout)

        accent_color = self.settings.value("accent_color", "#C06C84")
        if help_url:
            help_label = QLabel(
                f'<a href="{help_url}" style="color: {accent_color};">Obter chave de API</a>'
            )
            help_label.setOpenExternalLinks(True)
            layout.addWidget(help_label)
        elif help_text:
            help_label = QLabel(help_text)
            help_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
            layout.addWidget(help_label)

        return layout, api_key_input

    @staticmethod
    def _toggle_api_key_visibility(
        input_field: QLineEdit, toggle_btn: QPushButton
    ) -> None:
        """Toggle API key visibility."""
        if input_field.echoMode() == QLineEdit.EchoMode.Password:
            input_field.setEchoMode(QLineEdit.EchoMode.Normal)
            toggle_btn.setText("Ocultar")
        else:
            input_field.setEchoMode(QLineEdit.EchoMode.Password)
            toggle_btn.setText("Mostrar")

    def _create_downloads_tab(self) -> None:
        """Create the Downloads settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Download Settings Group
        dl_group = QGroupBox("Configurações de download")
        dl_layout = QVBoxLayout()

        library_tooltip = "Detecta bibliotecas da Steam e permite escolher onde instalar os jogos."
        if sys.platform == "linux":
            library_tooltip += (
                " No Linux, isso também habilita a integração do SLSsteam para essas instalações."
            )

        self.library_mode_checkbox = create_checkbox_setting(
            "Limitar downloads às bibliotecas da Steam",
            "library_mode",
            sys.platform == "linux",
            self,
            library_tooltip,
        )
        dl_layout.addWidget(self.library_mode_checkbox)

        self.auto_skip_single_choice_checkbox = create_checkbox_setting(
            "Pular seleção quando houver opção única",
            "auto_skip_single_choice",
            False,
            self,
            "Pula automaticamente a seleção quando existir apenas uma opção.",
        )
        dl_layout.addWidget(self.auto_skip_single_choice_checkbox)

        # Max Downloads
        max_dl_layout = QHBoxLayout()
        max_dl_label = QLabel("Máximo de downloads simultâneos")
        max_dl_label.setToolTip("Define o máximo de downloads simultâneos (0-255)")

        self.max_downloads_spinbox = QSpinBox()
        self.max_downloads_spinbox.setRange(0, 255)
        current_max = self.settings.value("max_downloads", 255, type=int)
        self.max_downloads_spinbox.setValue(current_max)

        max_dl_layout.addWidget(max_dl_label)
        max_dl_layout.addWidget(self.max_downloads_spinbox)
        dl_layout.addLayout(max_dl_layout)

        dl_group.setLayout(dl_layout)
        layout.addWidget(dl_group)

        # Post-Processing Group
        pp_group = QGroupBox("Pós-processamento")
        pp_layout = QVBoxLayout()

        self.achievements_checkbox = create_checkbox_setting(
            "Gerar conquistas da Steam",
            "generate_achievements",
            False,
            self,
            "Gera arquivos de conquistas para seus jogos após os downloads.",
        )
        pp_layout.addWidget(self.achievements_checkbox)

        self.steamless_checkbox = create_checkbox_setting(
            "Remover DRM da Steam com Steamless",
            "use_steamless",
            False,
            self,
            "Remove DRM dos executáveis do jogo após o download.",
        )
        pp_layout.addWidget(self.steamless_checkbox)


        if sys.platform == "linux":
            self.application_shortcuts_checkbox = create_checkbox_setting(
                "Criar atalhos de aplicativo",
                "create_application_shortcuts",
                False,
                self,
                "Cria atalhos na área de trabalho e instala ícones do SteamGridDB.",
            )
            pp_layout.addWidget(self.application_shortcuts_checkbox)
        else:
            self.application_shortcuts_checkbox = None

        pp_group.setLayout(pp_layout)
        layout.addWidget(pp_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Downloads")

    def goldberg_checked_warning(self) -> None:
        """Warn when Goldberg is enabled alongside Steam integration."""
        checkbox = self.auto_apply_goldberg_checkbox
        if not checkbox.isChecked():
            return

        integration_enabled = (
            self.sls_mode_checkbox.isChecked()
            if self.sls_mode_checkbox is not None
            else is_slssteam_mode_enabled()
        )
        if not integration_enabled:
            return

        warning = "Você está prestes a ativar a integração com Goldberg, feita para jogar seus jogos baixados SEM a Steam. Se você pretende jogar pela Steam, mantenha isso desativado, caso contrário as coisas vão quebrar. Avisado. Continuar?"

        if self.goldberg_warning_box(checkbox, warning):
            return

    def goldberg_checked_warning_from_mode(self, type) -> None:
        """Warn when Steam integration is enabled while Goldberg is active."""
        checkbox = self.sls_mode_checkbox
        if not checkbox.isChecked():
            return
        try:
            if not self.auto_apply_goldberg_checkbox.isChecked():
                return
        except:
            if not self.settings.value("auto_apply_goldberg", False):
                return

        warning = f"Você está prestes a ativar a integração {type}, feita para jogar seus jogos baixados COM a Steam. Mas o Goldberg está ativado, e ele foi feito para jogar seus jogos SEM a Steam. Se você pretende jogar pela Steam, desative o Goldberg nas configurações."

        if self.goldberg_warning_box(checkbox, warning):
            return

    def goldberg_warning_box(self, checkbox, warning) -> bool:
        # First
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Aviso")
        msg_box.setText(warning)
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)
        reply = msg_box.exec()

        if reply == QMessageBox.StandardButton.No:
            checkbox.setChecked(False)
            checkbox.checkbox.setCheckState(Qt.CheckState.Unchecked)
            return True

        # Second
        confirm_box = QMessageBox(self)
        confirm_box.setWindowTitle("Aviso")
        confirm_box.setText(warning + " \n\nTem certeza?")
        confirm_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirm_box.setDefaultButton(QMessageBox.StandardButton.No)
        second_reply = confirm_box.exec()

        if second_reply == QMessageBox.StandardButton.No:
            checkbox.setChecked(False)
            checkbox.checkbox.setCheckState(Qt.CheckState.Unchecked)
            return True

        return False

    def _create_morrenus_tab(self) -> None:
        """Create the Morrenus API settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # API Keys Group
        key_group = QGroupBox("Chaves de API")
        key_layout = QVBoxLayout()
        key_layout.setSpacing(10)

        morrenus_layout, self.api_key_input = self._create_api_key_setting(
            "Chave da API Hubcap:",
            "Cole sua chave da API Hubcap",
            "morrenus_api_key",
            help_url="https://hubcapmanifest.com/",
        )
        key_layout.addLayout(morrenus_layout)

        if sys.platform == "linux":
            sgdb_layout, self.sgdb_api_key_input = self._create_api_key_setting(
                "Chave da API SteamGridDB:",
                "Cole sua chave da API SteamGridDB",
                "sgdb_api_key",
                help_url="https://www.steamgriddb.com/profile/account",
            )
            key_layout.addLayout(sgdb_layout)
        else:
            self.sgdb_api_key_input = None

        key_group.setLayout(key_layout)
        layout.addWidget(key_group)

        # Stats Group
        stats_group = QGroupBox("Estatísticas da Hubcap")
        stats_layout = QVBoxLayout()
        stats_layout.setContentsMargins(5, 10, 5, 10)

        self.morrenus_stats_widget = MorrenusStatsWidget()
        stats_layout.addWidget(self.morrenus_stats_widget)

        stats_group.setLayout(stats_layout)
        layout.addWidget(stats_group)

        layout.addStretch()

        # Connect tab change for lazy loading stats
        self.morrenus_tab_initialized = False
        self.tab_widget.currentChanged.connect(self._on_tab_changed)

        self.tab_widget.addTab(tab, "Integrações")

    def _on_tab_changed(self, index: int) -> None:
        """Handle tab change events."""
        if (
            self.tab_widget.tabText(index) == "Integrações"
            and not self.morrenus_tab_initialized
        ):
            self.morrenus_tab_initialized = True
            QTimer.singleShot(100, self.morrenus_stats_widget.refresh_stats)

    def _create_steam_tab(self) -> None:
        """Create the Steam settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Integration Group
        int_group = QGroupBox("Integração com Steam")
        int_layout = QVBoxLayout()

        if sys.platform == "linux":
            wrapper_name = "SLSsteam"
            self.sls_mode_checkbox = None
            linux_hint = QLabel(
                "O SLSsteam é habilitado automaticamente para instalações em bibliotecas da Steam no Linux."
            )
            linux_hint.setWordWrap(True)
            int_layout.addWidget(linux_hint)
        else:
            wrapper_name = "GreenLuma"
            wrapper_full = "Modo wrapper GreenLuma"
            tooltip = (
                "Integra jogos com a Steam usando GreenLuma.\n"
                "Os jogos aparecem automaticamente na sua biblioteca da Steam."
            )
            self.sls_mode_checkbox = create_checkbox_setting(
                wrapper_full, "slssteam_mode", False, self, tooltip
            )
            self.sls_mode_checkbox.stateChanged.connect(
                lambda: self.goldberg_checked_warning_from_mode(wrapper_name)
            )
            int_layout.addWidget(self.sls_mode_checkbox)

        self.sls_config_management_checkbox = create_checkbox_setting(
            f"Gerenciamento de configuração do {wrapper_name}",
            "sls_config_management",
            True,
            self,
            f"Permite que o ACCELA gerencie os arquivos de configuração do {wrapper_name}.",
        )
        int_layout.addWidget(self.sls_config_management_checkbox)

        int_group.setLayout(int_layout)
        layout.addWidget(int_group)

        # Settings Group
        settings_group = QGroupBox("Configurações da Steam")
        settings_layout = QVBoxLayout()

        self.prompt_steam_restart_checkbox = create_checkbox_setting(
            "Pedir reinício da Steam",
            "prompt_steam_restart",
            True,
            self,
            "Exibe um aviso para reiniciar a Steam após downloads integrados a ela.",
        )
        settings_layout.addWidget(self.prompt_steam_restart_checkbox)


        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Steam")

    def _create_tools_tab(self) -> None:
        """Create the Tools settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Tools Group
        tools_group = QGroupBox("Ferramentas")
        tools_layout = QVBoxLayout()

        SettingsDialog._add_tool_button(
            tools_layout,
            "Configurar conquistas",
            "Abre o SLScheevo para configurar as credenciais de conquistas.",
            self.run_slscheevo,
        )

        SettingsDialog._add_tool_button(
            tools_layout,
            "Remover DRM",
            "Executa o Steamless manualmente em um .exe de jogo.",
            self.run_steamless_manually,
        )

        self.download_slssteam_button = QPushButton("Instalar/atualizar SLSsteam")
        self.download_slssteam_button.setToolTip(
            "Baixa e instala a release oficial mais recente do SLSsteam."
        )
        self.download_slssteam_button.clicked.connect(self.download_slssteam)
        tools_layout.addWidget(self.download_slssteam_button)
        SettingsDialog._add_tool_explanation(
            tools_layout,
            "Instala automaticamente o SLSsteam em ~/.local/share/SLSsteam usando a release oficial.",
        )

        tools_group.setLayout(tools_layout)
        layout.addWidget(tools_group)

        # Windows Registry Group
        if sys.platform == "win32":
            reg_group = QGroupBox("Windows Registry")
            reg_layout = QVBoxLayout()

            SettingsDialog._add_tool_button(
                reg_layout,
                "Register Registry Entries",
                "Register accela:// URL protocol and .zip context menu entries.",
                SettingsDialog.register_registry_entries,
            )

            SettingsDialog._add_tool_button(
                reg_layout,
                "Remove Registry Entries",
                "Remove accela:// URL protocol and .zip context menu entries.",
                SettingsDialog.remove_registry_entries,
            )

            reg_group.setLayout(reg_layout)
            layout.addWidget(reg_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Ferramentas")

    def _create_automation_tab(self) -> None:
        """Create the automation settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        startup_group = QGroupBox("Inicialização e fechamento")
        startup_layout = QVBoxLayout()

        self.start_minimized_checkbox = create_checkbox_setting(
            "Abrir minimizado na bandeja",
            "start_minimized_to_tray",
            True,
            self,
            "Inicia o ACCELA escondido na bandeja do sistema quando aberto com --start-hidden ou pelo autostart.",
        )
        startup_layout.addWidget(self.start_minimized_checkbox)

        self.autostart_checkbox = create_checkbox_setting(
            "Abrir junto com o Arch Linux",
            "autostart_on_login",
            False,
            self,
            "Cria um .desktop em ~/.config/autostart para iniciar o launcher com a sessão.",
        )
        startup_layout.addWidget(self.autostart_checkbox)

        self.close_to_tray_checkbox = create_checkbox_setting(
            "Fechar para a bandeja",
            "close_to_tray",
            True,
            self,
            "Ao clicar em fechar, mantém o ACCELA em segundo plano na bandeja.",
        )
        startup_layout.addWidget(self.close_to_tray_checkbox)

        self.auto_close_with_steam_checkbox = create_checkbox_setting(
            "Fechar ACCELA quando a Steam fechar",
            "auto_close_with_steam",
            False,
            self,
            "Monitora a Steam e encerra o ACCELA automaticamente para economizar RAM.",
        )
        startup_layout.addWidget(self.auto_close_with_steam_checkbox)

        startup_group.setLayout(startup_layout)
        layout.addWidget(startup_group)

        hint = QLabel(
            "Modo stealth usa a bandeja do sistema. Se seu ambiente não expor tray, o ACCELA apenas iniciará minimizado."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        layout.addWidget(hint)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Automação")

    def _create_opencloudsave_tab(self) -> None:
        """Create the OpenCloudSave settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        main_group = QGroupBox("OpenCloudSave")
        main_layout = QVBoxLayout()

        self.opencloudsave_enabled_checkbox = create_checkbox_setting(
            "Ativar OpenCloudSave",
            "opencloudsave_enabled",
            False,
            self,
            "Usa rclone para sincronizar saves do Proton/Steam Cloud com sua nuvem pessoal.",
        )
        main_layout.addWidget(self.opencloudsave_enabled_checkbox)

        remote_layout = QVBoxLayout()
        remote_layout.addWidget(QLabel("Remoto rclone"))
        self.opencloudsave_remote_input = QLineEdit()
        self.opencloudsave_remote_input.setPlaceholderText(
            "Exemplo: meudrive:ACCELA-Saves"
        )
        self.opencloudsave_remote_input.setText(
            self.settings.value("opencloudsave_remote", "", type=str)
        )
        remote_layout.addWidget(self.opencloudsave_remote_input)
        SettingsDialog._add_tool_explanation(
            remote_layout,
            "Pode ser Google Drive, OneDrive ou qualquer outro backend configurado no rclone.",
        )
        main_layout.addLayout(remote_layout)

        binary_layout = QVBoxLayout()
        binary_layout.addWidget(QLabel("Binário do rclone"))
        self.opencloudsave_rclone_input = QLineEdit()
        self.opencloudsave_rclone_input.setPlaceholderText(
            "Deixe em branco para usar o rclone do sistema ou o binário embutido."
        )
        self.opencloudsave_rclone_input.setText(
            self.settings.value("opencloudsave_rclone_binary", "", type=str)
        )
        binary_layout.addWidget(self.opencloudsave_rclone_input)
        main_layout.addLayout(binary_layout)

        self.opencloudsave_auto_upload_checkbox = create_checkbox_setting(
            "Enviar saves automaticamente após mudanças",
            "opencloudsave_auto_upload",
            True,
            self,
            "Monitora mudanças nos saves e envia quando os arquivos estabilizam.",
        )
        main_layout.addWidget(self.opencloudsave_auto_upload_checkbox)

        self.opencloudsave_sync_on_steam_exit_checkbox = create_checkbox_setting(
            "Sincronizar tudo quando a Steam fechar",
            "opencloudsave_auto_sync_on_steam_exit",
            True,
            self,
            "Antes do auto-close, faz um último upload dos jogos configurados.",
        )
        main_layout.addWidget(self.opencloudsave_sync_on_steam_exit_checkbox)

        test_btn = QPushButton("Testar rclone")
        test_btn.clicked.connect(self.test_rclone_setup)
        main_layout.addWidget(test_btn)

        main_group.setLayout(main_layout)
        layout.addWidget(main_group)

        hint = QLabel(
            "Os caminhos de save por jogo são configurados na Biblioteca do ACCELA, dentro da aba OpenCloudSave de cada jogo."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        layout.addWidget(hint)

        layout.addStretch()
        self.tab_widget.addTab(tab, "OpenCloudSave")

    def _create_discord_tab(self) -> None:
        """Create the Discord Rich Presence settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        rpc_group = QGroupBox("Discord Rich Presence")
        rpc_layout = QVBoxLayout()

        self.discord_presence_checkbox = create_checkbox_setting(
            "Ativar Rich Presence do ACCELA",
            "discord_presence_enabled",
            False,
            self,
            "Atualiza o Discord em tempo real com status do launcher, downloads e biblioteca.",
        )
        rpc_layout.addWidget(self.discord_presence_checkbox)

        self.discord_client_id_input = QLineEdit()
        self.discord_client_id_input.setPlaceholderText("Discord Application Client ID")
        self.discord_client_id_input.setText(
            self.settings.value("discord_presence_client_id", "", type=str)
        )
        rpc_layout.addWidget(QLabel("Client ID do Discord"))
        rpc_layout.addWidget(self.discord_client_id_input)

        self.discord_large_image_input = QLineEdit()
        self.discord_large_image_input.setPlaceholderText("Asset key da imagem principal")
        self.discord_large_image_input.setText(
            self.settings.value("discord_presence_large_image", "", type=str)
        )
        rpc_layout.addWidget(QLabel("Imagem principal"))
        rpc_layout.addWidget(self.discord_large_image_input)

        self.discord_small_image_input = QLineEdit()
        self.discord_small_image_input.setPlaceholderText("Asset key da imagem secundária")
        self.discord_small_image_input.setText(
            self.settings.value("discord_presence_small_image", "", type=str)
        )
        rpc_layout.addWidget(QLabel("Imagem secundária"))
        rpc_layout.addWidget(self.discord_small_image_input)

        SettingsDialog._add_tool_explanation(
            rpc_layout,
            "O Discord não aceita GIF bruto no Rich Presence. Use assets de imagem enviados na sua aplicação do Discord com a arte do ACCELA.",
        )

        rpc_group.setLayout(rpc_layout)
        layout.addWidget(rpc_group)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Discord")

    def _create_updates_tab(self) -> None:
        """Create the GitHub updates tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        updates_group = QGroupBox("Atualizações pelo GitHub")
        updates_layout = QVBoxLayout()

        self.update_current_version_label = QLabel("Versão atual: --")
        updates_layout.addWidget(self.update_current_version_label)

        self.update_environment_label = QLabel("Sistema: analisando ambiente local...")
        self.update_environment_label.setWordWrap(True)
        self.update_environment_label.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        updates_layout.addWidget(self.update_environment_label)

        updates_layout.addWidget(QLabel("Repositório"))
        self.github_repo_input = QLineEdit()
        self.github_repo_input.setText(
            self.settings.value(
                "github_updates_repo",
                "Pedrohs1771/Accela-Compatible-Linux",
                type=str,
            )
        )
        self.github_repo_input.setPlaceholderText("usuario/repositorio")
        updates_layout.addWidget(self.github_repo_input)

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

        check_button = QPushButton("Verificar agora")
        check_button.clicked.connect(self._check_for_updates_now)
        buttons_layout.addWidget(check_button)

        self.update_now_button = QPushButton("Atualizar agora")
        self.update_now_button.clicked.connect(self._install_update_now)
        self.update_now_button.setEnabled(False)
        buttons_layout.addWidget(self.update_now_button)

        self.update_rollback_button = QPushButton("Voltar backup")
        self.update_rollback_button.clicked.connect(self._rollback_latest_backup)
        self.update_rollback_button.setEnabled(False)
        buttons_layout.addWidget(self.update_rollback_button)

        updates_layout.addLayout(buttons_layout)
        updates_group.setLayout(updates_layout)
        layout.addWidget(updates_group)
        layout.addStretch()
        self.tab_widget.addTab(tab, "Updates")
        self._wire_update_manager()

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
            update_available = False
            if manager is not None and manager.latest_release is not None:
                latest_revision = str(
                    manager.latest_release.get("commit_sha", "")
                ).strip()
                update_available = (
                    bool(latest_revision)
                    and latest_revision != manager.get_installed_revision()
                )
            self.update_now_button.setEnabled(
                manager is not None and update_available
            )

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

    @staticmethod
    def _add_tool_button(layout: QVBoxLayout, text: str, tooltip: str, slot) -> None:
        """Helper to add a tool button with explanation text."""
        btn = QPushButton(text)
        btn.setToolTip(tooltip)
        btn.clicked.connect(slot)
        layout.addWidget(btn)
        SettingsDialog._add_tool_explanation(layout, tooltip)

    @staticmethod
    def _add_tool_explanation(layout: QVBoxLayout, text: str) -> None:
        """Helper to add explanation label."""
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)

    def _create_audio_tab(self) -> None:
        """Create the Audio settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

    def _create_style_tab(self) -> None:
        """Create the Style settings tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(15, 15, 15, 15)

        # Color Group
        color_group = QGroupBox("Configurações de cor")
        color_layout = QVBoxLayout()

        # Accent
        acc_layout = QHBoxLayout()
        self.accent_color_button = QPushButton()
        self.accent_color_button.setStyleSheet(
            f"background-color: {self._user_accent_color};"
        )
        self.accent_reset_button = QPushButton("Redefinir")
        acc_layout.addWidget(QLabel("Cor de destaque:"))
        acc_layout.addWidget(self.accent_color_button)
        acc_layout.addWidget(self.accent_reset_button)
        acc_layout.addStretch()
        self.accent_color_button.clicked.connect(self.choose_accent_color)
        self.accent_reset_button.clicked.connect(self.reset_accent_color)
        color_layout.addLayout(acc_layout)

        # Background
        bg_layout = QHBoxLayout()
        self.bg_color_button = QPushButton()
        self.bg_color_button.setStyleSheet(
            f"background-color: {self._user_background_color};"
        )
        self.bg_reset_button = QPushButton("Redefinir")
        bg_layout.addWidget(QLabel("Cor de fundo:"))
        bg_layout.addWidget(self.bg_color_button)
        bg_layout.addWidget(self.bg_reset_button)
        bg_layout.addStretch()
        self.bg_color_button.clicked.connect(self.choose_bg_color)
        self.bg_reset_button.clicked.connect(self.reset_bg_color)
        color_layout.addLayout(bg_layout)

        color_group.setLayout(color_layout)
        layout.addWidget(color_group)

        # Font Group
        font_group = QGroupBox("Configurações de fonte")
        font_layout = QVBoxLayout()
        font_children, self.font_button, self.font_reset_button = create_font_setting(
            self
        )
        self.font_button.clicked.connect(self.choose_font)
        self.font_reset_button.clicked.connect(self.reset_font)
        font_layout.addLayout(font_children)
        font_group.setLayout(font_layout)
        layout.addWidget(font_group)

        # Display Group
        disp_group = QGroupBox("Configurações de exibição")
        disp_layout = QVBoxLayout()

        self.titlebar_position_checkbox = QCheckBox("Mover barra de título para cima")
        is_top = self.settings.value("titlebar_position", "bottom", type=str) == "top"
        self.titlebar_position_checkbox.setChecked(is_top)
        self.titlebar_position_checkbox.setToolTip("Move a barra de título para a parte superior.")
        self.titlebar_position_checkbox.stateChanged.connect(
            self.on_titlebar_position_changed
        )
        disp_layout.addWidget(self.titlebar_position_checkbox)
        SettingsDialog._add_checkbox_explanation(
            disp_layout, "Move a barra de título para a parte superior da janela."
        )

        self.gif_display_checkbox = create_checkbox_setting(
            "Mostrar área de GIF",
            "gif_display_enabled",
            True,
            self,
            "Mostra o GIF animado na janela principal.",
        )
        self.gif_display_checkbox.stateChanged.connect(self.on_gif_display_changed)
        disp_layout.addWidget(self.gif_display_checkbox)

        self.ignore_color_warnings_checkbox = create_checkbox_setting(
            "Ignorar avisos de cor",
            "ignore_color_warnings",
            False,
            self,
            "Permite qualquer combinação de cores.",
        )
        disp_layout.addWidget(self.ignore_color_warnings_checkbox)

        disp_group.setLayout(disp_layout)
        layout.addWidget(disp_group)

        # Custom GIFs
        gif_layout = QHBoxLayout()
        custom_gifs_btn = QPushButton("GIFs personalizados")
        custom_gifs_btn.clicked.connect(self.open_custom_gifs_dialog)
        gif_layout.addWidget(custom_gifs_btn)

        clear_cache_btn = QPushButton("Limpar cache de GIFs")
        clear_cache_btn.clicked.connect(self.clear_gif_cache)
        clear_cache_btn.setToolTip("Regenera todos os GIFs.")
        gif_layout.addWidget(clear_cache_btn)
        layout.addLayout(gif_layout)

        layout.addStretch()
        self.tab_widget.addTab(tab, "Estilo")

    @staticmethod
    def _add_checkbox_explanation(layout: QVBoxLayout, text: str) -> None:
        """Add indented explanation text for checkboxes."""
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #A6A6A6; font-size: 13px;")
        lbl.setWordWrap(True)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.addSpacing(14)
        h_layout.addWidget(lbl)
        layout.addLayout(h_layout)

    # Color Handlers
    def choose_accent_color(self) -> None:
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        if (
            not self.ignore_color_warnings_checkbox.isChecked()
            and SettingsDialog._is_too_dark(color)
        ):
            SettingsDialog._show_color_warning()
            return
        hex_c = color.name()
        self.accent_color_button.setStyleSheet(f"background-color: {hex_c};")

    def reset_accent_color(self) -> None:
        default = "#C06C84"
        self.settings.setValue("accent_color", default)
        self.accent_color_button.setStyleSheet(f"background-color: {default};")

    def choose_bg_color(self) -> None:
        color = QColorDialog.getColor()
        if not color.isValid():
            return
        hex_c = color.name()
        self.bg_color_button.setStyleSheet(f"background-color: {hex_c};")

    def reset_bg_color(self) -> None:
        default = "#000000"
        self.settings.setValue("background_color", default)
        self.bg_color_button.setStyleSheet(f"background-color: {default};")

    @staticmethod
    def _is_too_dark(color: QColor) -> bool:
        brightness = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        return brightness < 15

    @staticmethod
    def _is_too_close(accent: QColor, bg: QColor, threshold: int = 100) -> bool:
        r_diff = bg.red() - accent.red()
        g_diff = bg.green() - accent.green()
        b_diff = bg.blue() - accent.blue()
        return (r_diff**2 + g_diff**2 + b_diff**2) ** 0.5 < threshold

    @staticmethod
    def _show_color_warning() -> None:
        QMessageBox.warning(
            None,
            "Cor inválida",
            "Essa cor é escura demais e deixará a interface inutilizável.",
        )

    # Font Handlers
    def choose_font(self) -> None:
        font, ok = QFontDialog.getFont(self.current_font, self)
        if ok:
            self.current_font = font
            self.update_font_button_text()

    def reset_font(self) -> None:
        default = QFont("TrixieCyrG-Plain", 10)
        default.setBold(False)
        default.setItalic(False)
        self.current_font = default
        self.update_font_button_text()

    def update_font_button_text(self) -> None:
        if hasattr(self, "font_button") and hasattr(self, "current_font"):
            fam = self.current_font.family()
            size = self.current_font.pointSize()
            text = f"{fam} {size}pt"
            if self.current_font.bold():
                text += " Bold"
            if self.current_font.italic():
                text += " Italic"
            self.font_button.setText(text)
            self.font_button.setFont(self.current_font)

    # Display Handlers
    def on_titlebar_position_changed(self, state: int) -> None:
        pos = "top" if state == 2 else "bottom"
        self.settings.setValue("titlebar_position", pos)
        if self.main_window and hasattr(self.main_window, "reposition_titlebar"):
            # noinspection PyUnresolvedReferences
            self.main_window.reposition_titlebar(pos)

    def on_gif_display_changed(self, state: int) -> None:
        enabled = state == 2
        self.settings.setValue("gif_display_enabled", enabled)
        if self.main_window and hasattr(self.main_window, "update_gif_display"):
            # noinspection PyUnresolvedReferences
            self.main_window.update_gif_display(enabled)

    def accept(self) -> None:
        """Save all settings and close."""
        self._save_general_settings()
        self._save_download_settings()
        self._save_automation_settings()
        self._save_opencloudsave_settings()
        self._save_discord_settings()
        if not self._save_style_settings():
            return  # Style validation failed
        if self.main_window and hasattr(self.main_window, "system_integration"):
            self.main_window.system_integration.reload_settings()
        if self.main_window and hasattr(self.main_window, "cloud_save_manager"):
            self.main_window.cloud_save_manager.reload_settings()
        if self.main_window and hasattr(self.main_window, "discord_presence_manager"):
            self.main_window.discord_presence_manager.reload_settings()
        if self.main_window and hasattr(self.main_window, "update_manager"):
            self.main_window.update_manager.reload_settings()
        logger.info("All settings saved.")
        super().accept()

    def _save_general_settings(self) -> None:
        api_key = self.api_key_input.text().strip()
        self.settings.setValue("morrenus_api_key", api_key)
        if self.sgdb_api_key_input:
            sgdb_key = self.sgdb_api_key_input.text().strip()
            self.settings.setValue("sgdb_api_key", sgdb_key)

    def _save_download_settings(self) -> None:
        if self.sls_mode_checkbox is not None:
            self.settings.setValue("slssteam_mode", self.sls_mode_checkbox.isChecked())
        self.settings.setValue(
            "sls_config_management",
            self.sls_config_management_checkbox.isChecked(),
        )
        self.settings.setValue("library_mode", self.library_mode_checkbox.isChecked())
        self.settings.setValue(
            "auto_skip_single_choice",
            self.auto_skip_single_choice_checkbox.isChecked(),
        )
        self.settings.setValue(
            "prompt_steam_restart",
            self.prompt_steam_restart_checkbox.isChecked(),
        )
        self.settings.setValue(
            "generate_achievements", self.achievements_checkbox.isChecked()
        )
        self.settings.setValue(
            "use_steamless", self.steamless_checkbox.isChecked()
        )

        if self.application_shortcuts_checkbox:
            self.settings.setValue(
                "create_application_shortcuts",
                self.application_shortcuts_checkbox.isChecked(),
            )

        val = 255
        if hasattr(self, "max_downloads_spinbox"):
            try:
                val = max(0, min(255, int(self.max_downloads_spinbox.value())))
            except (ValueError, TypeError):
                pass
        self.settings.setValue("max_downloads", val)

    def _save_automation_settings(self) -> None:
        self.settings.setValue(
            "start_minimized_to_tray", self.start_minimized_checkbox.isChecked()
        )
        self.settings.setValue("autostart_on_login", self.autostart_checkbox.isChecked())
        self.settings.setValue("close_to_tray", self.close_to_tray_checkbox.isChecked())
        self.settings.setValue(
            "auto_close_with_steam",
            self.auto_close_with_steam_checkbox.isChecked(),
        )

    def _save_opencloudsave_settings(self) -> None:
        self.settings.setValue(
            "opencloudsave_enabled",
            self.opencloudsave_enabled_checkbox.isChecked(),
        )
        self.settings.setValue(
            "opencloudsave_remote",
            self.opencloudsave_remote_input.text().strip(),
        )
        self.settings.setValue(
            "opencloudsave_rclone_binary",
            self.opencloudsave_rclone_input.text().strip(),
        )
        self.settings.setValue(
            "opencloudsave_auto_upload",
            self.opencloudsave_auto_upload_checkbox.isChecked(),
        )
        self.settings.setValue(
            "opencloudsave_auto_sync_on_steam_exit",
            self.opencloudsave_sync_on_steam_exit_checkbox.isChecked(),
        )

    def _save_discord_settings(self) -> None:
        self.settings.setValue(
            "discord_presence_enabled",
            self.discord_presence_checkbox.isChecked(),
        )
        self.settings.setValue(
            "discord_presence_client_id",
            self.discord_client_id_input.text().strip(),
        )
        self.settings.setValue(
            "discord_presence_large_image",
            self.discord_large_image_input.text().strip(),
        )
        self.settings.setValue(
            "discord_presence_small_image",
            self.discord_small_image_input.text().strip(),
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

    def _save_audio_settings(self) -> None:
        self.settings.setValue("play_etw", self.play_etw_checkbox.isChecked())
        self.settings.setValue("play_lall", self.play_lall_checkbox.isChecked())
        self.settings.setValue("play_50hz_hum", self.play_50hz_hum_checkbox.isChecked())
        self.settings.setValue("master_volume", self.master_volume_slider.value())
        self.settings.setValue("effects_volume", self.effects_volume_slider.value())
        self.settings.setValue("hum_volume", self.hum_volume_slider.value())
        if self.main_window and hasattr(self.main_window, "audio_manager"):
            # noinspection PyUnresolvedReferences
            self.main_window.audio_manager.apply_audio_settings()

    def _save_style_settings(self) -> bool:
        acc_s = self.accent_color_button.styleSheet()
        bg_s = self.bg_color_button.styleSheet()
        u_accent = acc_s.split("background-color: ")[1].split(";")[0]
        u_bg = bg_s.split("background-color: ")[1].split(";")[0]

        self.settings.setValue("user_accent_color", u_accent)
        self.settings.setValue("user_background_color", u_bg)

        prev_mode = self.settings.value("ui_mode", "default")
        applied_accent = u_accent
        applied_bg = u_bg
        self.settings.setValue("font-file", "")

        ignore = self.ignore_color_warnings_checkbox.isChecked()
        self.settings.setValue("ignore_color_warnings", ignore)
        if SettingsDialog._is_too_close(QColor(u_accent), QColor(u_bg)):
                QMessageBox.warning(
                    self,
                    "Cor inválida",
                    "A cor de fundo está muito parecida com a cor de destaque.",
                )
                return False

        self.settings.setValue("accent_color", applied_accent)
        self.settings.setValue("background_color", applied_bg)

        self.settings.setValue("font", self.current_font.family())
        self.settings.setValue("font-size", self.current_font.pointSize())

        style = "Normal"
        if self.current_font.bold():
            style = "Bold"
        if self.current_font.italic():
            style = "Italic"
        if self.current_font.bold() and self.current_font.italic():
            style = "Bold Italic"
        self.settings.setValue("font-style", style)

        if self.main_window and hasattr(self.main_window, "ui_state"):
            # noinspection PyUnresolvedReferences
            self.main_window.ui_state.apply_style_settings()

        return True

    def reject(self) -> None:
        """Revert settings on cancel."""
        self.settings.setValue("morrenus_api_key", self._original_morrenus_key)
        if self.sgdb_api_key_input:
            self.settings.setValue("sgdb_api_key", self._original_sgdb_key)

        # Revert live-previewed settings that were saved immediately
        self.settings.setValue("titlebar_position", self._original_titlebar_position)
        if self.main_window and hasattr(self.main_window, "reposition_titlebar"):
            # noinspection PyUnresolvedReferences
            self.main_window.reposition_titlebar(self._original_titlebar_position)

        self.settings.setValue(
            "gif_display_enabled", self._original_gif_display_enabled
        )
        if self.main_window and hasattr(self.main_window, "update_gif_display"):
            # noinspection PyUnresolvedReferences
            self.main_window.update_gif_display(self._original_gif_display_enabled)

        if self.main_window and hasattr(self.main_window, "audio_manager"):
            # noinspection PyUnresolvedReferences
            self.main_window.audio_manager.apply_audio_settings()
        super().reject()

    def test_rclone_setup(self) -> None:
        if not self.main_window or not hasattr(self.main_window, "cloud_save_manager"):
            QMessageBox.warning(self, "Erro", "OpenCloudSave indisponível nesta sessão.")
            return

        settings = self.main_window.cloud_save_manager
        rclone_binary = (
            self.opencloudsave_rclone_input.text().strip()
            or settings.get_rclone_binary()
        )
        if not rclone_binary or not os.path.exists(rclone_binary):
            QMessageBox.warning(
                self,
                "rclone ausente",
                "Não encontrei o binário do rclone. Defina o caminho manualmente.",
            )
            return

        remote = self.opencloudsave_remote_input.text().strip()
        if not remote:
            QMessageBox.warning(
                self,
                "Remoto ausente",
                "Defina um remoto rclone, por exemplo: meudrive:ACCELA-Saves",
            )
            return

        try:
            result = subprocess.run(
                [rclone_binary, "lsd", remote],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                QMessageBox.information(
                    self,
                    "OpenCloudSave",
                    "rclone respondeu corretamente. A base da nuvem está pronta.",
                )
            else:
                err = (result.stderr or result.stdout or "").strip()
                QMessageBox.warning(
                    self,
                    "Falha no rclone",
                    err or "Não foi possível validar o remoto informado.",
                )
        except (OSError, subprocess.SubprocessError) as exc:
            QMessageBox.warning(self, "Falha no rclone", str(exc))

    @staticmethod
    def _is_steam_updates_blocked() -> bool:
        """Check if steam.cfg exists."""
        try:
            from core.steam_helpers import find_steam_install

            path = find_steam_install()
            if not path:
                return False
            return os.path.exists(os.path.join(path, "steam.cfg"))
        except ImportError:
            return False

    @staticmethod
    def _apply_steam_updates_block(enabled: bool) -> None:
        """Manage steam.cfg file."""
        try:
            from core.steam_helpers import find_steam_install

            path = find_steam_install()
            if not path:
                logger.warning("Steam not found, skipping steam.cfg")
                return

            dest = os.path.join(path, "steam.cfg")
            src = Paths.deps("steam.cfg")

            if enabled:
                if not src.exists():
                    logger.error(f"Source steam.cfg missing: {src}")
                    return
                shutil.copy2(str(src), dest)
                logger.info(f"Copied steam.cfg to {dest}")
            elif os.path.exists(dest):
                os.remove(dest)
                logger.info(f"Removed steam.cfg from {dest}")

        except (ImportError, IOError) as e:
            logger.error(f"Failed to apply steam.cfg: {e}", exc_info=True)

    def _update_slssteam_status(self) -> None:
        """Check status update in background."""
        from core.tasks.download_slssteam_task import DownloadSLSsteamTask

        vf = DownloadSLSsteamTask.version_file()
        if not vf.exists():
            self._set_label_viz("slssteam_status_label", False)
            self._set_label_viz("slssteam_hash_warning_label", False)
            return

        self._set_label_viz("slssteam_status_label", True)
        self._set_label_viz("slssteam_hash_warning_label", True)

        import threading

        def check() -> None:
            st = DownloadSLSsteamTask.check_update_available()
            if hasattr(self, "slssteam_status_label"):
                self.slssteam_status_label.setText(
                    SettingsDialog._format_status_text(st)
                )
            if hasattr(self, "slssteam_hash_warning_label"):
                self._update_slssteam_hash_warning(st)

        threading.Thread(target=check, daemon=True).start()

    def _set_label_viz(self, name: str, viz: bool) -> None:
        if hasattr(self, name):
            getattr(self, name).setVisible(viz)

    def _update_slssteam_hash_warning(self, status: dict) -> None:
        """Update hash warning text."""
        if not hasattr(self, "slssteam_hash_warning_label"):
            return

        lbl = self.slssteam_hash_warning_label
        mis = status.get("steamclient_mismatch")
        fnd = status.get("steamclient_found")
        err = status.get("steamclient_error")
        pink = "color: #C06C84; font-size: 13px;"
        green = "color: #7FC97F; font-size: 13px;"

        if mis:
            lbl.setText("Seu cliente Steam não é compatível.")
            lbl.setStyleSheet(pink)
        elif err and fnd:
            lbl.setText("Não foi possível verificar a compatibilidade.")
            lbl.setStyleSheet(pink)
        elif not fnd:
            lbl.setText("Cliente Steam não encontrado.")
            lbl.setStyleSheet(pink)
        elif mis is False:
            lbl.setText("Seu cliente Steam é compatível.")
            lbl.setStyleSheet(green)
        lbl.setVisible(True)

    @staticmethod
    def _format_status_text(status: dict) -> str:
        if status.get("error"):
            return "Status desconhecido (erro na verificação)"
        ver = status.get("latest_version", "Desconhecida")
        if not status.get("installed", False):
            return f"Não instalado • Mais recente: {ver}"
        if status.get("update_available", False):
            return f"Atualização disponível • Mais recente: {ver}"
        return f"Atualizado • Versão: {status.get('installed_version', '?')}"

    def download_slssteam(self):
        """Download and install the official SLSsteam build."""
        if not self.main_window or not hasattr(self.main_window, "task_manager"):
            QMessageBox.critical(
                self,
                "Erro",
                "O gerenciador de tarefas não está disponível nesta sessão.",
            )
            return

        if self.download_slssteam_button is not None:
            self.download_slssteam_button.setEnabled(False)
            self.download_slssteam_button.setText("Instalando SLSsteam...")

        self.main_window.task_manager.download_slssteam()
        QTimer.singleShot(3000, self._update_slssteam_status)
        QTimer.singleShot(5000, self._reset_slssteam_button)

    def _reset_slssteam_button(self) -> None:
        if self.download_slssteam_button is None:
            return
        self.download_slssteam_button.setEnabled(True)
        self.download_slssteam_button.setText("Instalar/atualizar SLSsteam")

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

    def run_slscheevo(self) -> None:
        """Launch SLScheevo."""
        path = get_slscheevo_path()
        if not os.path.exists(path):
            QMessageBox.critical(self, "Erro", f"SLScheevo ausente: {path}")
            return

        save = get_slscheevo_save_path()
        cmd = []
        if str(path).endswith(".py"):
            py = get_venv_python()
            cmd.append(
                py if py else ("python" if sys.platform == "win32" else "python3")
            )
        cmd.extend(
            [str(path), "--save-dir", str(save), "--noclear", "--max-tries", "101"]
        )

        SettingsDialog._launch_terminal_command(cmd, os.path.dirname(path))

    @staticmethod
    def _launch_terminal_command(
        cmd: list[str], cwd: str, needs_env: bool = False
    ) -> None:
        """Try to launch a command in a visible terminal."""
        cmd: list[str] = [str(part) for part in cmd]
        cwd = str(cwd)
        if sys.platform == "win32":
            q_cmd = " ".join([f'"{c}"' if " " in str(c) else str(c) for c in cmd])
            try:
                subprocess.Popen(
                    f'start cmd /k "cd /d {cwd} && {q_cmd}"',
                    shell=True,
                )
                return
            except OSError:
                pass
        else:
            terms = [
                ["wezterm", "start", "--always-new-process", "--"] + cmd,
                ["konsole", "-e"] + cmd,
                ["gnome-terminal", "--"] + cmd,
                ["ptyxis", "--"] + cmd,
                ["alacritty", "-e"] + cmd,
                ["tilix", "-e"] + cmd,
                ["xfce4-terminal", "-e"] + cmd,
                ["terminator", "-x"] + cmd,
                ["mate-terminal", "-e"] + cmd,
                ["lxterminal", "-e"] + cmd,
                ["xterm", "-e"] + cmd,
                ["kitty", "-e"] + cmd,
            ]
            for t in terms:
                try:
                    t_cmd: list[str] = [str(part) for part in t]
                    subprocess.Popen(t_cmd, cwd=cwd)
                    return
                except FileNotFoundError:
                    continue

        # Fallback dialog
        msg_box = QMessageBox()
        msg_box.setWindowTitle("Terminal não encontrado")
        msg_box.setText(
            "Não foi possível abrir um terminal automaticamente.\n"
            "Abra um terminal e execute:\n"
        )
        msg_box.setInformativeText(" ".join(cmd))
        msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        msg_box.exec()

    def run_steamless_manually(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar executável", os.path.expanduser("~"), "*.exe"
        )
        if path and self.main_window:
            # noinspection PyUnresolvedReferences
            self.main_window.task_manager.run_steamless_manually(path)

    def open_custom_gifs_dialog(self) -> None:
        try:
            CustomGifsDialog(self.main_window).exec()
        except Exception as e:
            logger.error(f"Error opening GIF dialog: {e}")

    def clear_gif_cache(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Limpar cache",
                "Regenerar todos os GIFs?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            if self.main_window:
                # noinspection PyUnresolvedReferences
                self.main_window.gif_manager.regenerate_anyway = True
                # noinspection PyUnresolvedReferences
                self.main_window.ui_state.update_gifs()

    @staticmethod
    def register_registry_entries() -> None:
        SettingsDialog._manage_registry("ACCELA.reg", "Registrado com sucesso")

    @staticmethod
    def remove_registry_entries() -> None:
        SettingsDialog._manage_registry("ACCELA_uninstall.reg", "Removido com sucesso")

    @staticmethod
    def _manage_registry(filename: str, success_msg: str) -> None:
        if sys.platform != "win32":
            return

        # Locate registry file
        base = (
            os.path.join(getattr(sys, "_MEIPASS"), "deps")
            if getattr(sys, "frozen", False)
            else os.path.join(os.path.dirname(__file__), "..", "..", "deps")
        )
        reg_path = os.path.join(base, filename)

        if not os.path.exists(reg_path):
            QMessageBox.critical(None, "Erro", f"Faltando {filename}")
            return

        try:
            # Process template
            with open(reg_path, "r", encoding="utf-8-sig") as f:
                content = f.read().replace(
                    "[INSTALL_PATH]", sys.executable.replace("\\", "\\\\")
                )

            # Write temp file
            import tempfile

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".reg", delete=False
            ) as tmp:
                tmp.write(content)
                tmp_name = tmp.name

            # Import
            subprocess.run(["regedit", "/s", str(tmp_name)], check=True, shell=True)
            os.unlink(tmp_name)
            QMessageBox.information(None, "Sucesso", success_msg)

        except (IOError, OSError, subprocess.SubprocessError) as e:
            QMessageBox.critical(None, "Erro", f"Erro de registro: {e}")
