import os
import random
import logging
from pathlib import Path
from typing import cast
from PyQt6.QtCore import QSize, QTimer
from PyQt6.QtGui import QColor, QMovie, QFont
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QFrame,
)

from core.visual_presets import get_visual_preset
from managers.gif_manager import GIF_CACHE_VERSION
from utils.helpers import get_base_path
from utils.paths import Paths

logger = logging.getLogger(__name__)

DEFAULT_DOWNLOAD_GIF_PATTERN = "downloading_default*.gif"
DEFAULT_DOWNLOAD_GIF_PREFIX = "downloading_default"


def resolve_default_download_gifs(
    colored_dir: Path, resource_dir: Path
) -> list[str]:
    colorized_defaults = sorted(colored_dir.glob(DEFAULT_DOWNLOAD_GIF_PATTERN))
    resource_defaults = sorted(resource_dir.glob(DEFAULT_DOWNLOAD_GIF_PATTERN))
    return [str(path) for path in (colorized_defaults or resource_defaults)]


def resolve_visual_preset_gif_dir(settings) -> Path:
    preset = get_visual_preset(settings.value("visual_preset", "hellgirl", type=str))
    if preset.gif_dir.exists():
        return preset.gif_dir
    return Paths.resource("gif")


def colorized_cache_matches_visual_preset(settings, colored_dir: Path) -> bool:
    current = get_visual_preset(
        settings.value("visual_preset", "hellgirl", type=str)
    ).key
    marker = colored_dir / "active_visual_preset.txt"
    if not marker.exists():
        return current == "hellgirl"
    try:
        return marker.read_text(encoding="utf-8").strip() == current
    except OSError:
        return False


class UIStateManager:
    def __init__(self, main_window):
        self.main_window = main_window
        self.settings = main_window.settings

        # UI state
        self.fetch_dialog = None
        self.depot_dialog = None
        self.current_movie = None
        self.random_gif_path = None
        self.download_movie = None
        self.main_movie = None
        self.current_movie_path = None

        # Queue UI elements
        self.queue_widget = None
        self.queue_list_widget = None
        self.queue_move_up_button = None
        self.queue_move_down_button = None
        self.queue_remove_button = None
        self.pause_button = None
        self.cancel_button = None

        self.disable_default_gifs = self.settings.value("disable_default_gifs", False)
        self._gif_refresh_timer = None

        self._initialize_gifs()
        # Gifs are set up later in apply_style_settings()

    def _is_compact_screen(self) -> bool:
        screen = QApplication.primaryScreen()
        if not screen:
            return False
        geometry = screen.availableGeometry()
        return geometry.height() <= 800 or geometry.width() <= 1280

    def _apply_movie_size(self, movie: QMovie) -> None:
        # We don't scale the QMovie object itself because Qt's internal movie scaling
        # results in pixelated/low-quality rendering. The ScaledLabel widget handles
        # smooth scaling on every frame draw instead.
        pass

    def _initialize_gifs(self):
        """Initialize GIF resources"""
        colored_dir = get_base_path() / "gifs/colorized"
        os.makedirs(str(colored_dir), exist_ok=True)

        self.remove_old_downloading_gifs()

        # Custom downloading GIFs (excluding defaults)
        custom_patterns = ["downloading_custom*.gif"]
        self.download_gifs = []
        for pattern in custom_patterns:
            for p in colored_dir.glob(pattern):
                if not p.name.lower().startswith(DEFAULT_DOWNLOAD_GIF_PREFIX):
                    self.download_gifs.append(str(p))

        # Default downloading GIFs
        default_colored_dir = (
            colored_dir
            if colorized_cache_matches_visual_preset(self.settings, colored_dir)
            else Path()
        )
        self.default_download_gifs = resolve_default_download_gifs(
            default_colored_dir,
            resolve_visual_preset_gif_dir(self.settings),
        )

        # Sort both lists
        self.download_gifs.sort()
        self.default_download_gifs.sort()

        logger.debug(f"Found {len(self.download_gifs)} custom GIFs")
        logger.debug(f"Found {len(self.default_download_gifs)} default GIFs")

    def initialize_gifs(self):
        self._initialize_gifs()

    @staticmethod
    def remove_old_downloading_gifs():
        """Remove old downloading*.gif files and rename custom ones to sequential names"""
        total_removed = 0
        total_renamed = 0

        gifs_base = get_base_path() / "gifs"

        if not gifs_base.exists():
            logger.warning(f"Directory does not exist: {gifs_base}")
            return {"removed": 0, "renamed": 0}

        # Remove old downloading*.gif files
        colorized_dir = gifs_base / "colorized"

        if colorized_dir.exists() and colorized_dir.is_dir():
            removed_count = 0
            for file_path in colorized_dir.rglob("downloading*.gif"):
                # Preserve bundled defaults and user-provided custom GIFs.
                filename_lower = file_path.name.lower()
                if (
                    filename_lower.startswith(DEFAULT_DOWNLOAD_GIF_PREFIX)
                    or "downloading_custom" in filename_lower
                ):
                    continue

                try:
                    file_path.unlink()
                    removed_count += 1
                    logger.info(f"Removed from colorized: {file_path}")
                except Exception as e:
                    logger.error(f"Failed to remove {file_path}: {e}")

            total_removed += removed_count
            if removed_count > 0:
                logger.info(
                    f"Removed {removed_count} downloading*.gif files from colorized"
                )
        else:
            logger.warning(f"Colorized directory does not exist: {colorized_dir}")

        # Rename old downloading*.gif files
        custom_dir = gifs_base / "custom"

        if custom_dir.exists() and custom_dir.is_dir():
            # Find generic downloading*.gif files, excluding known slots.
            files_to_rename = []
            for file_path in custom_dir.rglob("downloading*.gif"):
                filename_lower = file_path.name.lower()
                if (
                    "_custom" not in filename_lower
                    and not filename_lower.startswith(DEFAULT_DOWNLOAD_GIF_PREFIX)
                ):
                    files_to_rename.append(file_path)

            if files_to_rename:
                # Sort the files (case-insensitive)
                files_to_rename.sort(key=lambda x: x.name.lower())

                # Find existing downloading_custom*.gif files to determine used indices
                used_indices = set()
                for file_path in custom_dir.rglob("downloading_custom*.gif"):
                    try:
                        # Extract number from filename: downloading_custom{number}.gif
                        stem = file_path.stem
                        if stem.lower().startswith("downloading_custom"):
                            num_str = stem[18:]  # Remove "downloading_custom"
                            if num_str and num_str.isdigit():
                                used_indices.add(int(num_str))
                    except (ValueError, AttributeError, IndexError):
                        pass

                # Rename files in sequence
                renamed_count = 0
                for file_path in files_to_rename:
                    try:
                        # Find next available index
                        index = 1
                        while index in used_indices:
                            index += 1

                        new_name = f"downloading_custom{index}.gif"
                        new_path = file_path.parent / new_name

                        # Rename the file
                        file_path.rename(new_path)
                        renamed_count += 1
                        used_indices.add(index)  # Mark this index as used
                        logger.info(f"Renamed: {file_path.name} -> {new_name}")

                    except Exception as e:
                        logger.error(f"Failed to rename {file_path}: {e}")

                total_renamed = renamed_count
                if renamed_count > 0:
                    logger.info(
                        f"Renamed {renamed_count} downloading*.gif files to sequential names"
                    )
            else:
                logger.info("No files to rename in custom directory")
        else:
            logger.warning(f"Custom directory does not exist: {custom_dir}")

        logger.info(
            f"Total: {total_removed} files removed, {total_renamed} files renamed"
        )
        return {"removed": total_removed, "renamed": total_renamed}

    def _current_colorized_dir(self) -> Path:
        return get_base_path() / "gifs" / "colorized" / self.main_window.accent_color.lstrip("#")

    def _colorized_cache_ready(self) -> bool:
        colored_dir = get_base_path() / "gifs" / "colorized"
        main_link = colored_dir / "main.gif"
        expected_dir = self._current_colorized_dir()
        if not main_link.exists() or not expected_dir.exists():
            return False
        if not colorized_cache_matches_visual_preset(self.settings, colored_dir):
            return False

        try:
            if main_link.resolve().parent != expected_dir.resolve():
                return False
        except OSError:
            return False

        setting_file = expected_dir / "disable_color_gifs_setting.txt"
        try:
            previous = setting_file.read_text(encoding="utf-8").strip()
        except OSError:
            return False
        expected = "1" if bool(self.main_window.gif_manager.disable_color_gifs) else "0"
        try:
            processor_version = (
                expected_dir / "gif_processor_version.txt"
            ).read_text(encoding="utf-8").strip()
        except OSError:
            return False
        return (
            previous == expected
            and processor_version == GIF_CACHE_VERSION
            and (expected_dir / "hashes.json").exists()
        )

    def _preferred_main_gif_path(self) -> Path:
        colored_dir = get_base_path() / "gifs" / "colorized"
        main_gif_path = colored_dir / "main.gif"
        preset_gif_dir = resolve_visual_preset_gif_dir(self.settings)
        default_gif_path = preset_gif_dir / "main.gif"
        if not default_gif_path.exists():
            default_gif_path = Paths.resource("gif/main.gif")

        ui_mode = self.settings.value("ui_mode", "default")
        if ui_mode == "sonic":
            sonic_gif = Paths.resource("sonic/gifs/main.gif")
            return sonic_gif if sonic_gif.exists() else default_gif_path

        if self._colorized_cache_ready() and main_gif_path.exists():
            return main_gif_path
        return default_gif_path

    def _set_movie(self, movie_path: Path, *, force: bool = False) -> None:
        movie_path = movie_path.resolve()
        movie_key = str(movie_path)
        if (
            not force
            and self.current_movie_path == movie_key
            and self.current_movie
            and self.current_movie.isValid()
        ):
            if self.current_movie.state() != QMovie.MovieState.Running:
                self.current_movie.start()
            return

        movie = QMovie(movie_key)
        movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self._apply_movie_size(movie)
        if not movie.isValid():
            logger.error("Failed to load GIF: %s", movie_key)
            return

        previous_movie = self.current_movie
        self.main_window.drop_zone_gif.setMovie(movie)
        movie.start()

        self.main_movie = movie
        self.current_movie = movie
        self.current_movie_path = movie_key
        if previous_movie and previous_movie is not movie:
            previous_movie.stop()

    def _update_gifs(self):
        """Update GIFs with current accent color"""
        output_dir = get_base_path() / "gifs" / "colorized"
        self.main_window.gif_manager.process_gif_batch(
            output_dir, self.main_window.accent_color, silent=True
        )
        if not self.main_window.gif_manager._is_processing:
            self._reload_movies(force=True)

    def _schedule_gif_refresh(self, delay_ms=350):
        timer = self._gif_refresh_timer
        if timer is None:
            timer = QTimer(self.main_window)
            timer.setSingleShot(True)
            timer.timeout.connect(self._update_gifs)
            self._gif_refresh_timer = timer
        timer.start(max(0, delay_ms))

    def update_gifs(self, force: bool = False):
        # Keep the currently running QMovie alive whenever possible. Rebuilding
        # it at startup restarts the animation and creates a visible blink.
        self._reload_movies(force=force)
        if force or self.main_window.gif_manager.regenerate_anyway or not self._colorized_cache_ready():
            self._schedule_gif_refresh(600)

    def _reload_movies(self, force: bool = False):
        """Reload movie objects with current GIFs"""
        if not hasattr(self.main_window, "drop_zone_gif"):
            return
        if self.main_window.task_manager.current_job:
            if force:
                self.main_movie = None
            self.switch_to_download_gif()
            return

        self._set_movie(self._preferred_main_gif_path(), force=force)

    def reload_movies(self):
        self._initialize_gifs()
        self._reload_movies(force=True)

    def setup_queue_panel(self):
        """Setup the download queue panel"""
        self.queue_widget = QWidget()
        queue_layout = QVBoxLayout(self.queue_widget)
        queue_layout.setContentsMargins(0, 0, 5, 0)

        # Queue label
        queue_label = QLabel("Fila de downloads")
        queue_label.setStyleSheet(f"color: {self.main_window.accent_color};")
        queue_layout.addWidget(queue_label)

        # Queue list
        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setToolTip(
            "Fila atual de downloads. Selecione um item para movê-lo."
        )
        queue_layout.addWidget(self.queue_list_widget)

        # Queue buttons
        self._setup_queue_buttons(queue_layout)

    def _setup_queue_buttons(self, parent_layout):
        """Setup queue control buttons"""
        queue_button_layout = QHBoxLayout()

        self.queue_move_up_button = QPushButton("Subir")
        self.queue_move_up_button.clicked.connect(
            self.main_window.job_queue.move_item_up
        )
        queue_button_layout.addWidget(self.queue_move_up_button)

        self.queue_move_down_button = QPushButton("Descer")
        self.queue_move_down_button.clicked.connect(
            self.main_window.job_queue.move_item_down
        )
        queue_button_layout.addWidget(self.queue_move_down_button)

        self.queue_remove_button = QPushButton("Remover")
        self.queue_remove_button.clicked.connect(self.main_window.job_queue.remove_item)
        queue_button_layout.addWidget(self.queue_remove_button)

        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.main_window.task_manager.toggle_pause)
        self.pause_button.setVisible(False)
        queue_button_layout.addWidget(self.pause_button)

        self.cancel_button = QPushButton("Cancelar")
        self.cancel_button.clicked.connect(
            self.main_window.task_manager.cancel_current_job
        )
        self.cancel_button.setVisible(False)
        queue_button_layout.addWidget(self.cancel_button)

        parent_layout.addLayout(queue_button_layout)

    def apply_style_settings(self):
        """Apply current style settings to UI"""
        self.main_window.background_color = self.settings.value(
            "background_color", "#000000"
        )
        self.main_window.accent_color = self.settings.value("accent_color", "#C06C84")

        # Load font family
        font_family = self.settings.value("font", "TrixieCyrG-Plain")

        # Keep the visual style, but enforce a readable floor.
        font_size = max(12, self.settings.value("font-size", 10, type=int))

        # Create font
        font = QFont(font_family)
        font.setPointSize(font_size)

        # Set font style
        font_style = self.settings.value("font-style", "Normal")
        if font_style == "Italic":
            font.setItalic(True)
        elif font_style == "Bold":
            font.setBold(True)
        elif font_style == "Bold Italic":
            font.setBold(True)
            font.setItalic(True)
        # "Normal" is the default, so no changes needed

        self.main_window.font = font

        # Update application appearance
        from main import update_appearance

        # UI mode (e.g., 'sonic') may override colors and font file
        ui_mode = self.settings.value("ui_mode", "default")

        font_file = None
        if ui_mode == "sonic":
            # Sonic mode: use specific palette (blue background, yellow accent)
            self.main_window.accent_color = "#ffcc00"
            self.main_window.background_color = "#002c83"
            font_file = self.settings.value("font-file", "sonic/sonic-1-hud-font.otf")

        font_ok, font_info = update_appearance(
            cast(QApplication, QApplication.instance()),
            self.main_window.accent_color,
            self.main_window.background_color,
            self.main_window.font,
            font_file=font_file,
        )

        if ui_mode == "sonic" and font_ok:
            # Sync main window font family to loaded Sonic font
            sonic_font = QFont(font_info)
            sonic_font.setPointSize(font_size)
            self.main_window.font = sonic_font

        # Apply styles to various UI elements
        self._apply_background_color()
        self._apply_accent_color()
        self.update_gifs()

    def _apply_background_color(self):
        """Apply background color to main content"""
        background = self.main_window.background_color
        accent = self.main_window.accent_color
        background_color = QColor(background)
        accent_color = QColor(accent)
        if not background_color.isValid():
            background_color = QColor("#000000")
        if not accent_color.isValid():
            accent_color = QColor("#C06C84")

        surface_color = (
            QColor("#0B0B0E")
            if background_color.lightness() < 24
            else background_color.lighter(108)
        )
        border = (
            f"rgba({accent_color.red()}, {accent_color.green()}, "
            f"{accent_color.blue()}, 72)"
        )
        muted = (
            f"rgba({accent_color.red()}, {accent_color.green()}, "
            f"{accent_color.blue()}, 150)"
        )

        for widget_name in ("content_frame", "progress_container"):
            widget = getattr(self.main_window, widget_name, None)
            if widget is not None:
                widget.setStyleSheet(f"background-color: {background};")

        self.main_window.central_widget.setStyleSheet(
            f"#central_widget {{ background-color: {background}; "
            f"border: 1px solid {border}; }}"
        )
        self.main_window.drop_zone_container.setStyleSheet(
            "#drop_zone_container { "
            f"background-color: {surface_color.name()}; "
            f"border: 1px solid {border}; "
            "border-radius: 6px; "
            "}"
        )
        if hasattr(self.main_window, "activity_header"):
            self.main_window.activity_header.setStyleSheet(
                "#activity_header { background-color: transparent; border: none; }"
            )

        if hasattr(self.main_window, "drop_zone_gif"):
            self.main_window.drop_zone_gif.setProperty(
                "background_color", surface_color.name()
            )
            self.main_window.drop_zone_gif.setStyleSheet(
                f"background-color: {surface_color.name()}; border: none;"
            )
            self.main_window.drop_zone_gif.update()
        if hasattr(self.main_window, "log_output"):
            self.main_window.log_output.setStyleSheet(
                "QTextEdit { "
                f"background-color: {surface_color.name()}; "
                f"color: {accent}; "
                f"selection-background-color: {accent}; "
                f"selection-color: {background}; "
                f"border: 1px solid {border}; "
                "border-radius: 4px; "
                "padding: 8px 10px; "
                "font-size: 10pt; "
                "font-family: 'DejaVu Sans Mono'; "
                "}"
                "QScrollBar:vertical { "
                f"background: {surface_color.name()}; width: 8px; margin: 2px; "
                "}"
                "QScrollBar::handle:vertical { "
                f"background: {muted}; min-height: 24px; border-radius: 3px; "
                "}"
                "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { "
                "height: 0px; "
                "}"
            )

    def _apply_accent_color(self):
        """Apply accent color to UI elements"""
        accent_style = (
            f"color: {self.main_window.accent_color}; font-size: 12pt; "
            "font-weight: 600; letter-spacing: 0px;"
        )

        # Drop text label
        self.main_window.drop_text_label.setStyleSheet(accent_style)

        # Queue label
        if hasattr(self, "queue_widget") and self.queue_widget:
            queue_label = self.queue_widget.findChild(QLabel)
            if queue_label:
                queue_label.setStyleSheet(accent_style)

        # Progress bar
        self.main_window.update_progress_bar_style()

        if hasattr(self.main_window, "activity_label"):
            self.main_window.activity_label.setStyleSheet(
                f"color: {self.main_window.accent_color}; font-size: 9pt; "
                "font-weight: 700; letter-spacing: 0px;"
            )
            self.main_window.activity_status_label.setStyleSheet(
                f"color: {self.main_window.accent_color}; font-size: 9pt; "
                "font-weight: 600; letter-spacing: 0px;"
            )

        # Bottom titlebar
        if hasattr(self.main_window, "bottom_titlebar"):
            self.main_window.bottom_titlebar.update_style()

    def update_queue_visibility(self, is_processing, has_jobs):
        """Update queue visibility based on current state"""
        if not is_processing and not has_jobs:
            if self.queue_widget:
                self.queue_widget.setVisible(False)
            self.main_window.drop_text_label.setText("Arraste e solte o ZIP aqui")
            if hasattr(self.main_window, "activity_status_label"):
                self.main_window.activity_status_label.setText("PRONTO")
            self._show_main_gif()
        else:
            if self.queue_widget:
                self.queue_widget.setVisible(True)
            if not is_processing:
                self.main_window.drop_text_label.setText(
                    "Fila parada. Pronta para o próximo trabalho."
                )
            if hasattr(self.main_window, "activity_status_label"):
                self.main_window.activity_status_label.setText(
                    "PROCESSANDO" if is_processing else "NA FILA"
                )

    def _show_main_gif(self):
        """Show the main GIF animation"""
        preferred_path = self._preferred_main_gif_path().resolve()
        main_path = None
        if self.main_movie:
            try:
                main_path = Path(self.main_movie.fileName()).resolve()
            except OSError:
                pass

        if (
            not self.main_movie
            or not self.main_movie.isValid()
            or main_path != preferred_path
        ):
            self._set_movie(preferred_path, force=True)
            return

        if self.current_movie is self.main_movie:
            if self.main_movie.state() != QMovie.MovieState.Running:
                self.main_movie.start()
            return

        previous_movie = self.current_movie
        self.main_window.drop_zone_gif.setMovie(self.main_movie)
        self.main_movie.start()
        self.current_movie = self.main_movie
        self.current_movie_path = str(preferred_path)
        if previous_movie and previous_movie is not self.main_movie:
            previous_movie.stop()

    def show_main_gif(self):
        self._show_main_gif()

    def switch_to_download_gif(self):
        """Switch to a random download GIF"""
        # Update setting from current value
        self.disable_default_gifs = self.settings.value(
            "disable_default_gifs", False, type=bool
        )

        colored_dir = get_base_path() / "gifs/colorized"
        os.makedirs(str(colored_dir), exist_ok=True)

        # Determine which GIFs to use based on setting
        ui_mode = self.settings.value("ui_mode", "default")
        if ui_mode == "sonic":
            sonic_dir = Paths.resource("sonic/gifs")
            sonic_downloads = []
            if sonic_dir.exists() and sonic_dir.is_dir():
                sonic_downloads.extend(
                    [str(p) for p in sonic_dir.glob("downloading*.gif")]
                )

            if sonic_downloads:
                available_gifs = sorted(sonic_downloads)
            else:
                available_gifs = []
        elif self.disable_default_gifs:
            # Use only custom GIFs
            custom_gifs = sorted(
                [str(p) for p in colored_dir.glob("downloading_custom*.gif")]
            )

            available_gifs = [
                gif
                for gif in custom_gifs
                if not Path(gif).name.lower().startswith(DEFAULT_DOWNLOAD_GIF_PREFIX)
            ]

            # If no custom GIFs found, fall back to defaults
            if not available_gifs:
                available_gifs = self.default_download_gifs
                logger.warning("No custom GIFs found, using defaults")
        else:
            # Use only default GIFs
            available_gifs = self.default_download_gifs

        if not available_gifs and ui_mode != "sonic":
            available_gifs = resolve_default_download_gifs(
                colored_dir,
                resolve_visual_preset_gif_dir(self.settings),
            )
            if available_gifs:
                logger.warning(
                    "Colorized download GIFs are not ready; using preset defaults"
                )

        # Make sure we have GIFs to use
        if not available_gifs:
            logger.error("No download GIFs available!")
            self.main_window.drop_text_label.setText("Baixando...")
            return

        resolved_gifs = []
        for gif_path in available_gifs:
            try:
                path = Path(gif_path).resolve()
            except OSError:
                continue
            if path.exists():
                resolved_gifs.append(str(path))

        if not resolved_gifs:
            logger.error("No valid download GIFs available!")
            self.main_window.drop_text_label.setText("Baixando...")
            return

        # Queue refreshes can happen many times per second. Reuse the active
        # download movie so its animation never jumps back to frame zero.
        if (
            self.current_movie is self.download_movie
            and self.download_movie
            and self.download_movie.isValid()
            and self.random_gif_path in resolved_gifs
        ):
            if self.download_movie.state() != QMovie.MovieState.Running:
                self.download_movie.start()
            return

        random_gif_path = random.choice(resolved_gifs)
        download_movie = QMovie(random_gif_path)
        download_movie.setCacheMode(QMovie.CacheMode.CacheAll)
        self._apply_movie_size(download_movie)

        if not download_movie.isValid():
            logger.error("Failed to load GIF: %s", random_gif_path)
            self.main_window.drop_text_label.setText("Baixando...")
            return

        previous_movie = self.current_movie
        self.random_gif_path = random_gif_path
        self.download_movie = download_movie
        self.current_movie = download_movie
        self.current_movie_path = random_gif_path
        self.main_window.drop_zone_gif.setMovie(download_movie)
        download_movie.start()
        if previous_movie and previous_movie is not download_movie:
            previous_movie.stop()
