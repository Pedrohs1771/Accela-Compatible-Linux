from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.platform.windows import WindowsBackend


class WindowsBackendTests(unittest.TestCase):
    def test_detects_registry_root_and_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp) / "Steam"
            (steam_root / "steamapps").mkdir(parents=True)
            (steam_root / "steam.exe").write_text("", encoding="utf-8")
            extra_library = Path(tmp) / "Games Library"
            (extra_library / "steamapps").mkdir(parents=True)
            (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n"0" "{steam_root}"\n"1" "{extra_library}"\n}}\n',
                encoding="utf-8",
            )

            backend = WindowsBackend(
                env={"PROGRAMFILES(X86)": str(Path(tmp) / "Missing")},
                registry_reader=lambda: str(steam_root),
            )
            install = backend.describe_steam_install()

            self.assertEqual(install.root, str(steam_root.resolve()))
            self.assertIn(str(extra_library.resolve()), install.libraries)
            self.assertTrue(install.launch_command[0].endswith("steam.exe"))

    def test_falls_back_to_program_files_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pf = Path(tmp) / "Program Files (x86)"
            steam_root = pf / "Steam"
            (steam_root / "steamapps").mkdir(parents=True)

            backend = WindowsBackend(
                env={"PROGRAMFILES(X86)": str(pf), "SystemDrive": str(Path(tmp).drive or "C:")},
                registry_reader=lambda: None,
            )
            self.assertEqual(backend.find_steam_install(), str(steam_root.resolve()))


if __name__ == "__main__":
    unittest.main()
