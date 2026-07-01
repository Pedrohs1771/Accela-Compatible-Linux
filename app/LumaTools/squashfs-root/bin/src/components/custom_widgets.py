from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt6.QtWidgets import QLabel, QPushButton


class ScaledLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._movie = None

    def setMovie(self, movie):
        if self._movie:
            try:
                self._movie.frameChanged.disconnect(self.update)
            except (TypeError, RuntimeError):
                pass
        self._movie = movie
        if self._movie:
            self._movie.frameChanged.connect(self.update)
            self.update()

    def paintEvent(self, event):
        if self._movie:
            painter = QPainter(self)
            background = self.property("background_color")
            if isinstance(background, str) and QColor(background).isValid():
                fill_color = QColor(background)
            else:
                fill_color = self.palette().color(self.backgroundRole())
            painter.fillRect(self.rect(), fill_color)
            pixmap = self._movie.currentPixmap()
            if not pixmap.isNull():
                rect = self.rect()
                scaled_size = pixmap.size()
                scaled_size.scale(rect.size(), Qt.AspectRatioMode.KeepAspectRatio)
                x = (rect.width() - scaled_size.width()) // 2
                y = (rect.height() - scaled_size.height()) // 2
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                painter.drawPixmap(x, y, scaled_size.width(), scaled_size.height(), pixmap)
            painter.end()
        else:
            super().paintEvent(event)

    def sizeHint(self):
        if self._movie:
            return self._movie.frameRect().size()
        return super().sizeHint()



class ScaledFontLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self.setWordWrap(True)  # Enable word wrap
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)  # Center text

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Get text metrics to check if text fits
        font = self.font()
        text = self.text()

        if text:
            # Start with height-based size
            new_size = max(8, min(72, int(self.height() * 0.4)))
            font.setPointSize(new_size)

            # Check if text fits width-wise
            test_font = QFont(font)
            test_font.setPointSize(new_size)
            metrics = QFontMetrics(test_font)
            text_width = metrics.horizontalAdvance(text)

            # Reduce font size if text is too wide (with some padding)
            while text_width > self.width() * 0.9 and new_size > 8:
                new_size -= 1
                test_font.setPointSize(new_size)
                metrics = QFontMetrics(test_font)
                text_width = metrics.horizontalAdvance(text)

            font.setPointSize(new_size)

        self.setFont(font)


class ScaledButton(QPushButton):
    """QPushButton that automatically scales its font to fit the button size"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMinimumSize(1, 1)
        self.max_font_size = 14

    def set_max_font_size(self, size):
        """Set maximum font size for scaling"""
        self.max_font_size = max(8, size)
        self._scale_font()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._scale_font()

    def setText(self, text):
        """Override setText to trigger font scaling immediately"""
        super().setText(text)
        self._scale_font()

    def _scale_font(self):
        """Calculate and set appropriate font size for current text and button size"""
        text = self.text()
        button_width = self.width()
        button_height = self.height()

        if text and button_width > 0 and button_height > 0:
            font = self.font()
            new_size = max(8, min(self.max_font_size, int(button_height * 0.4)))
            font.setPointSize(new_size)
            self.setFont(font)
