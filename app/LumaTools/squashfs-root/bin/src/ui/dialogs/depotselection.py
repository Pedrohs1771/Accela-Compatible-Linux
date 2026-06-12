import logging
import re
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from utils.image_fetcher import ImageFetcher
from utils.proton_tools import (
    build_default_proton_selection,
    choose_default_proton_tool,
    depot_selection_requires_proton,
    discover_proton_tools,
)
from ui.dialogs.dialog_helpers import create_standard_buttons

logger = logging.getLogger(__name__)


class DepotSelectionDialog(QDialog):
    def __init__(self, app_id, game_name, depots, header_url, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar depots para baixar")
        self.depots = depots
        self.game_name = game_name
        self.header_url = header_url
        self.resize(485, 520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 10)
        layout.setSpacing(10)

        self.anchor_row = -1
        self._online_fix_filter_enabled = False

        self.header_label = QLabel("Carregando imagem de capa...")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_label.setFixedHeight(108)
        layout.addWidget(self.header_label)
        self._fetch_header_image(app_id)

        content_widget = QVBoxLayout()
        content_widget.setContentsMargins(10, 0, 10, 0)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        self._host_platform = self._get_host_platform_family()

        def get_sort_key(depot_item):
            _depot_id, data = depot_item

            os_val = data.get("oslist")
            os_priority = self._calculate_os_priority(os_val)

            desc_str = data.get("desc", "").lower()
            lang_val = data.get("language")

            lang_priority = 3
            lang_sort_key = lang_val.lower() if lang_val else "zzzz"

            is_no_language = (
                lang_val is None
                and "english" not in desc_str
                and "japanese" not in desc_str
            )

            if "english" in desc_str:
                lang_priority = 1
                lang_sort_key = lang_val.lower() if lang_val else "english"
            elif is_no_language:
                lang_priority = 1
                lang_sort_key = "english"
            elif "japanese" in desc_str:
                lang_priority = 2
                lang_sort_key = "japanese"

            final_key = (os_priority, lang_priority, lang_sort_key)
            logger.debug(
                f"Depot {_depot_id}: OS='{os_val}', Lang='{lang_val}', Desc='{data.get('desc', '')}'"
            )
            logger.debug(
                f"    -> Key: {final_key} (OS_Prio: {os_priority}, Lang_Prio: {lang_priority}, Lang_Key: '{lang_sort_key}')"
            )

            return final_key

        logger.debug("--- Starting Depot Sort ---")
        sorted_depots = sorted(self.depots.items(), key=get_sort_key)
        logger.debug("--- Depot Sort Finished ---")

        is_first_depot = True

        for depot_id, depot_data in sorted_depots:
            original_desc = depot_data["desc"]

            original_desc = re.sub(
                r"\s*-\s*Depot\s*" + re.escape(depot_id),
                "",
                original_desc,
                flags=re.IGNORECASE,
            )

            tags = ""
            base_desc = original_desc.strip()
            tags_match = re.match(r"^((?:\[.*?]\s*)*)(.*)", original_desc)
            if tags_match:
                tags = tags_match.group(1).strip()
                base_desc = tags_match.group(2).strip()

            is_generic_fallback = bool(
                re.fullmatch(r"Depot \d+", base_desc, re.IGNORECASE)
            )

            if is_first_depot:
                if is_generic_fallback:
                    final_desc = f"{tags} {self.game_name}".strip()
                else:
                    final_desc = original_desc

                is_first_depot = False
            else:
                if is_generic_fallback:
                    final_desc = tags
                else:
                    final_desc = original_desc

            if depot_data.get("size"):
                try:
                    size_gb = int(depot_data["size"]) / (1024**3)
                    final_desc += f" <{size_gb:.2f} GB>"
                except (ValueError, TypeError):
                    pass

            platform_label = self._display_platform_label(depot_data.get("oslist"))
            item_text = f"{depot_id} {platform_label} - {final_desc}"

            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, depot_id)
            item.setCheckState(Qt.CheckState.Unchecked)

            # Removes ItemIsUserCheckable flag to disable internal checkbox handling, handled manually in self.on_depot_item_clicked
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self.list_widget.addItem(item)

        # Makes list widget update stylesheets for the items
        QApplication.processEvents()

        content_widget.addWidget(self.list_widget)

        self.list_widget.itemClicked.connect(self.on_depot_item_clicked)

        button_layout = QHBoxLayout()
        select_all_button = QPushButton("Selecionar tudo")
        select_all_button.clicked.connect(
            lambda: self._toggle_all_checkboxes(check=True)
        )
        button_layout.addWidget(select_all_button)

        deselect_all_button = QPushButton("Desmarcar tudo")
        deselect_all_button.clicked.connect(
            lambda: self._toggle_all_checkboxes(check=False)
        )
        button_layout.addWidget(deselect_all_button)
        content_widget.addLayout(button_layout)

        self.proton_checkbox = None
        self.proton_combo = None
        self._proton_tools = []
        if sys.platform == "linux":
            self._build_proton_section(content_widget)

        buttons = create_standard_buttons(self._accept_with_validation, self.reject)
        content_widget.addWidget(buttons)

        layout.addLayout(content_widget)
        self._refresh_proton_section()

    def _build_proton_section(self, parent_layout):
        self._proton_tools = discover_proton_tools()

        container = QFrame()
        container.setObjectName("protonCompatibilitySection")
        self.proton_container = container
        section_layout = QVBoxLayout(container)
        section_layout.setContentsMargins(10, 10, 10, 10)
        section_layout.setSpacing(6)

        title = QLabel("Compatibilidade Steam")
        self.proton_title = title
        section_layout.addWidget(title)

        self.proton_checkbox = QCheckBox("Forcar Proton para depots Windows")
        self.proton_checkbox.setChecked(False)
        self.proton_checkbox.toggled.connect(self._refresh_proton_section)
        section_layout.addWidget(self.proton_checkbox)

        tool_row = QHBoxLayout()
        tool_label = QLabel("Ferramenta:")
        self.proton_tool_label = tool_label
        tool_row.addWidget(tool_label)

        self.proton_combo = QComboBox()
        self.proton_combo.setMinimumWidth(220)
        tool_row.addWidget(self.proton_combo, 1)
        section_layout.addLayout(tool_row)

        self.online_checkbox = None

        self.online_fix_checkbox = QCheckBox("Implementar Online Compatible")
        self.online_fix_checkbox.setToolTip(
            "Selecione primeiro um depot [Windows]. OnlineFix roda a versao Windows via Proton."
        )
        self.online_fix_checkbox.setChecked(False)
        self.online_fix_checkbox.toggled.connect(self._on_online_fix_toggled)
        section_layout.addWidget(self.online_fix_checkbox)

        self.online_fix_notice = QLabel(
            "OnlineFix requer versão [Windows] rodando via Proton. Depots [Linux] "
            "e [Mac] somem da lista enquanto esta opção estiver marcada. Depots "
            "[All] continuam visíveis quando forem conteúdo comum."
        )
        self.online_fix_notice.setWordWrap(True)
        self.online_fix_notice.setVisible(False)
        section_layout.addWidget(self.online_fix_notice)

        help_label = QLabel(
            "Proton so e usado quando a selecao atual precisa rodar depots Windows no Linux."
        )
        self.proton_help_label = help_label
        help_label.setWordWrap(True)
        section_layout.addWidget(help_label)

        for tool in self._proton_tools:
            self.proton_combo.addItem(tool.display_name, tool.internal_name)

        default_tool = choose_default_proton_tool(self._proton_tools)
        if default_tool is not None:
            index = self.proton_combo.findData(default_tool.internal_name)
            if index >= 0:
                self.proton_combo.setCurrentIndex(index)

        parent_layout.addWidget(container)

    def _refresh_proton_section(self):
        if not self.proton_checkbox or not self.proton_combo:
            return

        selected_depots = self.get_selected_depots()
        requires_proton = depot_selection_requires_proton(selected_depots, self.depots)
        has_windows_selection = self._selected_has_windows_depot()
        proton_available = bool(self._proton_tools)
        enabled = requires_proton and proton_available
        show_windows_controls = has_windows_selection

        self.proton_checkbox.blockSignals(True)
        try:
            if requires_proton and proton_available:
                self.proton_checkbox.setChecked(True)
            else:
                self.proton_checkbox.setChecked(False)
        finally:
            self.proton_checkbox.blockSignals(False)

        self.proton_checkbox.setEnabled(enabled)
        self.proton_combo.setEnabled(enabled and self.proton_checkbox.isChecked())
        if hasattr(self, "proton_container"):
            self.proton_container.setVisible(show_windows_controls)
        self.proton_checkbox.setVisible(show_windows_controls)
        self.proton_combo.setVisible(show_windows_controls)
        if hasattr(self, "proton_tool_label"):
            self.proton_tool_label.setVisible(show_windows_controls)

        if requires_proton and not proton_available:
            self.proton_checkbox.setToolTip(
                "Nenhum Proton foi encontrado na Steam desta maquina."
            )
        elif requires_proton:
            self.proton_checkbox.setToolTip(
                "Obrigatorio para rodar depot Windows no Linux."
            )
        else:
            self.proton_checkbox.setToolTip(
                "Nao necessario para a selecao atual."
            )

        if hasattr(self, "proton_help_label"):
            if not selected_depots:
                self.proton_help_label.setText(
                    "Selecione um depot. As opcoes de Proton aparecem somente para depots [Windows]."
                )
            elif has_windows_selection:
                self.proton_help_label.setText(
                    "Depot [Windows] selecionado: LumaTools usara Proton e pode aplicar OnlineFix."
                )
            else:
                self.proton_help_label.setText(
                    "Selecao nativa desta maquina: Proton e OnlineFix nao sao necessarios."
                )

        self._refresh_online_fix_state()

    def _selected_has_windows_depot(self):
        return any(
            self._platform_family_for_depot(
                self.depots.get(str(depot_id), {}).get("oslist")
            )
            == "windows"
            for depot_id in self.get_selected_depots()
        )

    def _refresh_online_fix_state(self):
        if not hasattr(self, "online_fix_checkbox") or self.online_fix_checkbox is None:
            return

        has_windows_selection = self._selected_has_windows_depot()
        can_use_online_fix = has_windows_selection and bool(self._proton_tools)

        self.online_fix_checkbox.blockSignals(True)
        try:
            if not can_use_online_fix:
                self.online_fix_checkbox.setChecked(False)
        finally:
            self.online_fix_checkbox.blockSignals(False)

        self.online_fix_checkbox.setEnabled(can_use_online_fix)
        self.online_fix_checkbox.setVisible(has_windows_selection)
        if not has_windows_selection:
            self.online_fix_checkbox.setToolTip(
                "Selecione um depot [Windows] para habilitar o OnlineFix."
            )
        elif not self._proton_tools:
            self.online_fix_checkbox.setToolTip(
                "OnlineFix precisa de Proton instalado na Steam."
            )
        else:
            self.online_fix_checkbox.setToolTip(
                "Aplica OnlineFix na versao Windows e forca Proton."
            )

        if self.online_fix_notice is not None:
            self.online_fix_notice.setVisible(
                has_windows_selection and self.online_fix_checkbox.isChecked()
            )

    def get_proton_preferences(self):
        defaults = build_default_proton_selection(self.get_selected_depots(), self.depots)
        if not self.proton_checkbox or not self.proton_combo:
            return defaults

        selected_name = self.proton_combo.currentData() or ""
        selected_text = self.proton_combo.currentText() or ""
        defaults["force_proton"] = bool(
            defaults["force_proton"]
            and self.proton_checkbox.isEnabled()
            and self.proton_checkbox.isChecked()
            and selected_name
        )
        defaults["proton_tool_name"] = selected_name if defaults["force_proton"] else ""
        defaults["proton_tool_display_name"] = (
            selected_text if defaults["force_proton"] else ""
        )
        defaults["online_mode"] = False
        defaults["apply_online_fix"] = self.online_fix_checkbox.isChecked() if hasattr(self, "online_fix_checkbox") else False
        return defaults

    def _is_windows_or_generic_depot(self, depot_id):
        depot_data = self.depots.get(str(depot_id), {})
        platform = self._platform_family_for_depot(depot_data.get("oslist"))
        return platform == "windows" or self._is_generic_depot(depot_data.get("oslist"))

    def _has_windows_depot(self):
        return any(
            self._platform_family_for_depot(data.get("oslist")) == "windows"
            for data in self.depots.values()
        )

    def _on_online_fix_toggled(self, enabled):
        if enabled and not self._selected_has_windows_depot():
            self.online_fix_checkbox.blockSignals(True)
            self.online_fix_checkbox.setChecked(False)
            self.online_fix_checkbox.blockSignals(False)
            self._apply_online_fix_filter(False)
            self._refresh_online_fix_state()
            return

        if self.online_fix_notice is not None:
            self.online_fix_notice.setVisible(bool(enabled))

        if enabled:
            if self.proton_checkbox is not None:
                self.proton_checkbox.setChecked(True)

        self._apply_online_fix_filter(enabled)
        self._refresh_proton_section()

    def _apply_online_fix_filter(self, enabled):
        self._online_fix_filter_enabled = bool(enabled)
        if not hasattr(self, "list_widget") or self.list_widget is None:
            return

        has_visible_checked_item = False

        self.list_widget.blockSignals(True)
        try:
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                if item is None:
                    continue

                depot_id = str(item.data(Qt.ItemDataRole.UserRole))
                depot_data = self.depots.get(depot_id, {})
                family = self._platform_family_for_depot(depot_data.get("oslist"))
                compatible = family == "windows" or self._is_generic_depot(
                    depot_data.get("oslist")
                )
                hidden = bool(enabled and not compatible)

                item.setHidden(hidden)
                if hidden:
                    item.setCheckState(Qt.CheckState.Unchecked)
                    continue

                if item.checkState() == Qt.CheckState.Checked:
                    has_visible_checked_item = True

            if enabled and not has_visible_checked_item:
                self.online_fix_checkbox.blockSignals(True)
                self.online_fix_checkbox.setChecked(False)
                self.online_fix_checkbox.blockSignals(False)
                self._online_fix_filter_enabled = False
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    if item is not None:
                        item.setHidden(False)
        finally:
            self.list_widget.blockSignals(False)

        self.anchor_row = -1

    @staticmethod
    def _normalize_os_value(os_val):
        if not os_val:
            return ""
        return str(os_val).strip().lower()

    @staticmethod
    def _get_host_platform_family():
        if sys.platform == "win32":
            return "windows"
        if sys.platform == "linux":
            return "linux"
        if sys.platform == "darwin":
            return "macos"
        return ""

    def _calculate_os_priority(self, os_val):
        os_str = self._normalize_os_value(os_val)
        host = self._host_platform

        if host == "linux":
            if os_str == "linux":
                return 1
            if "all" in os_str or not os_str:
                return 2
            if os_str == "windows":
                return 3
            if os_str in ("macosx", "macos"):
                return 4
            return 5

        if host == "windows":
            if os_str == "windows":
                return 1
            if "all" in os_str or not os_str:
                return 2
            if os_str == "linux":
                return 3
            if os_str in ("macosx", "macos"):
                return 4
            return 5

        if host == "macos":
            if os_str in ("macosx", "macos"):
                return 1
            if "all" in os_str or not os_str:
                return 2
            if os_str == "windows":
                return 3
            if os_str == "linux":
                return 4
            return 5

        if os_str == "windows":
            return 1
        if os_str == "linux":
            return 2
        if "all" in os_str or not os_str:
            return 3
        if os_str in ("macosx", "macos"):
            return 4
        return 5

    @staticmethod
    def _platform_family_for_depot(os_val):
        os_str = DepotSelectionDialog._normalize_os_value(os_val)
        if os_str == "windows":
            return "windows"
        if os_str == "linux":
            return "linux"
        if os_str in ("macosx", "macos"):
            return "macos"
        return ""

    @staticmethod
    def _is_generic_depot(os_val):
        os_str = DepotSelectionDialog._normalize_os_value(os_val)
        return not os_str or "all" in os_str

    @staticmethod
    def _display_platform_label(os_val):
        family = DepotSelectionDialog._platform_family_for_depot(os_val)
        if family == "windows":
            return "[Windows]"
        if family == "linux":
            return "[Linux]"
        if family == "macos":
            return "[Mac]"
        return "[All]"

    def _get_selected_platform_families(self, selected_depots):
        families = set()
        for depot_id in selected_depots:
            depot_data = self.depots.get(str(depot_id), {})
            family = self._platform_family_for_depot(depot_data.get("oslist"))
            if family:
                families.add(family)
        return families

    def _has_host_compatible_depot(self):
        if not self._host_platform:
            return False

        for depot_data in self.depots.values():
            family = self._platform_family_for_depot(depot_data.get("oslist"))
            if family == self._host_platform or self._is_generic_depot(
                depot_data.get("oslist")
            ):
                return True

        return False

    def _accept_with_validation(self):
        selected_depots = self.get_selected_depots()
        if not selected_depots:
            QMessageBox.warning(
                self,
                "Nenhum depot selecionado",
                "Selecione pelo menos um depot antes de continuar.",
            )
            return

        if (
            hasattr(self, "online_fix_checkbox")
            and self.online_fix_checkbox.isChecked()
        ):
            invalid_depots = [
                str(depot_id)
                for depot_id in selected_depots
                if not self._is_windows_or_generic_depot(depot_id)
            ]
            if invalid_depots:
                reply = QMessageBox.question(
                    self,
                    "OnlineFix será desativado",
                    "Você selecionou depot Linux/Mac. OnlineFix só funciona com "
                    "versão Windows via Proton.\n\n"
                    "Deseja continuar baixando sem OnlineFix?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.online_fix_checkbox.setChecked(False)
                else:
                    return
            if not depot_selection_requires_proton(selected_depots, self.depots):
                reply = QMessageBox.question(
                    self,
                    "OnlineFix será desativado",
                    "Nenhum depot [Windows] foi selecionado. Deseja continuar "
                    "baixando sem OnlineFix?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes,
                )
                if reply == QMessageBox.StandardButton.Yes:
                    self.online_fix_checkbox.setChecked(False)
                else:
                    return
            if not self._proton_tools:
                QMessageBox.warning(
                    self,
                    "Proton não encontrado",
                    "OnlineFix precisa rodar a versão Windows via Proton. "
                    "Instale Proton Experimental na Steam e tente novamente.",
                )
                return

        selected_platforms = self._get_selected_platform_families(selected_depots)
        if len(selected_platforms) > 1:
            QMessageBox.warning(
                self,
                "Mistura de plataformas",
                "Você selecionou depots de plataformas diferentes na mesma instalação. "
                "Escolha apenas uma família de plataforma por vez, junto com depots genéricos [ALL] quando existirem.",
            )
            return

        selected_platform = next(iter(selected_platforms), "")
        if (
            self._host_platform
            and selected_platform
            and selected_platform != self._host_platform
            and self._has_host_compatible_depot()
        ):
            reply = QMessageBox.question(
                self,
                "Plataforma diferente do sistema",
                f"Você está no {self._host_platform} e selecionou depots {selected_platform}. "
                "Isso costuma gerar instalação quebrada. Deseja continuar mesmo assim?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        if (
            sys.platform == "linux"
            and depot_selection_requires_proton(selected_depots, self.depots)
            and self.proton_checkbox is not None
            and self.proton_checkbox.isChecked()
            and not self._proton_tools
        ):
            QMessageBox.warning(
                self,
                "Proton nao encontrado",
                "Voce selecionou depots Windows, mas nenhum Proton foi detectado na Steam. "
                "Instale ao menos o Proton Experimental e tente novamente.",
            )
            return

        self.accept()

    def on_depot_item_clicked(self, item):
        if item is None or item.isHidden():
            return

        modifiers = QApplication.keyboardModifiers()
        current_row = self.list_widget.row(item)

        current_state = item.checkState()
        new_state = (
            Qt.CheckState.Unchecked
            if current_state == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

        if modifiers == Qt.KeyboardModifier.ShiftModifier:
            if self.anchor_row == -1:
                item.setCheckState(new_state)
                self.anchor_row = current_row
            else:
                try:
                    anchor_item = self.list_widget.item(self.anchor_row)
                    if anchor_item is None:
                        raise RuntimeError("Anchor item is None")
                    target_state = anchor_item.checkState()
                except Exception as e:
                    logger.warning(f"Could not find anchor item for shift-click: {e}")
                    target_state = new_state

                start_row = min(self.anchor_row, current_row)
                end_row = max(self.anchor_row, current_row)

                self.list_widget.blockSignals(True)
                for i in range(start_row, end_row + 1):
                    row_item = self.list_widget.item(i)
                    if row_item is not None and not row_item.isHidden():
                        row_item.setCheckState(target_state)
                self.list_widget.blockSignals(False)

        else:
            item.setCheckState(new_state)
            self.anchor_row = current_row

        if not self._selected_has_windows_depot() and hasattr(self, "online_fix_checkbox"):
            self._apply_online_fix_filter(False)
        self._refresh_proton_section()

    def _toggle_all_checkboxes(self, check=True):
        state = Qt.CheckState.Checked if check else Qt.CheckState.Unchecked
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            row_item = self.list_widget.item(i)
            if row_item is not None and not row_item.isHidden():
                row_item.setCheckState(state)
        self.list_widget.blockSignals(False)

        self.anchor_row = -1
        if not self._selected_has_windows_depot() and hasattr(self, "online_fix_checkbox"):
            self._apply_online_fix_filter(False)
        self._refresh_proton_section()

    def _fetch_header_image(self, app_id):
        self._current_app_id = app_id
        url = ImageFetcher.get_header_image_url(app_id)
        self.fetcher = ImageFetcher(url)
        self.fetcher.finished.connect(self.on_image_fetched)
        self.fetcher.finished.connect(self._cleanup_fetcher)
        self.fetcher.start()

    def on_image_fetched(self, image_data):
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            self._apply_header_pixmap(pixmap)
        else:
            # Image fetch failed (404), try to get the correct URL from Steam API
            logger.debug("Image fetch failed, attempting to refresh from API")
            self._trigger_header_refresh()

    def _trigger_header_refresh(self):
        """
        Fetch the correct header URL from Steam API when generic URL fails.
        """
        app_id = getattr(self, "_current_app_id", None)
        if not app_id:
            self._show_no_image()
            return

        logger.debug(f"Fetching header URL from Steam API for appid {app_id}")

        try:
            # Fetch the correct URL from Steam API (synchronous but fast)
            api_url = ImageFetcher.fetch_header_from_web_api(app_id)

            if api_url:
                logger.info(f"Got header URL from API for appid {app_id}: {api_url}")

                # Update database with fresh URL
                try:
                    from managers.db_manager import DatabaseManager

                    db = DatabaseManager()
                    db.upsert_app_info(app_id, {"header_url": api_url})
                except Exception as e:
                    logger.debug(f"Could not update DB: {e}")

                # Re-fetch the image with the correct URL
                self.retry_fetcher = ImageFetcher(api_url)
                self.retry_fetcher.finished.connect(self._on_retry_image_fetched)
                self.retry_fetcher.finished.connect(self._cleanup_retry_fetcher)
                self.retry_fetcher.start()
            else:
                logger.debug(f"No header URL found in API for appid {app_id}")
                self._show_no_image()
        except Exception as e:
            logger.warning(f"Failed to refresh header for appid {app_id}: {e}")
            self._show_no_image()

    def _on_retry_image_fetched(self, image_data):
        """Handle the retry image fetch result."""
        if image_data:
            pixmap = QPixmap()
            pixmap.loadFromData(image_data)
            self._apply_header_pixmap(pixmap)
            logger.info("Successfully loaded header image after refresh")
        else:
            self._show_no_image()

    def _apply_header_pixmap(self, pixmap: QPixmap) -> None:
        # Scale to full dialog width (485px), height auto (Steam header is ~2.14:1 ratio = ~227px height)
        scaled = pixmap.scaledToWidth(
            self.width(), Qt.TransformationMode.SmoothTransformation
        )
        self.header_label.setPixmap(scaled)
        self.header_label.setFixedHeight(scaled.height())
        self.header_label.setStyleSheet("")

    def _show_no_image(self):
        """Show fallback text when image is not available."""
        self.header_label.setText("Imagem de capa indisponível.")
        self.header_label.setStyleSheet("")

    def _cleanup_fetcher(self, _data: bytes) -> None:
        if hasattr(self, "fetcher") and self.fetcher is not None:
            self.fetcher.deleteLater()
            self.fetcher = None

    def _cleanup_retry_fetcher(self, _data: bytes) -> None:
        if hasattr(self, "retry_fetcher") and self.retry_fetcher is not None:
            self.retry_fetcher.deleteLater()
            self.retry_fetcher = None

    def get_selected_depots(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item is None:
                continue
            if item.isHidden():
                continue
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def closeEvent(self, a0):
        """Ensure image fetch is cleaned up when dialog closes."""
        if hasattr(self, "fetcher") and self.fetcher is not None:
            try:
                self.fetcher.stop()
            except RuntimeError:
                pass
        if hasattr(self, "retry_fetcher") and self.retry_fetcher is not None:
            try:
                self.retry_fetcher.stop()
            except RuntimeError:
                pass
        super().closeEvent(a0)
