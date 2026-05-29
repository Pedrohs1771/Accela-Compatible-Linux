import logging
from typing import Optional

from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDialog,
    QFontDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from utils.settings import get_settings
from ui.dialogs.dialog_helpers import create_standard_buttons
from utils.helpers import create_color_setting

logger = logging.getLogger(__name__)


class StyleDialog(QDialog):
    """Dialog for customizing application appearance settings."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Style Settings")
        self.settings = get_settings()
        self.main_layout = QVBoxLayout(self)
        self.main_window = parent

        self.current_font = QFont()

        # UI Elements (initialized in setup methods)
        self.accent_color_button: Optional[QPushButton] = None
        self.bg_color_button: Optional[QPushButton] = None
        self.font_button: Optional[QPushButton] = None
        self.ignore_color_warnings_checkbox: Optional[QCheckBox] = None
        self.titlebar_position_checkbox: Optional[QCheckBox] = None
        self.gif_display_checkbox: Optional[QCheckBox] = None

        logger.debug("Opening StyleDialog.")
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Initialize all UI components."""
        self._setup_color_settings()
        self._setup_font_settings()
        self._setup_checkboxes()
        self._setup_dialog_buttons()

    def _setup_color_settings(self) -> None:
        """Setup accent and background color controls."""
        color_group = QVBoxLayout()
        color_label = QLabel("Color Settings")
        color_label.setStyleSheet("font-weight: bold;")
        color_group.addWidget(color_label)

        accent_layout, self.accent_color_button, accent_reset = create_color_setting(
            "Accent Color:", "accent_color", "#C06C84", self
        )
        # noinspection PyUnresolvedReferences
        self.accent_color_button.clicked.connect(self.choose_accent_color)
        # noinspection PyUnresolvedReferences
        accent_reset.clicked.connect(self.reset_accent_color)
        color_group.addLayout(accent_layout)

        bg_layout, self.bg_color_button, bg_reset = create_color_setting(
            "Background Color:", "background_color", "#000000", self
        )
        # noinspection PyUnresolvedReferences
        self.bg_color_button.clicked.connect(self.choose_bg_color)
        # noinspection PyUnresolvedReferences
        bg_reset.clicked.connect(self.reset_bg_color)
        color_group.addLayout(bg_layout)

        self.main_layout.addLayout(color_group)

    def _setup_font_settings(self) -> None:
        """Setup font selection controls."""
        font_group = QVBoxLayout()
        font_label = QLabel("Font Settings")
        font_label.setStyleSheet("font-weight: bold;")
        font_group.addWidget(font_label)

        font_layout = QHBoxLayout()
        font_chooser_label = QLabel("Font:")

        self.font_button = QPushButton("Choose Font")
        self._load_current_font()
        self.update_font_button_text()
        # noinspection PyUnresolvedReferences
        self.font_button.clicked.connect(self.choose_font)

        font_reset = QPushButton("Reset")
        # noinspection PyUnresolvedReferences
        font_reset.clicked.connect(self.reset_font)

        font_layout.addWidget(font_chooser_label)
        font_layout.addWidget(self.font_button)
        font_layout.addWidget(font_reset)
        font_layout.addStretch()

        font_group.addLayout(font_layout)
        self.main_layout.addLayout(font_group)

    def _load_current_font(self) -> None:
        """Load font settings from QSettings."""
        family = self.settings.value("font", "TrixieCyrG-Plain")
        size = self.settings.value("font-size", 10, type=int)
        style = self.settings.value("font-style", "Normal")

        self.current_font.setFamily(family)
        self.current_font.setPointSize(size)

        if style == "Italic":
            self.current_font.setItalic(True)
        elif style == "Bold":
            self.current_font.setBold(True)
        elif style == "Bold Italic":
            self.current_font.setBold(True)
            self.current_font.setItalic(True)

    def _setup_checkboxes(self) -> None:
        """Setup configuration checkboxes."""
        # Ignore warnings
        ignore_warn = self.settings.value("ignore_color_warnings", False, type=bool)
        self.ignore_color_warnings_checkbox = QCheckBox("Ignore color warnings")
        self.ignore_color_warnings_checkbox.setChecked(ignore_warn)
        self.ignore_color_warnings_checkbox.setToolTip(
            "Lets you ignore the color warnings and set any color."
        )
        # Insert after color group (index 1 in layout)
        self.main_layout.insertWidget(1, self.ignore_color_warnings_checkbox)

        # Titlebar position
        self.titlebar_position_checkbox = QCheckBox("Move Titlebar to Top")
        is_top = self.settings.value("titlebar_position", "bottom", type=str) == "top"
        self.titlebar_position_checkbox.setChecked(is_top)
        self.titlebar_position_checkbox.setToolTip(
            "Move the titlebar from the bottom to the top of the window."
        )
        # noinspection PyUnresolvedReferences
        self.titlebar_position_checkbox.stateChanged.connect(
            self.on_titlebar_position_changed
        )
        self.main_layout.addWidget(self.titlebar_position_checkbox)

        # GIF display
        self.gif_display_checkbox = QCheckBox("Show GIF Display")
        gif_enabled = self.settings.value("gif_display_enabled", True, type=bool)
        self.gif_display_checkbox.setChecked(gif_enabled)
        self.gif_display_checkbox.setToolTip(
            "Show or hide the animated GIF display in the main window."
        )
        # noinspection PyUnresolvedReferences
        self.gif_display_checkbox.stateChanged.connect(self.on_gif_display_changed)
        self.main_layout.addWidget(self.gif_display_checkbox)

    def _setup_dialog_buttons(self) -> None:
        """Setup standard Ok/Cancel buttons."""
        buttons = create_standard_buttons(self.accept, self.reject)
        self.main_layout.addWidget(buttons)

    def on_gif_display_changed(self, state: int) -> None:
        """Handle GIF display setting change."""
        gif_display_enabled = state == 2
        self.settings.setValue("gif_display_enabled", gif_display_enabled)

        if self.main_window and hasattr(self.main_window, "update_gif_display"):
            self.main_window.update_gif_display(gif_display_enabled)
            logger.info(f"GIF display set to: {gif_display_enabled}")

    def on_titlebar_position_changed(self, state: int) -> None:
        """Handle immediate titlebar position change."""
        position = "top" if state == 2 else "bottom"
        self.settings.setValue("titlebar_position", position)

        if self.main_window and hasattr(self.main_window, "reposition_titlebar"):
            self.main_window.reposition_titlebar(position)
            logger.info(f"Titlebar position set to: {position}")

    def update_font_button_text(self) -> None:
        """Update the font button text to show current font details."""
        family = self.current_font.family()
        size = self.current_font.pointSize()
        font_text = f"{family} {size}pt"

        if self.current_font.bold() and self.current_font.italic():
            font_text += " Bold Italic"
        elif self.current_font.bold():
            font_text += " Bold"
        elif self.current_font.italic():
            font_text += " Italic"

        if self.font_button:
            self.font_button.setText(font_text)
            self.font_button.setFont(self.current_font)

    def reset_accent_color(self) -> None:
        default = "#C06C84"
        self.settings.setValue("accent_color", default)
        if self.accent_color_button:
            self.accent_color_button.setStyleSheet(f"background-color: {default};")

    def reset_bg_color(self) -> None:
        default = "#000000"
        self.settings.setValue("background_color", default)
        if self.bg_color_button:
            self.bg_color_button.setStyleSheet(f"background-color: {default};")

    def reset_font(self) -> None:
        self.current_font.setFamily("TrixieCyrG-Plain")
        self.current_font.setPointSize(10)
        self.current_font.setBold(False)
        self.current_font.setItalic(False)

        self.update_font_button_text()

        self.settings.setValue("font", "TrixieCyrG-Plain")
        self.settings.setValue("font-size", 10)
        self.settings.setValue("font-style", "Normal")

    @staticmethod
    def is_too_dark(color: QColor) -> bool:
        """Calculate perceived brightness (0-255)."""
        brightness = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        return brightness < 15

    @staticmethod
    def is_too_close_to_accent_color(
        accent_color: QColor,
        background_color: QColor,
        threshold: int = 100,
    ) -> bool:
        """Return True if background color is too close to accent color."""
        r_diff = background_color.red() - accent_color.red()
        g_diff = background_color.green() - accent_color.green()
        b_diff = background_color.blue() - accent_color.blue()

        distance = (r_diff**2 + g_diff**2 + b_diff**2) ** 0.5
        return distance < threshold

    def choose_accent_color(self) -> None:
        color = QColorDialog.getColor()

        if not color.isValid():
            return

        if (
            self.ignore_color_warnings_checkbox
            and not self.ignore_color_warnings_checkbox.isChecked()
            and self.is_too_dark(color)
        ):
            QMessageBox.warning(
                self,
                "Invalid Color",
                "This color is too dark and would make the UI unusable.",
            )
            return

        hex_color = color.name()
        self.settings.setValue("accent_color", hex_color)
        if self.accent_color_button:
            self.accent_color_button.setStyleSheet(f"background-color: {hex_color};")

    def choose_bg_color(self) -> None:
        color = QColorDialog.getColor()
        if not color.isValid():
            return

        hex_color = color.name()
        if self.bg_color_button:
            self.bg_color_button.setStyleSheet(f"background-color: {hex_color};")

    def choose_font(self) -> None:
        font, ok = QFontDialog.getFont(self.current_font, self)
        if not ok:
            return

        self.current_font = font
        self.update_font_button_text()

        self.settings.setValue("font", font.family())
        self.settings.setValue("font-size", font.pointSize())

        font_style = "Normal"
        if font.bold() and font.italic():
            font_style = "Bold Italic"
        elif font.bold():
            font_style = "Bold"
        elif font.italic():
            font_style = "Italic"

        self.settings.setValue("font-style", font_style)

    def accept(self) -> None:
        """Validate and save settings before closing."""
        if not self.accent_color_button or not self.bg_color_button:
            super().accept()
            return

        # Extract colors from stylesheets
        accent_style = self.accent_color_button.styleSheet()
        accent_color = accent_style.split("background-color: ")[1].split(";")[0]

        bg_style = self.bg_color_button.styleSheet()
        bg_color = bg_style.split("background-color: ")[1].split(";")[0]

        ignore_warnings = (
            self.ignore_color_warnings_checkbox.isChecked()
            if self.ignore_color_warnings_checkbox
            else False
        )
        self.settings.setValue("ignore_color_warnings", ignore_warnings)

        if not ignore_warnings:
            if self.is_too_close_to_accent_color(
                QColor(accent_color), QColor(bg_color)
            ):
                QMessageBox.warning(
                    self,
                    "Invalid Color",
                    "The background color is too similar to the accent color "
                    "and would reduce contrast.",
                )
                return

        self.settings.setValue("accent_color", accent_color)
        self.settings.setValue("background_color", bg_color)

        # Font settings are saved immediately in choose_font, but re-save here
        self.settings.setValue("font", self.current_font.family())
        self.settings.setValue("font-size", self.current_font.pointSize())

        font_style = "Normal"
        if self.current_font.bold() and self.current_font.italic():
            font_style = "Bold Italic"
        elif self.current_font.bold():
            font_style = "Bold"
        elif self.current_font.italic():
            font_style = "Italic"
        self.settings.setValue("font-style", font_style)

        # Other settings
        if self.titlebar_position_checkbox:
            is_top = self.titlebar_position_checkbox.isChecked()
            pos = "top" if is_top else "bottom"
            self.settings.setValue("titlebar_position", pos)
            logger.info(f"Titlebar position set to: {pos}")

        if self.gif_display_checkbox:
            gif_enabled = self.gif_display_checkbox.isChecked()
            self.settings.setValue("gif_display_enabled", gif_enabled)

        logger.info("Style settings saved.")
        super().accept()
