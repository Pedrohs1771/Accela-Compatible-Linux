import logging
from typing import Callable, Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QColor, QIcon, QMouseEvent, QMovie, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from utils.helpers import get_base_path
from utils.paths import Paths
from utils.settings import get_settings
from utils.version import app_version
from .assets import (
    BOOK_SVG,
    GEAR_SVG,
    MAXIMIZE,
    MINIMIZE,
    PACKAGE_SVG,
    PAPERCLIP_SVG,
    POWER_SVG,
    SEARCH_SVG,
    UPDATE_SVG,
)

logger = logging.getLogger(__name__)


class ClickableLabel(QLabel):
    """A QLabel that emits a callback when clicked."""

    def __init__(
        self,
        text: str,
        parent: Optional[QWidget] = None,
        callback: Optional[Callable[[], None]] = None,
    ):
        super().__init__(text, parent)
        self.callback = callback
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.callback:
            self.callback()
        super().mousePressEvent(event)


class BottomTitleBar(QFrame):
    """Custom title bar displayed at the bottom (or top) of the window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("bottom_titlebar")
        self.parent_window = parent
        self.drag_pos = None
        self.setFixedHeight(42)
        self.no_previous_state = True
        self._navi_movie_path: Optional[str] = None

        self.navi_label: Optional[QLabel] = None
        self.navi_movie: Optional[QMovie] = None
        self.title_label: Optional[QLabel] = None

        # Buttons
        self.status_button: Optional[QPushButton] = None
        self.search_button: Optional[QPushButton] = None
        self.ryuu_button: Optional[QPushButton] = None
        self.content_button: Optional[QPushButton] = None
        self.game_library_button: Optional[QPushButton] = None
        self.settings_button: Optional[QPushButton] = None
        self.update_button: Optional[QPushButton] = None
        self.update_badge: Optional[QLabel] = None
        self.minimize_button: Optional[QPushButton] = None
        self.maximize_button: Optional[QPushButton] = None
        self.close_button: Optional[QPushButton] = None

        self._setup_ui()
        self._apply_style()
        logger.debug("CustomTitleBar initialized.")

    def _setup_ui(self) -> None:
        """Setup the layout and widgets."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(6)

        left_widget = self._create_left_section()
        right_widget = self._create_right_section()

        self.title_label = QLabel("LumaTools")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )

        layout.addWidget(left_widget, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.title_label, 1)
        layout.addWidget(right_widget, 0, Qt.AlignmentFlag.AlignRight)

    def _create_left_section(self) -> QWidget:
        """Create the left section containing animation and version."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self._setup_navi_animation(layout)

        version_label = ClickableLabel(
            app_version,
            self.parent_window,
            getattr(self.parent_window, "open_credits_dialog", None),
        )
        version_label.setStyleSheet("color: #9D9D9D; font-size: 12px; padding-left: 4px;")
        version_label.setToolTip("Ver créditos")
        layout.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignLeft)

        widget.setMinimumSize(widget.sizeHint())
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return widget

    def _setup_navi_animation(self, layout: QHBoxLayout) -> None:
        """Setup the Navi GIF animation."""
        self.navi_label = QLabel()
        self.navi_label.setFixedHeight(22)
        self.navi_label.setScaledContents(True)
        layout.addWidget(self.navi_label, alignment=Qt.AlignmentFlag.AlignLeft)
        self.reload_navi_animation()

    def reload_navi_animation(self, force: bool = False) -> None:
        if self.navi_label is None:
            return

        gif_path = get_base_path() / "gifs/colorized/navi.gif"
        if not gif_path.exists():
            gif_path = Paths.resource("gif/navi.gif")
        try:
            movie_path = str(gif_path.resolve())
        except OSError:
            movie_path = str(gif_path)

        if (
            not force
            and self._navi_movie_path == movie_path
            and self.navi_movie
            and self.navi_movie.isValid()
        ):
            if self.navi_movie.state() != QMovie.MovieState.Running:
                self.navi_movie.start()
            return

        movie = QMovie(movie_path)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)

        if not movie.isValid():
            return

        movie.jumpToFrame(0)
        orig_size = movie.currentImage().size()
        height = 22
        width = (
            int(height * (orig_size.width() / orig_size.height()))
            if orig_size.height() > 0
            else 62
        )

        self.navi_label.setFixedSize(width, height)
        previous_movie = self.navi_movie
        self.navi_movie = movie
        self._navi_movie_path = movie_path
        self.navi_label.setMovie(movie)
        movie.start()
        if previous_movie and previous_movie is not movie:
            previous_movie.stop()

    def _create_right_section(self) -> QWidget:
        """Create the right section containing buttons."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addStretch()

        parent = self.parent_window

        self.status_button = self._create_colored_circle_button(
            getattr(parent, "open_status_dialog", None),
            "Status do download",
        )
        layout.addWidget(self.status_button)

        self.search_button = self._create_svg_button(
            SEARCH_SVG, getattr(parent, "open_fetch_dialog", None), "Baixar jogo"
        )
        layout.addWidget(self.search_button)

        self.ryuu_button = self._create_svg_button(
            PAPERCLIP_SVG,
            getattr(parent, "open_ryuu_fixes", None),
            "Ryuu Fixes",
        )
        layout.addWidget(self.ryuu_button)

        self.content_button = self._create_svg_button(
            PACKAGE_SVG,
            getattr(parent, "open_content_manager", None),
            "Conteudo e Workshop",
        )
        layout.addWidget(self.content_button)

        self.game_library_button = self._create_svg_button(
            BOOK_SVG, getattr(parent, "open_game_library", None), "Biblioteca"
        )
        layout.addWidget(self.game_library_button)

        self.settings_button = self._create_svg_button(
            GEAR_SVG, getattr(parent, "open_settings", None), "Configurações"
        )
        layout.addWidget(self.settings_button)

        self.update_button = self._create_round_svg_button(
            UPDATE_SVG,
            getattr(parent, "open_update_center", None),
            "Update Center",
        )
        self.update_badge = QLabel(self.update_button)
        self.update_badge.setFixedSize(8, 8)
        self.update_badge.setStyleSheet(
            "background-color: #ff3b30; border: 1px solid #ffd7d3; border-radius: 4px;"
        )
        self.update_badge.move(15, 1)
        self.update_badge.hide()
        layout.addWidget(self.update_button)

        self.minimize_button = self._create_svg_button(
            MINIMIZE, self._minimize_window, "Minimizar"
        )
        layout.addWidget(self.minimize_button)

        self.maximize_button = self._create_svg_button(
            MAXIMIZE, self._maximize_window, "Maximizar"
        )
        layout.addWidget(self.maximize_button)

        self.close_button = self._create_svg_button(
            POWER_SVG, self._close_window, "Fechar"
        )
        layout.addWidget(self.close_button)

        widget.setMinimumSize(widget.sizeHint())
        widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return widget

    def _apply_style(self) -> None:
        """Apply style settings from the parent window."""
        settings = get_settings()
        bg_color = settings.value("background_color", "#000000")
        accent_color = settings.value("accent_color", "#C06C84")
        background = QColor(bg_color)
        accent = QColor(accent_color)
        surface = (
            QColor("#08080B")
            if background.lightness() < 24
            else background.lighter(106)
        )
        border = f"rgba({accent.red()}, {accent.green()}, {accent.blue()}, 72)"

        self.setStyleSheet(
            f"""
            QFrame#bottom_titlebar {{
                background-color: {surface.name()};
                border-top: 1px solid {border};
            }}
            QToolTip {{
                color: {accent_color};
                background-color: {surface.name()};
                border: 1px solid {accent_color};
                padding: 5px;
            }}
        """
        )

        if self.title_label:
            self.title_label.setStyleSheet(
                f"color: {accent_color}; font-size: 13pt; font-weight: 700; "
                "letter-spacing: 0px;"
            )

    def update_style(self) -> None:
        """Update the style when colors change."""
        self._apply_style()
        self._update_button_colors()
        self._update_button_styles()

    def _update_button_styles(self) -> None:
        """Update all button styles with custom border and background."""
        settings = get_settings()
        bg_color = QColor(settings.value("background_color", "#000000"))

        bg_hover = bg_color
        hover_lightness = 150
        if bg_color == QColor("#000000"):
            bg_hover = QColor("#282828")
            hover_lightness = 120

        button_style = f"""
            QPushButton {{
                background-color: {bg_color.name()};
                border: none;
                border-radius: 3px;
                padding: 1px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover.lighter(hover_lightness).name()};
            }}
        """

        buttons = [
            self.minimize_button,
            self.maximize_button,
            self.search_button,
            self.ryuu_button,
            self.content_button,
            self.game_library_button,
            self.settings_button,
            self.close_button,
        ]

        for button in buttons:
            if button:
                button.setStyleSheet(button_style)

        if self.update_button:
            self._apply_round_button_style(self.update_button)

    def _update_button_colors(self) -> None:
        """Update all SVG button colors to match the current accent color."""
        settings = get_settings()
        accent_color = settings.value("accent_color", "#C06C84")

        buttons = [
            (self.minimize_button, MINIMIZE),
            (self.maximize_button, MAXIMIZE),
            (self.search_button, SEARCH_SVG),
            (self.ryuu_button, PAPERCLIP_SVG),
            (self.content_button, PACKAGE_SVG),
            (self.game_library_button, BOOK_SVG),
            (self.settings_button, GEAR_SVG),
            (self.update_button, UPDATE_SVG),
            (self.close_button, POWER_SVG),
        ]

        for button, svg_data in buttons:
            if button:
                self._update_svg_button_color(button, svg_data, accent_color)

        if self.no_previous_state and self.status_button:
            self._update_colored_circle_button(self.status_button, accent_color)

    @staticmethod
    def _update_colored_circle_button(button: QPushButton, color: str) -> None:
        """Update a colored circle button's color."""
        try:
            stylesheet = f"""
            QPushButton {{
                border-radius: 10px;
                background-color: {color};
                border: none;
            }}
            QPushButton:hover {{
                border: 2px solid {color};
                background-color: {color};
                opacity: 0.8;
            }}
            QPushButton:pressed {{
                opacity: 0.6;
            }}
            """
            button.setStyleSheet(stylesheet)
        except Exception as e:
            logger.error(f"Failed to update colored circle button: {e}", exc_info=True)

    def update_colored_circle_button(self, button: QPushButton, color: str) -> None:
        self._update_colored_circle_button(button, color)

    @staticmethod
    def _build_svg_pixmap(svg_data: str, color: QColor) -> QPixmap:
        renderer = QSvgRenderer(svg_data.encode("utf-8"))
        icon_size = QSize(16, 16)

        pixmap = QPixmap(icon_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)

        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter)

        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        painter.fillRect(pixmap.rect(), color)
        painter.end()

        return pixmap

    def _update_svg_button_color(
        self, button: QPushButton, svg_data: str, color: str
    ) -> None:
        """Update a single SVG button's color."""
        try:
            pixmap = self._build_svg_pixmap(svg_data, QColor(color))
            button.setIcon(QIcon(pixmap))

        except Exception as e:
            logger.error(f"Failed to update SVG button color: {e}", exc_info=True)

    def _create_svg_button(
        self,
        svg_data: str,
        on_click: Optional[Callable[[], None]],
        tooltip: str,
    ) -> QPushButton:
        """Create a button with an SVG icon."""
        try:
            button = QPushButton()
            button.setToolTip(tooltip)
            button.setFlat(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet(
                """
                QPushButton {
                    background-color: transparent;
                    border: none;
                    border-radius: 3px;
                    padding: 1px;
                }
                QPushButton:hover {
                    background-color: rgba(255, 255, 255, 0.08);
                }
                """
            )

            settings = get_settings()
            accent_color = QColor(settings.value("accent_color", "#C06C84"))

            pixmap = self._build_svg_pixmap(svg_data, accent_color)
            button.setIcon(QIcon(pixmap))
            button.setIconSize(pixmap.size())
            button.setFixedSize(26, 26)

            if on_click:
                button.clicked.connect(on_click)
            return button

        except Exception as e:
            logger.error(f"Failed to create SVG button: {e}", exc_info=True)
            fallback_button = QPushButton("X")
            fallback_button.setFixedSize(22, 22)
            if on_click:
                fallback_button.clicked.connect(on_click)
            return fallback_button

    def _create_round_svg_button(
        self,
        svg_data: str,
        on_click: Optional[Callable[[], None]],
        tooltip: str,
    ) -> QPushButton:
        button = self._create_svg_button(svg_data, on_click, tooltip)
        self._apply_round_button_style(button)
        return button

    @staticmethod
    def _apply_round_button_style(button: QPushButton) -> None:
        settings = get_settings()
        accent_color = settings.value("accent_color", "#C06C84")
        bg_color = QColor(settings.value("background_color", "#000000"))
        hover_color = bg_color.lighter(130).name() if bg_color != QColor("#000000") else "#202020"
        button.setFixedSize(28, 28)
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: transparent;
                border: 1px solid {accent_color};
                border-radius: 14px;
                padding: 1px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            """
        )

    def set_update_badge_visible(self, visible: bool) -> None:
        if self.update_badge is not None:
            self.update_badge.setVisible(visible)

    @staticmethod
    def _create_colored_circle_button(
        callback: Optional[Callable[[], None]],
        tooltip_text: str,
    ) -> QPushButton:
        """Create a simple colored circle button."""
        button = QPushButton()
        button.setFixedSize(20, 20)

        if tooltip_text:
            button.setToolTip(tooltip_text)

        if callback:
            button.clicked.connect(callback)

        return button

    def _minimize_window(self) -> None:
        """Minimize the window."""
        self.parent_window.showMinimized()

    def _maximize_window(self) -> None:
        """Maximize or restore the window."""
        if self.parent_window.isMaximized():
            self.parent_window.showNormal()
        else:
            self.parent_window.showMaximized()

    def _close_window(self) -> None:
        """Close the window."""
        self.parent_window.close()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press for window movement."""
        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return

        # Check if we're not on a resize handle (border area)
        border_width = 6
        pos = event.pos()
        width = self.width()
        height = self.height()

        on_left_border = pos.x() <= border_width
        on_right_border = pos.x() >= width - border_width
        on_top_border = pos.y() <= border_width
        on_bottom_border = pos.y() >= height - border_width

        if on_left_border or on_right_border or on_top_border or on_bottom_border:
            event.accept()
            return

        window = self.window().windowHandle()
        if window is not None:
            window.startSystemMove()

        event.accept()


"""
The wired might actually be thought of as a highly advanced upper layer of
the real world. In other words, physical reality is nothing but an illusion,
a hologram of the information that flows to us through the wired.
This is because the body, physical motion, the activity of the human brain
is merely a physical phenomenon, simply caused by synapses delivering
electrical impulses.
The physical body exists at a less evolved plane only to verify one's
existence in the universe.
"""
