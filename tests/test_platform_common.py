from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.platform.common import resolve_steam_library_path


class ResolveSteamLibraryPathTests(unittest.TestCase):
    def test_normalizes_game_directory_to_library_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "mnt" / "games" / "SteamLibrary"
            game_directory = library / "steamapps" / "common" / "Terraria"
            game_directory.mkdir(parents=True)

            self.assertEqual(
                resolve_steam_library_path(game_directory, []),
                str(library.resolve()),
            )

    def test_normalizes_nested_steamapps_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "SteamLibrary"
            workshop_item = (
                library / "steamapps" / "workshop" / "content" / "105600"
            )
            workshop_item.mkdir(parents=True)

            self.assertEqual(
                resolve_steam_library_path(workshop_item, []),
                str(library.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
