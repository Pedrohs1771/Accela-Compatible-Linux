import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtWidgets import (
    QDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ui.dialogs.dialog_helpers import create_standard_buttons
from core import steam_helpers

logger = logging.getLogger(__name__)


class SteamLibraryDialog(QDialog):
    """Dialog for selecting a Steam library folder."""

    def __init__(
        self,
        library_paths: List[str],
        parent: Optional[QWidget] = None,
        initial_path: Optional[str] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Selecionar biblioteca da Steam")
        self.setMinimumWidth(500)

        self.selected_path: Optional[str] = None
        self.list_widget: Optional[QListWidget] = None

        logger.debug(f"Opening SteamLibraryDialog with {len(library_paths)} libraries.")
        self._setup_ui(library_paths, initial_path)

    def _setup_ui(
        self, library_paths: List[str], initial_path: Optional[str] = None
    ) -> None:
        """Initialize the layout and widgets."""
        layout = QVBoxLayout(self)

        self.list_widget = QListWidget()

        # Fix for overlapping items
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(2)

        # Keep backend order intact. On Linux this puts the library belonging
        # to the currently running Steam mode (native/Flatpak/Snap) first.
        preferred_library = steam_helpers.get_preferred_steam_library()
        selected_row = 0
        for index, path in enumerate(library_paths):
            item = QListWidgetItem(self._display_path(path, preferred_library))
            item.setData(Qt.ItemDataRole.UserRole, path)
            # Explicitly set size hint to prevent overlap
            item.setSizeHint(QSize(0, 24))
            self.list_widget.addItem(item)
            if initial_path and path == initial_path:
                selected_row = index

        layout.addWidget(self.list_widget)

        # Remembering a choice only preselects it; users with multiple
        # libraries still get the dialog and can change the destination.
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(selected_row)
            self.list_widget.itemDoubleClicked.connect(lambda _item: self.accept())

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

        self.selected_path = current_item.data(Qt.ItemDataRole.UserRole) or current_item.text()
        logger.info(f"User selected Steam library: {self.selected_path}")
        super().accept()

    def get_selected_path(self) -> Optional[str]:
        """Return the selected library path."""
        return self.selected_path

    @staticmethod
    def _display_path(path: str, preferred_library: Optional[str] = None) -> str:
        label = "Steam em uso" if path == preferred_library else "biblioteca extra"
        if "/.var/app/com.valvesoftware.Steam/" in path:
            label += " / Flatpak"
        elif "/snap/steam/" in path:
            label += " / Snap"
        else:
            label += " / Native"
        return f"{path}  [{label}]"
