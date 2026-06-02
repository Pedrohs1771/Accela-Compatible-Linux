"""
Theme Manager.

Handles application theming, palette application, and font loading.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

from PyQt6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from utils.paths import Paths

logger = logging.getLogger(__name__)


def normal_palette_colors(
    background_color: QColor, accent_color: QColor
) -> Dict[QPalette.ColorRole, QColor]:
    """Define colors for the normal palette state."""
    return {
        QPalette.ColorRole.Window: background_color,
        QPalette.ColorRole.WindowText: accent_color,
        QPalette.ColorRole.Base: background_color.darker(120),
        QPalette.ColorRole.AlternateBase: background_color,
        QPalette.ColorRole.ToolTipBase: accent_color,
        QPalette.ColorRole.ToolTipText: background_color,
        QPalette.ColorRole.Text: accent_color,
        QPalette.ColorRole.Button: background_color,
        QPalette.ColorRole.ButtonText: accent_color,
        QPalette.ColorRole.BrightText: accent_color.lighter(120),
        QPalette.ColorRole.Link: accent_color.lighter(120),
        QPalette.ColorRole.Highlight: accent_color,
        QPalette.ColorRole.HighlightedText: background_color,
        QPalette.ColorRole.PlaceholderText: accent_color.darker(120),
    }


def disabled_palette_colors(
    disabled_bg: QColor, disabled_text: QColor, background_color: QColor
) -> Dict[QPalette.ColorRole, QColor]:
    """Define colors for the disabled palette state."""
    return {
        QPalette.ColorRole.Button: disabled_bg,
        QPalette.ColorRole.ButtonText: disabled_text,
        QPalette.ColorRole.Text: disabled_text,
        QPalette.ColorRole.WindowText: disabled_text,
        QPalette.ColorRole.Base: background_color.darker(140),
    }


def apply_palette(app: QApplication, accent: str, background: str) -> None:
    """Apply the Fusion style and custom color palette to the application."""
    app.setStyle("Fusion")
    dark_palette = QPalette()

    background_color = QColor(background)
    accent_color = QColor(accent)

    disabled_bg = background_color.darker(200)
    disabled_text = QColor(100, 100, 100)

    # Apply normal colors
    for role, color in normal_palette_colors(background_color, accent_color).items():
        dark_palette.setColor(role, color)

    # Apply disabled colors
    for role, color in disabled_palette_colors(
        disabled_bg, disabled_text, background_color
    ).items():
        dark_palette.setColor(QPalette.ColorGroup.Disabled, role, color)

    app.setPalette(dark_palette)
    _apply_stylesheet(app, background_color, accent_color, disabled_bg, disabled_text)


def _apply_stylesheet(
    app: QApplication,
    bg_color: QColor,
    accent_color: QColor,
    disabled_bg: QColor,
    disabled_text: QColor,
) -> None:
    """Generate and apply the CSS stylesheet."""
    bg_effect = bg_color
    if bg_effect == QColor("#000000"):
        bg_effect = QColor("#282828")

    accent_light = accent_color.lighter(120).name()
    bg_light = bg_color.lighter(120).name()

    gradient_border = (
        f"border-top: 2px solid {accent_light};\n"
        f"border-bottom: 2px solid {accent_light};\n"
        f"border-left: 2px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {accent_light}, stop:0.5 {bg_light}, stop:1 {accent_light});\n"
        f"border-right: 2px solid qlineargradient(x1:0, y1:0, x2:0, y2:1, "
        f"stop:0 {accent_light}, stop:0.5 {bg_light}, stop:1 {accent_light});"
    )

    gradient_border_full = (
        f"border-top: 2px solid {accent_light};\n"
        f"border-bottom: 2px solid {accent_light};\n"
        f"border-left: 2px solid {accent_light};\n"
        f"border-right: 2px solid {accent_light};"
    )

    style_sheet = f"""
        QLineEdit {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            border: 1px solid {accent_color.name()};
            padding: 8px;
        }}

        QLineEdit:hover {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
        }}

        QCheckBox {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 8px;
            spacing: 8px;
        }}

        QCheckBox::indicator {{
            width: 12px;
            height: 12px;
            background: {bg_color.name()};
            {gradient_border}
        }}

        QCheckBox::indicator:checked {{
            background: {accent_color.name()};
        }}

        QCheckBox::indicator:hover {{
            {gradient_border_full}
        }}

        QDialog {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
        }}

        QListWidget {{
            background-color: {bg_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            outline: 0;
            border: none;
        }}

        QListWidget::item {{
            background-color: {bg_color.darker(120).name()};
            color: {accent_color.name()};
            border-radius: 4px;
            padding: 6px;
        }}

        QListWidget::item:hover {{
            background-color: {bg_effect.lighter(120).name()};
            color: {accent_color.name()};
        }}

        QListWidget::item:selected {{
            background-color: {bg_effect.lighter(150).name()};
            color: {accent_color.name()};
        }}

        QListWidget::item:checked {{
            background-color: {bg_effect.lighter(200).name()};
            color: {accent_color.name()};
            font-weight: bold;
        }}

        QListWidget::item:checked:selected {{
            background-color: {bg_effect.lighter(250).name()};
            color: {accent_color.name()};
        }}

        QListWidget::indicator {{
            {gradient_border}
            border-radius: 4px;
        }}

        QListWidget::indicator:unchecked {{
            background-color: {bg_color.name()};
        }}

        QListWidget::indicator:checked {{
            background-color: {accent_color.name()};
        }}

        QListWidget::indicator:hover {{
            {gradient_border_full}
        }}

        QPushButton {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 6px 6px;
            {gradient_border}
            font-weight: bold;
        }}

        QPushButton:hover {{
            background-color: {bg_effect.name()};
            color: {accent_color.lighter(150).name()};
            {gradient_border_full}
        }}

        QPushButton:disabled {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
            border: 1px solid {disabled_text.name()};
            font-weight: normal;
        }}

        QPushButton:disabled:hover {{
            background-color: {disabled_bg.name()};
            color: {disabled_text.name()};
        }}

        QLabel {{
            color: {accent_color.name()};
        }}

        QToolTip {{
            background-color: {bg_color.name()};
            color: {accent_color.name()};
            padding: 6px;
        }}
    """
    app.setStyleSheet(style_sheet)


def _resolve_font_path(font_resource: Union[str, Path]) -> Path:
    """Resolve the provided font resource to a concrete Path object."""
    try:
        if isinstance(font_resource, str):
            candidate = Path(font_resource)
            if candidate.is_absolute() and candidate.exists():
                return candidate
            return Paths.resource(font_resource)

        if isinstance(font_resource, Path):
            return font_resource

        return Paths.resource(str(font_resource))
    except TypeError:
        # Fallback for unexpected types
        return Paths.resource(str(font_resource))


def _load_and_set_font(
    app: QApplication, font_path: Path, current_font: Optional[QFont]
) -> Tuple[bool, str]:
    """Load a font file from disk and set it to the application."""
    logger.debug(f"Attempting to load font from: {font_path}")

    if not font_path.exists():
        logger.warning(f"Font file not found at: {font_path}")
        return False, str(font_path)

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        logger.warning(f"QFontDatabase failed to load font: {font_path}")
        return False, str(font_path)

    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        logger.warning(f"No font families returned for: {font_path}")
        return False, str(font_path)

    font_name = families[0]

    if current_font:
        # Update existing font object with new family
        current_font.setFamily(font_name)
        new_font = current_font
    else:
        # Create new default font
        new_font = QFont(font_name, 10)

    app.setFont(new_font)
    return True, font_name


def apply_font(
    app: QApplication,
    font: Optional[QFont],
    font_file: Optional[Union[str, Path]],
) -> Tuple[bool, Union[str, Path]]:
    """
    Applies the font to the application.

    If font_file is provided, loads that font file and applies it.
    If font is provided (with a family name), checks if it's a system font.
    Otherwise, falls back to the default TrixieCyrG font.
    """
    default_font_file = "TrixieCyrG-Plain Regular.otf"

    # Case 1: Specific font file provided
    if font_file:
        path = _resolve_font_path(font_file)
        return _load_and_set_font(app, path, font)

    # Case 2: System font provided
    if font and font.family():
        font_family = font.family()
        if font_family in QFontDatabase.families():
            logger.debug(f"Using system font: {font_family}")
            app.setFont(font)
            return True, font_family

        # System font not found, log and fall through to default
        logger.debug(f"Font family '{font_family}' not found in system, using default")

    # Case 3: Fallback to default font
    path = _resolve_font_path(default_font_file)
    return _load_and_set_font(app, path, font)


def update_appearance(
    app: QApplication,
    accent: str = "#C06C84",
    background: str = "#000000",
    font: Optional[QFont] = None,
    font_file: Optional[Union[str, Path]] = None,
) -> Tuple[bool, Union[str, Path]]:
    """
    Apply a dynamic palette and custom font to the application.

    Args:
        app: The QApplication instance.
        accent: Hex string for accent color.
        background: Hex string for background color.
        font: Optional QFont object for settings.
        font_file: Relative resource path to load custom font.
    """
    apply_palette(app, accent, background)
    return apply_font(app, font, font_file)
