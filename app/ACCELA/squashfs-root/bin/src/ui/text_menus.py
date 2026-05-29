"""
Text-based menu system for CLI mode using urwid.

Supports both Linux and Windows terminals.
"""

import logging
import os
import sys
from functools import partial
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import urwid

# Handle Windows specific curses requirements
if sys.platform == "win32":
    try:
        import windows_curses

        windows_curses.enable()
    except ImportError:
        windows_curses = None

logger = logging.getLogger(__name__)


class BaseTextMenu:
    """Base class for all text menus with common functionality."""

    def __init__(self, title: str, subtitle: str = ""):
        self.title = title
        self.subtitle = subtitle
        self.loop: Optional[urwid.MainLoop] = None
        self.result: Optional[Any] = None
        self.layout: urwid.Widget = urwid.Text("")
        self._selected_set: Optional[Set[str]] = None

    def run(self) -> Any:
        """Run the menu and return the result."""
        # Return early if result was set during __init__ (auto-skip case)
        if self.result is not None:
            return self.result

        self._build_menu()

        self.loop = urwid.MainLoop(
            self.layout,
            self._get_palette(),
            unhandled_input=self._handle_input,
            handle_mouse=False,
        )
        self.loop.run()
        return self.result

    @staticmethod
    def _get_palette() -> List[Tuple[str, str, str, str]]:
        return [
            ("header", "white,bold", "", "bold"),
            ("title", "white,bold", "", "bold"),
            ("selected", "light magenta,bold", "", "standout"),
            ("info", "light gray", "", ""),
            ("default", "white", "", ""),
            ("footer", "light magenta", "", ""),
        ]

    def _handle_input(self, key: Union[str, Tuple]) -> Optional[bool]:
        """Handle keyboard input."""
        if isinstance(key, tuple):
            return None

        if key in ("q", "Q", "esc", "Esc"):
            self.result = None
            raise urwid.ExitMainLoop()

        if key == "enter":
            return False

        if key in ("up", "down", "page up", "page down"):
            return False

        return None

    def _on_checkbox_changed(
        self, _checkbox: urwid.CheckBox, new_state: bool, user_data: str
    ) -> None:
        """Handle checkbox state change for selection sets."""
        if self._selected_set is None:
            return
        if new_state:
            self._selected_set.add(user_data)
        else:
            self._selected_set.discard(user_data)

    @staticmethod
    def _append_confirm_button(
        items: List[urwid.Widget],
        on_press,
    ) -> None:
        confirm_btn = urwid.Button(
            "  Confirmar seleção  ",
            on_press=on_press,
        )
        items.append(urwid.AttrMap(confirm_btn, "footer", "selected"))

    def _build_list_layout(self, items: List[urwid.Widget], instructions: str) -> None:
        walker = urwid.SimpleListWalker(items)
        listbox = urwid.ListBox(walker)

        header = self._create_header()
        footer = self._create_footer(instructions)

        self.layout = urwid.Frame(
            urwid.AttrMap(listbox, "default"),
            header=urwid.AttrMap(header, "header"),
            footer=footer,
        )

    def _build_menu(self) -> None:
        """Subclasses must implement this to build the menu."""
        raise NotImplementedError

    def _create_header(self) -> urwid.Widget:
        """Create the menu header."""
        text = f"{self.title}\n{self.subtitle}" if self.subtitle else self.title
        header = urwid.Text(("header", text))
        divider = urwid.Divider("─")
        return urwid.Pile([header, divider])

    @staticmethod
    def _create_footer(instructions: str) -> urwid.Widget:
        """Create the menu footer with instructions."""
        footer = urwid.Text(("info", instructions))
        return urwid.AttrMap(footer, "footer")


class CheckboxSelectionMenu(BaseTextMenu):
    """Base class for menus with multiple checkbox selections."""

    def __init__(self, title: str, subtitle: str = ""):
        super().__init__(title, subtitle)
        self.items_map: Dict[str, Any] = {}
        self.selected_items: Set[str] = set()
        self._selected_set = self.selected_items
        self.checkboxes: Dict[str, urwid.CheckBox] = {}

    def _build_menu(self) -> None:
        """Build the selection menu."""
        items = []
        for item_id, item_data in self.items_map.items():
            item = self._create_item_widget(item_id, item_data)
            items.append(item)

        self._append_confirm_button(items, self._on_confirm_pressed)

        instructions = "↑/↓: Navegar  Espaço: Marcar  A: Tudo  D: Nenhum  Q: Cancelar"
        self._build_list_layout(items, instructions)

    def _on_confirm_pressed(self, _btn: urwid.Button) -> None:
        """Handle confirm button press."""
        if self.selected_items:
            self.result = list(self.selected_items)
            raise urwid.ExitMainLoop()

    def _create_item_widget(self, item_id: str, item_data: Any) -> urwid.Widget:
        """Create an item widget using CheckBox."""
        item_text = self._get_item_text(item_id, item_data)
        checked = item_id in self.selected_items

        checkbox = urwid.CheckBox(
            item_text,
            state=checked,
            on_state_change=partial(self._on_checkbox_changed, user_data=item_id),
        )

        self.checkboxes[item_id] = checkbox
        return urwid.AttrMap(checkbox, "default", "selected")

    def _get_item_text(self, item_id: str, item_data: Any) -> str:
        """Get the text to display for an item."""
        raise NotImplementedError

    def _handle_input(self, key: Union[str, Tuple]) -> Optional[bool]:
        """Handle special keyboard shortcuts."""
        if key in ("a", "A"):
            self.selected_items.clear()
            self.selected_items.update(self.items_map.keys())
            self._update_all_checkboxes()
            return False

        if key in ("d", "D"):
            self.selected_items.clear()
            self._update_all_checkboxes()
            return False

        return super()._handle_input(key)

    def _update_all_checkboxes(self) -> None:
        """Update all checkboxes to reflect current selection."""
        for item_id, checkbox in self.checkboxes.items():
            checkbox.set_state(item_id in self.selected_items)


class DepotSelectionMenu(CheckboxSelectionMenu):
    """Text-based depot selection menu with multi-selection."""

    def __init__(
        self,
        app_id: str,
        game_name: str,
        depots: Dict[str, Any],
        _header_url: Optional[str] = None,
    ):
        subtitle = f"AppID: {app_id}"
        super().__init__(f"Selecionar depots para baixar - {game_name}", subtitle)
        self.items_map = depots
        self.selected_depots = self.selected_items
        self._host_platform = self._get_host_platform_family()

        # Auto-skip when only one depot is available
        if len(self.items_map) == 1:
            depot_id = list(self.items_map.keys())[0]
            depot_desc = self.items_map[depot_id].get("desc", "Desconhecido")
            self.selected_depots.clear()
            self.selected_depots.add(depot_id)
            self.result = [depot_id]
            logger.info(f"Auto-selected single depot: {depot_id} - {depot_desc}")

    def _get_item_text(self, item_id: str, item_data: Any) -> str:
        desc = item_data.get("desc", f"Depot {item_id}")
        size_str = self._format_size(item_data.get("size"))
        return f"{item_id} - {desc}{size_str}"

    @staticmethod
    def _format_size(size: Union[str, int, None]) -> str:
        """Format size in bytes to GB string."""
        if not size:
            return ""
        try:
            size_bytes = int(size)
            if size_bytes > 0:
                size_gb = size_bytes / (1024**3)
                return f" <{size_gb:.2f} GB>"
        except (ValueError, TypeError):
            pass
        return ""

    def _build_menu(self) -> None:
        """Build the depot selection menu."""
        sorted_depots = self._sort_depots()

        items = []
        for depot_id, depot_data in sorted_depots:
            item = self._create_item_widget(depot_id, depot_data)
            items.append(item)

        self._append_confirm_button(items, self._on_confirm_pressed)

        instructions = "↑/↓: Navegar  Espaço: Marcar  A: Tudo  D: Nenhum  Q: Cancelar"
        self._build_list_layout(items, instructions)

    @staticmethod
    def _normalize_os_value(os_val: Optional[str]) -> str:
        if not os_val:
            return ""
        return str(os_val).strip().lower()

    @staticmethod
    def _get_host_platform_family() -> str:
        if sys.platform == "win32":
            return "windows"
        if sys.platform == "linux":
            return "linux"
        if sys.platform == "darwin":
            return "macos"
        return ""

    def _calculate_os_priority(self, os_val: Optional[str]) -> int:
        """Calculate sort priority based on OS string."""
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
    def _calculate_lang_priority(
        lang_val: Optional[str], desc_str: str
    ) -> Tuple[int, str]:
        """Calculate language priority and sort key."""
        is_no_language = (
            lang_val is None
            and "english" not in desc_str
            and "japanese" not in desc_str
        )

        if "english" in desc_str:
            return 1, lang_val.lower() if lang_val else "english"
        if is_no_language:
            return 1, "english"
        if "japanese" in desc_str:
            return 2, "japanese"

        return 3, lang_val.lower() if lang_val else "zzzz"

    def _sort_depots(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Sort depots using same logic as GUI version."""

        def get_sort_key(depot_item: Tuple[str, Dict[str, Any]]) -> Tuple:
            depot_id, depot_data = depot_item
            os_priority = self._calculate_os_priority(depot_data.get("oslist"))
            desc_str = depot_data.get("desc", "").lower()
            lang_priority, lang_key = self._calculate_lang_priority(
                depot_data.get("language"), desc_str
            )
            return os_priority, lang_priority, lang_key, depot_id

        return sorted(self.items_map.items(), key=get_sort_key)


class DlcSelectionMenu(CheckboxSelectionMenu):
    """Text-based DLC selection menu using urwid.CheckBox."""

    def __init__(self, dlcs: Dict[str, str]):
        title = (
            "Selecionar DLC para o wrapper GreenLuma"
            if sys.platform == "win32"
            else "Selecionar DLC para o wrapper SLSsteam"
        )
        super().__init__(title)
        self.items_map = dlcs
        self.selected_dlcs = self.selected_items

    def _get_item_text(self, item_id: str, item_data: Any) -> str:
        return f"{item_id} - {item_data}"


class SteamLibraryMenu(BaseTextMenu):
    """Text-based Steam library selection menu using urwid.RadioButton."""

    def __init__(self, library_paths: List[str]):
        super().__init__("Selecionar biblioteca da Steam")
        self.library_paths = library_paths
        self.radio_buttons = {}
        self._radio_group = []
        self._selected_path = library_paths[0] if library_paths else None

        # Auto-skip when only one library is available
        if len(self.library_paths) == 1:
            logger.info(f"Auto-selected single Steam library: {self._selected_path}")
            self.result = self._selected_path

    def _build_menu(self) -> None:
        """Build the library selection menu."""
        items = []
        for path in self.library_paths:
            item = self._create_library_item(path)
            items.append(item)

        # Add confirm button at the end
        self._append_confirm_button(items, self._on_confirm_pressed)

        instructions = "↑/↓: Navegar  Enter: Confirmar  Q: Cancelar"
        self._build_list_layout(items, instructions)

    def _on_confirm_pressed(self, _btn: urwid.Button) -> None:
        """Handle confirm button press."""
        if self._selected_path:
            self.result = self._selected_path
            raise urwid.ExitMainLoop()

    def _create_library_item(self, path: str) -> urwid.Widget:
        """Create a library item widget."""
        radio = urwid.RadioButton(
            self._radio_group,
            path,
            state=path == self.library_paths[0] if self.library_paths else False,
            on_state_change=partial(self._on_radio_changed, user_data=path),
        )
        self.radio_buttons[path] = radio
        return urwid.AttrMap(radio, "default", "selected")

    def _on_radio_changed(
        self, _radio: urwid.RadioButton, new_state: bool, user_data: str
    ) -> None:
        """Handle radio button selection."""
        if new_state:
            self._selected_path = user_data

    def _handle_input(self, key: Union[str, Tuple]) -> Optional[bool]:
        """Handle special keyboard shortcuts."""
        return super()._handle_input(key)


class DestinationPathMenu(BaseTextMenu):
    """Text-based destination path selection."""

    def __init__(self, default_path: Optional[str] = None):
        super().__init__("Selecionar pasta de destino")
        self.default_path = default_path or os.path.expanduser("~")
        self.current_path = self.default_path
        self.edit: Optional[urwid.Edit] = None

    def _build_menu(self) -> None:
        """Build the path selection menu."""
        # Current path display
        path_label = urwid.Text(("title", "Caminho atual:"))
        path_display = urwid.Text(("default", f"  {self.current_path}"))

        # Navigation options
        nav_options = urwid.Text(("info", "\nOpções:"))
        opt1 = urwid.Text("  [Enter] - Usar caminho atual")
        opt2 = urwid.Text("  [Type]  - Informar novo caminho")
        opt3 = urwid.Text("  [H]     - Ir para a pasta home (~)")
        opt4 = urwid.Text("  [Q]     - Cancelar")

        # Edit widget for path input
        edit_label = urwid.Text(("title", "\nDigite o caminho:"))
        self.edit = urwid.Edit("", self.current_path)

        # Create pile
        pile = urwid.Pile(
            [
                path_label,
                path_display,
                urwid.Divider(" "),
                nav_options,
                opt1,
                opt2,
                opt3,
                opt4,
                urwid.Divider(" "),
                edit_label,
                urwid.AttrMap(self.edit, "default"),
            ]
        )

        header = self._create_header()

        self.layout = urwid.Frame(
            urwid.AttrMap(pile, "default"),
            header=urwid.AttrMap(header, "header"),
        )

    def _handle_input(self, key: Union[str, Tuple]) -> Optional[bool]:
        """Handle keyboard input."""
        if key == "enter":
            self._handle_enter()
            return None

        if key in ("h", "H"):
            if self.edit:
                self.edit.edit_text = "~"
            return False

        return super()._handle_input(key)

    def _handle_enter(self) -> None:
        """Handle Enter key press."""
        if not self.edit:
            self.result = self.default_path
            raise urwid.ExitMainLoop()

        path = self.edit.get_edit_text().strip()
        if path:
            self.result = os.path.expanduser(os.path.expandvars(path))
        else:
            self.result = self.default_path
        raise urwid.ExitMainLoop()


# Convenience functions


def _create_and_run_menu(menu_class, *args, **kwargs) -> Any:
    """Helper to create and run a menu."""
    menu = menu_class(*args, **kwargs)
    return menu.run()


def select_depots(
    app_id: str,
    game_name: str,
    depots: Dict[str, Any],
    header_url: Optional[str] = None,
) -> List[str]:
    """Show depot selection menu."""
    return _create_and_run_menu(
        DepotSelectionMenu, app_id, game_name, depots, header_url
    )


def select_dlcs(dlcs: Dict[str, str]) -> List[str]:
    """Show DLC selection menu."""
    if not dlcs:
        return []
    return _create_and_run_menu(DlcSelectionMenu, dlcs) or []


def select_steam_library(library_paths: List[str]) -> Optional[str]:
    """Show Steam library selection menu."""
    if not library_paths:
        return None
    return _create_and_run_menu(SteamLibraryMenu, library_paths)


def select_destination_path(default_path: Optional[str] = None) -> Optional[str]:
    """Show destination path selection menu."""
    return _create_and_run_menu(DestinationPathMenu, default_path)
