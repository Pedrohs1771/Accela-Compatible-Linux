from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.platform.common import parse_libraryfolders_vdf
from core.platform.linux import LinuxBackend
from core.platform.windows import WindowsBackend


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class PlatformBackendTests(unittest.TestCase):
    def test_parse_libraryfolders_vdf_returns_real_libraries_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            primary = Path(temp_dir) / "primary"
            secondary = Path(temp_dir) / "secondary"
            invalid = Path(temp_dir) / "missing"
            (primary / "steamapps").mkdir(parents=True)
            (secondary / "steamapps").mkdir(parents=True)

            template = (FIXTURES / "libraryfolders_linux.vdf.tpl").read_text(
                encoding="utf-8"
            )
            vdf_path = Path(temp_dir) / "libraryfolders.vdf"
            vdf_path.write_text(
                template.format(
                    PRIMARY_LIBRARY=str(primary),
                    SECONDARY_LIBRARY=str(secondary),
                )
                + f'\n"9"\n{{\n"path" "{invalid}"\n}}\n',
                encoding="utf-8",
            )

            libraries = parse_libraryfolders_vdf(vdf_path)
            self.assertEqual(
                libraries,
                [os.path.realpath(primary), os.path.realpath(secondary)],
            )

    def test_linux_backend_collects_root_and_additional_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Steam"
            extra = Path(temp_dir) / "ExtraLibrary"
            (root / "steamapps").mkdir(parents=True)
            (extra / "steamapps").mkdir(parents=True)
            template = (FIXTURES / "libraryfolders_linux.vdf.tpl").read_text(
                encoding="utf-8"
            )
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                template.format(
                    PRIMARY_LIBRARY=str(root),
                    SECONDARY_LIBRARY=str(extra),
                ),
                encoding="utf-8",
            )

            with patch("core.platform.linux.list_steam_roots", return_value=[root]):
                with patch(
                    "core.platform.linux.get_steam_launch_command",
                    return_value=["steam"],
                ):
                    install = LinuxBackend(preferred_mode="native").describe_steam_install()

            self.assertEqual(install.mode, "native")
            self.assertEqual(install.root, os.path.realpath(root))
            self.assertIn(os.path.realpath(extra), install.libraries)
            self.assertEqual(install.launch_command, ["steam"])

    def test_windows_backend_reads_registry_and_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "Steam"
            extra = Path(temp_dir) / "Games"
            (root / "steamapps").mkdir(parents=True)
            (extra / "steamapps").mkdir(parents=True)
            (root / "steam.exe").write_text("", encoding="utf-8")
            template = (FIXTURES / "libraryfolders_windows.vdf.tpl").read_text(
                encoding="utf-8"
            )
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                template.format(
                    PRIMARY_LIBRARY=str(root),
                    SECONDARY_LIBRARY=str(extra),
                ),
                encoding="utf-8",
            )

            backend = WindowsBackend(
                env={"SystemDrive": "C:"},
                registry_reader=lambda: str(root),
            )
            install = backend.describe_steam_install()

            self.assertEqual(install.platform, "windows")
            self.assertEqual(install.root, os.path.realpath(root))
            self.assertIn(os.path.realpath(extra), install.libraries)
            self.assertEqual(install.launch_command, [str(root / "steam.exe")])


if __name__ == "__main__":
    unittest.main()
