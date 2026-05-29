import logging
from typing import List, Optional

from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.dialog_helpers import create_standard_buttons

logger = logging.getLogger(__name__)


class SteamLibraryDialog(QDialog):
    """Dialog for selecting a Steam library folder."""

    def __init__(self, library_paths: List[str], parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Selecionar biblioteca da Steam")
        self.setMinimumWidth(500)

        self.selected_path: Optional[str] = None
        self.list_widget: Optional[QListWidget] = None

        logger.debug(f"Opening SteamLibraryDialog with {len(library_paths)} libraries.")
        self._setup_ui(library_paths)

    def _setup_ui(self, library_paths: List[str]) -> None:
        """Initialize the layout and widgets."""
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()

        # Fix for overlapping items
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(2)

        # Populate list with sorted paths
        for path in sorted(library_paths):
            item = QListWidgetItem(path)
            # Explicitly set size hint to prevent overlap
            item.setSizeHint(QSize(0, 24))
            self.list_widget.addItem(item)

        layout.addWidget(self.list_widget)

        # Select first item by default if available
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

        buttons = create_standard_buttons(self.accept, self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        """Handle the OK button click."""
        if not self.list_widget:
            super().accept()
            return

        current_item = self.list_widget.currentItem()

        if not current_item:
            QMessageBox.warning(self, "Nenhuma seleção", "Selecione uma pasta de biblioteca.")
            return

        self.selected_path = current_item.text()
        logger.info(f"User selected Steam library: {self.selected_path}")
        super().accept()

    def get_selected_path(self) -> Optional[str]:
        """Return the selected library path."""
        return self.selected_path
