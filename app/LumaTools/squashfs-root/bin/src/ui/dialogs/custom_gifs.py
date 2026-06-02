import logging
import os
import shutil
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QGroupBox,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

from utils.settings import get_settings
from utils.helpers import get_base_path, create_checkbox_setting
from ui.dialogs.dialog_helpers import create_standard_buttons

logger = logging.getLogger(__name__)


class CustomGifItem(QWidget):
    def __init__(self, gif_name, parent_dialog):
        super().__init__()
        self.gif_name = gif_name
        self.parent_dialog = parent_dialog
        self.original_file_path = None
        self.temp_file_path = None

        self.main_layout = QHBoxLayout(self)

        # GIF name label - apply display name mapping
        display_name = CustomGifItem.get_display_name(gif_name)
        self.name_label = QLabel(display_name)
        self.name_label.setMinimumWidth(200)

        # Current file display
        self.current_file_label = QLabel("Nenhum arquivo personalizado")
        self.current_file_label.setStyleSheet("color: #888888; font-style: italic;")

        # View button
        self.view_button = QPushButton("Ver")
        self.view_button.clicked.connect(self.view_gif)
        self.view_button.setEnabled(False)
        self.view_button.setFixedWidth(80)

        # Upload button
        self.upload_button = QPushButton("Enviar")
        self.upload_button.clicked.connect(self.upload_gif)
        self.upload_button.setFixedWidth(80)

        # Remove button
        self.remove_button = QPushButton("Remover")
        self.remove_button.clicked.connect(self.remove_gif)
        self.remove_button.setEnabled(False)
        self.remove_button.setFixedWidth(80)

        self.main_layout.addWidget(self.name_label)
        self.main_layout.addWidget(self.current_file_label)
        self.main_layout.addWidget(self.view_button)
        self.main_layout.addWidget(self.upload_button)
        self.main_layout.addWidget(self.remove_button)

        # Check if custom file already exists
        self.check_existing_custom()

    @staticmethod
    def get_display_name(gif_name):
        """Get the display name for a GIF based on the filename"""
        if gif_name == "main.gif":
            return "Inativo"
        elif gif_name == "navi.gif":
            return "Logo da barra de título"
        elif gif_name.startswith("downloading_custom") and gif_name.endswith(".gif"):
            # Extract the number from downloading_custom{i}.gif
            num_part = gif_name[18:-4]  # Remove "downloading" and ".gif"
            return f"Downloading: {num_part}"
        else:
            return gif_name

    @staticmethod
    def truncate_filename(filename):
        """Truncate filename if longer than 13 characters"""
        if len(filename) > 13:
            return filename[:10] + "..."
        return filename

    def check_existing_custom(self):
        """Check if a custom version of this GIF already exists"""
        custom_dir = CustomGifItem.get_custom_dir()
        custom_path = os.path.join(custom_dir, self.gif_name)

        if os.path.exists(custom_path):
            self.original_file_path = custom_path
            self.current_file_label.setText("Personalizado aplicado")
            self.current_file_label.setStyleSheet("color: #4CAF50;")
            self.remove_button.setEnabled(True)
            self.view_button.setEnabled(True)
            self.upload_button.setText("Substituir")

    @staticmethod
    def get_custom_dir():
        """Get the custom GIF directory"""
        custom_dir = get_base_path() / "gifs" / "custom"
        custom_dir.mkdir(parents=True, exist_ok=True)
        return str(custom_dir)

    def upload_gif(self):
        """Handle GIF file upload"""
        # Allow all common image formats
        image_extensions = {
            "*.gif",
            "*.png",
            "*.jpg",
            "*.jpeg",
            "*.bmp",
            "*.tiff",
            "*.tif",
            "*.webp",
            "*.svg",
            "*.ico",
            "*.ppm",
            "*.pgm",
            "*.pbm",
            "*.pnm",
        }

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Selecionar GIF para {self.gif_name}",
            os.path.expanduser("~"),
            f"Arquivos de imagem ({' '.join(sorted(image_extensions))});;Todos os arquivos (*)",
        )

        if not file_path:
            return

        # Validate file extension
        file_ext = f"*{os.path.splitext(file_path)[1].lower()}"
        if file_ext not in image_extensions:
            QMessageBox.warning(
                self,
                "Arquivo inválido",
                f"Selecione um arquivo de imagem. Formatos compatíveis: {', '.join(sorted(image_extensions))}",
            )
            return

        # Copy to temporary location first
        temp_dir = self.parent_dialog.get_temp_dir()
        self.temp_file_path = os.path.join(temp_dir, self.gif_name)

        try:
            shutil.copy2(file_path, self.temp_file_path)
            filename = os.path.basename(file_path)
            display_filename = CustomGifItem.truncate_filename(filename)
            self.current_file_label.setText(f"Temporário: {display_filename}")
            self.current_file_label.setStyleSheet("color: #FF9800;")
            self.remove_button.setEnabled(True)
            self.view_button.setEnabled(True)
            self.upload_button.setText("Substituir")
            logger.info(f"Temporary upload for {self.gif_name}: {file_path}")
        except Exception as e:
            QMessageBox.critical(
                self, "Erro de envio", f"Falha ao enviar o GIF: {str(e)}"
            )
            logger.error(f"Failed to upload GIF for {self.gif_name}: {e}")

    def remove_gif(self):
        """Remove the custom/temporary GIF"""
        is_download_gif = self.gif_name.startswith(
            "downloading_custom"
        ) and self.gif_name.endswith(".gif")

        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.remove(self.temp_file_path)
                self.temp_file_path = None
            except Exception as e:
                logger.error(f"Failed to remove temp file for {self.gif_name}: {e}")

        if self.original_file_path and os.path.exists(self.original_file_path):
            try:
                os.remove(self.original_file_path)
                self.original_file_path = None
            except Exception as e:
                logger.error(f"Failed to remove custom file for {self.gif_name}: {e}")

        self.current_file_label.setText("Nenhum arquivo personalizado")
        self.current_file_label.setStyleSheet("color: #888888; font-style: italic;")
        self.remove_button.setEnabled(False)
        self.view_button.setEnabled(False)
        self.upload_button.setText("Enviar")

        # Notify parent dialog if it's a download GIF
        if is_download_gif and self.parent_dialog:
            # Check if this item should be completely removed from the UI
            # (it's a download GIF with no custom file anymore)
            if not self.original_file_path and not self.temp_file_path:
                # Remove this widget from the parent dialog
                self.parent_dialog.remove_download_gif_item(self)

    def view_gif(self):
        """View the current GIF/image in a dialog"""
        # Determine which file to show (temp file takes precedence, then original)
        file_to_show = None
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            file_to_show = self.temp_file_path
        elif self.original_file_path and os.path.exists(self.original_file_path):
            file_to_show = self.original_file_path

        if not file_to_show:
            QMessageBox.warning(self, "Nenhum arquivo", "Não há arquivo personalizado para visualizar.")
            return

        # Create and show the view dialog
        view_dialog = QDialog(self)
        view_dialog.setWindowTitle(f"Visualizando: {os.path.basename(file_to_show)}")
        view_dialog.setMinimumSize(400, 400)

        layout = QVBoxLayout(view_dialog)

        # Create label to display the image
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Load and display the image
        pixmap = QPixmap(file_to_show)
        if pixmap.isNull():
            QMessageBox.warning(self, "Erro", "Não foi possível carregar o arquivo de imagem.")
            return

        # Scale the image to fit the dialog while maintaining aspect ratio
        scaled_pixmap = pixmap.scaled(
            380,
            380,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        image_label.setPixmap(scaled_pixmap)

        # Add image info
        info_text = f"Arquivo: {os.path.basename(file_to_show)}\n"
        info_text += f"Tamanho: {pixmap.width()} x {pixmap.height()}\n"
        info_text += f"Caminho: {file_to_show}"
        info_label = QLabel(info_text)
        info_label.setWordWrap(True)

        # OK button
        ok_button = QPushButton("OK")
        ok_button.clicked.connect(view_dialog.accept)

        layout.addWidget(image_label)
        layout.addWidget(info_label)
        layout.addWidget(ok_button, alignment=Qt.AlignmentFlag.AlignCenter)

        view_dialog.exec()

    def apply_changes(self):
        """Apply temporary changes to permanent location"""
        if not self.temp_file_path or not os.path.exists(self.temp_file_path):
            # No temporary file, nothing to apply
            return True

        try:
            custom_dir = CustomGifItem.get_custom_dir()
            permanent_path = os.path.join(custom_dir, self.gif_name)

            # Remove existing custom file if it exists
            if os.path.exists(permanent_path):
                os.remove(permanent_path)

            # Move temp file to permanent location
            shutil.move(self.temp_file_path, permanent_path)
            self.original_file_path = permanent_path
            self.temp_file_path = None

            self.current_file_label.setText("Personalizado aplicado")
            self.current_file_label.setStyleSheet("color: #4CAF50;")
            self.view_button.setEnabled(True)
            logger.info(f"Applied custom GIF for {self.gif_name}: {permanent_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to apply changes for {self.gif_name}: {e}")
            return False

    def rollback_changes(self):
        """Rollback temporary changes"""
        if self.temp_file_path and os.path.exists(self.temp_file_path):
            try:
                os.remove(self.temp_file_path)
                self.temp_file_path = None
                logger.info(f"Rolled back temporary file for {self.gif_name}")
            except Exception as e:
                logger.error(f"Failed to rollback temp file for {self.gif_name}: {e}")


class CustomGifsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = get_settings()
        self.setWindowTitle("GIFs personalizados")
        self.setMinimumWidth(600)
        self.setMinimumHeight(400)
        self.resize(700, 500)

        self.main_window = parent
        self.gif_items = []
        self.default_gifs_checkbox = None
        self.disable_color_gifs_checkbox = None
        self.content_widget = None
        self.content_layout = None
        self.standard_gifs = []
        self.download_gifs = []
        self.next_download_num = 0
        self.next_download_label = None

        self.setup_ui()

    def setup_ui(self):
        """Setup the dialog UI"""
        layout = QVBoxLayout(self)

        # Title and description
        title_label = QLabel("Gerenciamento de GIFs personalizados")
        title_label.setStyleSheet(
            "font-size: 24px; font-weight: bold; margin-bottom: 10px;"
        )
        layout.addWidget(title_label)

        desc_label = QLabel(
            f"Envie GIFs personalizados para substituir os padrões.\nOs GIFs personalizados ficam em:\n{get_base_path() / 'gifs' / 'custom'}"
        )
        desc_label.setStyleSheet("color: #888888; margin-bottom: 20px;")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        self.default_gifs_checkbox = create_checkbox_setting(
            "Desativar GIFs padrão de download",
            "disable_default_gifs",
            False,
            self,
            "Desativa os GIFs padrão de download da Lain",
        )
        layout.addWidget(self.default_gifs_checkbox)

        self.disable_color_gifs_checkbox = create_checkbox_setting(
            "Desativar coloração dos GIFs pela cor de destaque",
            "disable_color_gifs",
            False,
            self,
            "Desativa a recoloração dos GIFs com base na cor de destaque",
        )
        layout.addWidget(self.disable_color_gifs_checkbox)

        # Scrollable area for GIF items
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)

        # Create GIF items
        self.create_gif_items()

        # Add new download GIF section
        self.add_new_download_section()

        self.content_layout.addStretch()
        scroll.setWidget(self.content_widget)
        layout.addWidget(scroll)

        # Dialog buttons
        buttons = create_standard_buttons(self.accept, self.reject)
        layout.addWidget(buttons)

    def create_gif_items(self):
        """Create items for each GIF type"""
        # Standard GIFs - just filenames
        self.standard_gifs = ["main.gif", "navi.gif"]

        # Download GIFs - get just the filenames from custom directory
        custom_dir = get_base_path() / "gifs/custom"
        os.makedirs(str(custom_dir), exist_ok=True)

        # Get just the filenames, not full paths
        self.download_gifs = sorted(
            [p.name for p in custom_dir.glob("downloading_custom*.gif")]
        )

        all_gifs = self.standard_gifs + self.download_gifs

        for gif_name in all_gifs:
            item = CustomGifItem(gif_name, self)
            self.gif_items.append(item)
            self.content_layout.addWidget(item)

    def add_new_download_section(self):
        """Add section for adding new download GIF slots"""
        group = QGroupBox("Adicionar mais slots de GIF de download")
        group_layout = QHBoxLayout(group)

        add_button_layout = QHBoxLayout()

        # Calculate the next available number (highest existing number + 1)
        max_num = -1
        for gif_name in self.download_gifs:
            if gif_name.startswith("downloading_custom") and gif_name.endswith(".gif"):
                try:
                    num = int(
                        gif_name[18:-4]
                    )  # Extract number from "downloading_customX.gif"
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass

        self.next_download_num = max_num + 1
        self.next_download_label = QLabel(
            f"Próximo: downloading_custom{self.next_download_num}.gif"
        )

        add_button = QPushButton("Adicionar novo GIF de download")
        add_button.clicked.connect(self.add_download_gif)

        add_button_layout.addWidget(self.next_download_label)
        add_button_layout.addWidget(add_button)

        group_layout.addLayout(add_button_layout)
        self.content_layout.addWidget(group)

    def add_download_gif(self):
        """Add a new download GIF slot"""
        # First, check if we need to renumber
        self.renumber_download_gifs()

        # Check if there are existing download GIF items in the UI
        download_items = self._get_download_items()

        # If there are existing download items, check the last one
        if download_items:
            last_item = download_items[-1]

            # Check if the last item has a file (either original saved or temporary uploaded)
            if not last_item.original_file_path and not last_item.temp_file_path:
                QMessageBox.warning(
                    self,
                    "Slot anterior vazio",
                    f"Envie um GIF ou imagem para o slot anterior ({last_item.gif_name}) antes de adicionar um novo.",
                )
                return

        gif_name = f"downloading_custom{self.next_download_num}.gif"

        item = CustomGifItem(gif_name, self)
        self.gif_items.append(item)

        # Also add to the download_gifs list to keep track
        self.download_gifs.append(gif_name)

        # Insert before the stretch and the "Add More" section
        self.content_layout.insertWidget(self.content_layout.count() - 2, item)

        self.next_download_num += 1
        self.next_download_label.setText(
            f"Próximo: downloading_custom{self.next_download_num}.gif"
        )

        logger.info(f"Added new download GIF slot: {gif_name}")

    def remove_download_gif_item(self, item_to_remove):
        """Remove a download GIF item from the UI and renumber the rest"""
        # Remove the widget from the layout
        self.content_layout.removeWidget(item_to_remove)
        item_to_remove.setParent(None)

        # Remove from the gif_items list
        if item_to_remove in self.gif_items:
            self.gif_items.remove(item_to_remove)

        # Remove from the download_gifs list
        if item_to_remove.gif_name in self.download_gifs:
            self.download_gifs.remove(item_to_remove.gif_name)

        # Renumber the remaining download GIFs
        self.renumber_download_gifs()

        logger.info(f"Removed download GIF item: {item_to_remove.gif_name}")

    @staticmethod
    def get_temp_dir():
        """Get temporary directory for uploads"""
        temp_dir = get_base_path() / "gifs" / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return str(temp_dir)

    def _get_download_items(self):
        download_items = [
            item
            for item in self.gif_items
            if item.gif_name.startswith("downloading_custom")
            and item.gif_name.endswith(".gif")
        ]
        download_items.sort(
            key=lambda item: (
                int(item.gif_name[18:-4]) if item.gif_name[18:-4].isdigit() else 0
            )
        )
        return download_items

    def _cleanup_temp_dir(self):
        temp_dir = self.get_temp_dir()
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.warning(f"Failed to clean up temp directory: {e}")

    def renumber_download_gifs(self):
        """Renumber download GIFs to maintain sequential order without gaps"""
        # Get all download GIF items
        download_items = self._get_download_items()

        # Check if we have gaps in the numbering
        needs_renumbering = False

        for i, item in enumerate(download_items):
            current_num = (
                int(item.gif_name[18:-4]) if item.gif_name[18:-4].isdigit() else 0
            )
            if current_num != i:
                needs_renumbering = True
                break

        # If no gaps, we're done
        if not needs_renumbering:
            # Still need to update next_download_num based on highest existing number
            max_num = -1
            for item in download_items:
                try:
                    num = int(item.gif_name[18:-4])
                    if num > max_num:
                        max_num = num
                except ValueError:
                    pass
            self.next_download_num = max_num + 1
            self.next_download_label.setText(
                f"Próximo: downloading_custom{self.next_download_num}.gif"
            )
            return

        # Renumber all download GIFs
        for i, item in enumerate(download_items):
            old_name = item.gif_name
            new_name = f"downloading_custom{i}.gif"

            if old_name != new_name:
                # Update the item's gif_name
                item.gif_name = new_name

                # Update display name
                display_name = CustomGifItem.get_display_name(new_name)
                item.name_label.setText(display_name)

                # If there's an original file, rename it
                if item.original_file_path and os.path.exists(item.original_file_path):
                    custom_dir = CustomGifItem.get_custom_dir()
                    new_path = os.path.join(custom_dir, new_name)
                    try:
                        os.rename(item.original_file_path, new_path)
                        item.original_file_path = new_path
                        logger.info(f"Renamed {old_name} to {new_name}")
                    except Exception as e:
                        logger.error(f"Failed to rename {old_name} to {new_name}: {e}")

                # If there's a temp file, rename it
                if item.temp_file_path and os.path.exists(item.temp_file_path):
                    temp_dir = self.get_temp_dir()
                    new_temp_path = os.path.join(temp_dir, new_name)
                    try:
                        os.rename(item.temp_file_path, new_temp_path)
                        item.temp_file_path = new_temp_path
                    except Exception as e:
                        logger.error(
                            f"Failed to rename temp file {old_name} to {new_name}: {e}"
                        )

        # Update the download_gifs list
        self.download_gifs = [item.gif_name for item in download_items]

        # Update next download number (highest number + 1)
        if download_items:
            max_num = len(download_items) - 1  # Since we just renumbered sequentially
        else:
            max_num = -1

        self.next_download_num = max_num + 1
        self.next_download_label.setText(
            f"Próximo: downloading_custom{self.next_download_num}.gif"
        )

        logger.info(f"Renumbered download GIFs. Next number: {self.next_download_num}")

    def accept(self):
        """Handle OK button - apply all changes and reload GIFs"""
        if self.main_window:
            if hasattr(self.main_window, "ui_state") and self.main_window.ui_state:
                self.main_window.ui_state.disable_default_gifs = (
                    self.default_gifs_checkbox.isChecked()
                )
                self.main_window.ui_state.initialize_gifs()
                self.settings.setValue(
                    "disable_default_gifs",
                    self.main_window.ui_state.disable_default_gifs,
                )

            if (
                hasattr(self.main_window, "gif_manager")
                and self.main_window.gif_manager
            ):
                self.main_window.gif_manager.disable_color_gifs = (
                    self.disable_color_gifs_checkbox.isChecked()
                )
                self.settings.setValue(
                    "disable_color_gifs",
                    self.main_window.gif_manager.disable_color_gifs,
                )

        # Apply all changes
        failed_items = []
        for item in self.gif_items:
            if not item.apply_changes():
                failed_items.append(item.gif_name)

        if failed_items:
            QMessageBox.warning(
                self,
                "Sucesso parcial",
                f"Falha ao aplicar alterações para: {', '.join(failed_items)}\n"
                "As outras alterações foram aplicadas com sucesso.",
            )

        # Clean up temp directory
        self._cleanup_temp_dir()

        # Don't reload GIFs here - let the main Settings dialog handle it
        # Just show success message
        logger.info("Custom GIFs applied successfully")
        QMessageBox.information(
            self,
            "Sucesso",
            "Os GIFs personalizados foram aplicados.\n\nClique em OK novamente para recarregá-los.",
        )

        super().accept()

    def reject(self):
        """Handle Cancel button - rollback all changes"""
        # Rollback all changes
        for item in self.gif_items:
            item.rollback_changes()

        # Clean up temp directory
        self._cleanup_temp_dir()

        logger.info("Custom GIF changes cancelled and rolled back")
        super().reject()
