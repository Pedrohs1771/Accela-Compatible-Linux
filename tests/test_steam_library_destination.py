from __future__ import annotations

import unittest
from unittest import mock

from managers.task_manager import TaskManager


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})
        self.synced = False

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value

    def setValue(self, key, value):
        self.values[key] = value

    def sync(self):
        self.synced = True


class SteamLibraryDestinationTests(unittest.TestCase):
    def test_multiple_libraries_open_selector_instead_of_forcing_primary(self):
        manager = TaskManager.__new__(TaskManager)
        manager.main_window = object()
        manager.settings = _Settings()
        libraries = ["/home/user/.steam", "/mnt/games/SteamLibrary"]

        dialog = mock.Mock()
        dialog.exec.return_value = True
        dialog.get_selected_path.return_value = libraries[1]

        with (
            mock.patch(
                "core.steam_helpers.get_steam_libraries",
                return_value=libraries,
            ),
            mock.patch(
                "core.steam_helpers.get_preferred_steam_library",
                return_value=libraries[0],
            ),
            mock.patch(
                "ui.dialogs.steamlibrary.SteamLibraryDialog",
                return_value=dialog,
            ) as dialog_class,
        ):
            selected = manager._get_library_destination_path()

        self.assertEqual(selected, libraries[1])
        dialog_class.assert_called_once_with(
            libraries,
            manager.main_window,
            initial_path=libraries[0],
        )
        self.assertEqual(
            manager.settings.values["preferred_steam_library_path"],
            libraries[1],
        )
        self.assertTrue(manager.settings.synced)

    def test_single_library_keeps_existing_automatic_behavior(self):
        manager = TaskManager.__new__(TaskManager)
        manager.main_window = object()
        manager.settings = _Settings()
        libraries = ["/home/user/.steam"]

        with mock.patch(
            "core.steam_helpers.get_steam_libraries",
            return_value=libraries,
        ):
            selected = manager._get_library_destination_path()

        self.assertEqual(selected, libraries[0])


if __name__ == "__main__":
    unittest.main()
