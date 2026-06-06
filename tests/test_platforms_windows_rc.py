from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from platforms.windows_backend import WindowsPlatformBackend
from utils import steam_manifest


class WindowsPlatformRcTests(unittest.TestCase):
    def test_windows_backend_uses_localappdata_and_job_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = WindowsPlatformBackend(
                env={"LOCALAPPDATA": str(Path(tmp) / "LocalAppData")},
                registry_reader=lambda: None,
            )

            layout = backend.ensure_data_layout()
            expected_dirs = {
                "logs",
                "backups",
                "jobs",
                "temp",
                "dlc_cache",
                "workshop_cache",
                "hubcap_manifests",
                "ryuu_content",
                "doctor_reports",
                "online_reports",
                "downloads",
                "tools",
                "depotdownloader",
                "steamcmd",
                "redist",
            }

            self.assertEqual(layout["root"], Path(tmp) / "LocalAppData" / "LumaTools")
            for key in expected_dirs:
                self.assertTrue(layout[key].is_dir(), key)

            job = backend.make_job_layout("job-123")
            self.assertEqual(job["root"], layout["jobs"] / "job-123")
            self.assertEqual(job["keys"], job["root"] / "keys.vdf")
            self.assertTrue(job["manifests"].is_dir())
            self.assertTrue(job["staging"].is_dir())
            self.assertTrue(job["logs"].is_dir())
            self.assertEqual(job["download_plan"], job["root"] / "download_plan.json")
            self.assertEqual(job["result"], job["root"] / "result.json")

    def test_windows_backend_detects_registry_root_libraries_and_launch_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Steam"
            extra_library = Path(tmp) / "Steam Library With Spaces"
            (root / "steamapps").mkdir(parents=True)
            (root / "userdata" / "12345" / "config").mkdir(parents=True)
            (root / "steam.exe").write_text("", encoding="utf-8")
            (extra_library / "steamapps").mkdir(parents=True)
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                (
                    '"libraryfolders"\n'
                    "{\n"
                    f'\t"0"\t\t"{str(root).replace(chr(92), chr(92) * 2)}"\n'
                    f'\t"1"\t\t"{str(extra_library).replace(chr(92), chr(92) * 2)}"\n'
                    "}\n"
                ),
                encoding="utf-8",
            )

            backend = WindowsPlatformBackend(
                env={"LOCALAPPDATA": str(Path(tmp) / "LocalAppData")},
                registry_reader=lambda: str(root),
            )

            self.assertEqual(backend.find_steam_install(), root.resolve())
            self.assertEqual(backend.get_steam_executable(), root.resolve() / "steam.exe")
            self.assertIn(extra_library.resolve(), backend.get_steam_libraries())

            changed = backend.set_launch_options(413150, "-windowed %command%")
            self.assertTrue(changed)
            localconfig = root / "userdata" / "12345" / "config" / "localconfig.vdf"
            content = localconfig.read_text(encoding="utf-8")
            self.assertIn('"413150"', content)
            self.assertIn('"LaunchOptions"', content)
            self.assertIn("-windowed %command%", content)


class SteamManifestWindowsSafetyTests(unittest.TestCase):
    def _game_data(self) -> dict:
        return {
            "appid": "123",
            "game_name": 'Quote "Game" São Paulo',
            "installdir": 'Quote "Dir" \\ Test',
            "buildid": "456",
            "selected_depots_list": ["1231", "1232"],
            "manifests": {"1231": "999", "1232": "888"},
            "depots": {"1231": {"size": "10"}, "1232": {"size": "20"}},
        }

    def test_acf_writer_escapes_values_and_creates_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            steamapps = Path(tmp) / "steamapps"
            steamapps.mkdir()

            first = steam_manifest.write_acf_file(
                tmp,
                self._game_data(),
                size_on_disk=30,
                include_depots=True,
            )
            self.assertIsNotNone(first)
            acf_path = Path(first)
            content = acf_path.read_text(encoding="utf-8")
            self.assertIn('\\"Game\\"', content)
            self.assertIn('\\"Dir\\"', content)
            self.assertIn("\\\\ Test", content)
            self.assertIn('"1231"', content)
            self.assertIn('"manifest"\t\t"999"', content)

            steam_manifest.write_acf_file(
                tmp,
                self._game_data(),
                size_on_disk=31,
                include_depots=True,
            )
            self.assertTrue(acf_path.with_suffix(acf_path.suffix + ".bak").exists())

    def test_acf_writer_rolls_back_when_generated_manifest_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            steamapps = Path(tmp) / "steamapps"
            steamapps.mkdir()
            acf_path = steamapps / "appmanifest_123.acf"
            original = '"AppState"\n{\n\t"appid"\t\t"123"\n}\n'
            acf_path.write_text(original, encoding="utf-8")

            original_builder = steam_manifest.build_acf_content
            steam_manifest.build_acf_content = lambda *args, **kwargs: '"AppState"\n{\n'
            try:
                with self.assertRaises(ValueError):
                    steam_manifest.write_acf_file(
                        tmp,
                        self._game_data(),
                        size_on_disk=30,
                        include_depots=True,
                    )
            finally:
                steam_manifest.build_acf_content = original_builder

            self.assertEqual(acf_path.read_text(encoding="utf-8"), original)
            self.assertFalse(acf_path.with_suffix(acf_path.suffix + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
