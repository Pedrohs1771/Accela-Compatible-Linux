import tempfile
import unittest
from pathlib import Path

from utils.steam_manifest import (
    detect_recent_decryption_key_issue,
    get_active_steam_owner,
    repair_lumatools_library_manifests,
    write_acf_file,
)


class SteamManifestRepairTests(unittest.TestCase):
    def test_repairs_lumatools_managed_update_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "Stardew Valley"
            game_dir.mkdir(parents=True)
            (game_dir / ".LumaTools").write_text("", encoding="utf-8")
            (game_dir / "data.bin").write_bytes(b"12345")
            (steamapps / "downloading" / "413150").mkdir(parents=True)
            (steamapps / "temp" / "413150").mkdir(parents=True)
            (steamapps / "shadercache" / "413150").mkdir(parents=True)
            (steamapps / "appmanifest_413150.acf.tmp").write_text("tmp", encoding="utf-8")
            (steamapps / "appmanifest_413150.acf.old").write_text("old", encoding="utf-8")
            manifest = steamapps / "appmanifest_413150.acf"
            manifest.write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"413150"\n'
                '\t"name"\t\t"Stardew Valley"\n'
                '\t"StateFlags"\t\t"6"\n'
                '\t"installdir"\t\t"Stardew Valley"\n'
                '\t"LastOwner"\t\t"0"\n'
                '\t"UpdateResult"\t\t"8"\n'
                '\t"BytesToDownload"\t\t"123"\n'
                '\t"ScheduledAutoUpdate"\t\t"999"\n'
                "}\n",
                encoding="utf-8",
            )

            result = repair_lumatools_library_manifests([str(library)])

            self.assertEqual(result["repaired"], ["413150"])
            text = manifest.read_text(encoding="utf-8")
            self.assertIn('"StateFlags"\t\t"4"', text)
            self.assertIn('"UpdateResult"\t\t"0"', text)
            self.assertIn('"BytesToDownload"\t\t"0"', text)
            self.assertIn('"ScheduledAutoUpdate"\t\t"0"', text)
            self.assertIn('"SizeOnDisk"\t\t"5"', text)
            self.assertFalse((steamapps / "downloading" / "413150").exists())
            self.assertFalse((steamapps / "temp" / "413150").exists())
            self.assertFalse((steamapps / "shadercache" / "413150").exists())
            self.assertFalse((steamapps / "appmanifest_413150.acf.tmp").exists())
            self.assertFalse((steamapps / "appmanifest_413150.acf.old").exists())

    def test_reports_decryption_key_block_without_hiding_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "Blocked Game"
            game_dir.mkdir(parents=True)
            logs = library / "logs"
            logs.mkdir(parents=True)
            (game_dir / ".LumaTools").write_text("", encoding="utf-8")
            (logs / "content_log.txt").write_text(
                "[2026-06-04] AppID 777 update prefetch canceled : "
                "Failed to initialize depot 778, manifest 123 (Missing decryption key)\n",
                encoding="utf-8",
            )
            manifest = steamapps / "appmanifest_777.acf"
            manifest.write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"777"\n'
                '\t"name"\t\t"Blocked Game"\n'
                '\t"StateFlags"\t\t"6"\n'
                '\t"installdir"\t\t"Blocked Game"\n'
                "}\n",
                encoding="utf-8",
            )

            result = repair_lumatools_library_manifests([str(library)])

            self.assertEqual(result["repaired"], ["777"])
            self.assertEqual(result["decryption_key_blocked"], ["777"])
            self.assertIn(
                "Missing decryption key",
                detect_recent_decryption_key_issue(library, "777"),
            )

    def test_skips_unmanaged_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "Owned Game"
            game_dir.mkdir(parents=True)
            manifest = steamapps / "appmanifest_123.acf"
            manifest.write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"123"\n'
                '\t"StateFlags"\t\t"6"\n'
                '\t"installdir"\t\t"Owned Game"\n'
                "}\n",
                encoding="utf-8",
            )

            result = repair_lumatools_library_manifests([str(library)])

            self.assertEqual(result["repaired"], [])
            self.assertEqual(result["skipped"], ["123"])
            self.assertIn('"StateFlags"\t\t"6"', manifest.read_text(encoding="utf-8"))

    def test_active_steam_owner_uses_most_recent_login_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp)
            config = steam_root / "config"
            config.mkdir(parents=True)
            (config / "loginusers.vdf").write_text(
                '"users"\n'
                "{\n"
                '\t"76561198000000001"\n'
                "\t{\n"
                '\t\t"AccountName"\t\t"old"\n'
                '\t\t"MostRecent"\t\t"0"\n'
                "\t}\n"
                '\t"76561198000000002"\n'
                "\t{\n"
                '\t\t"AccountName"\t\t"active"\n'
                '\t\t"MostRecent"\t\t"1"\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )

            self.assertEqual(get_active_steam_owner(steam_root), "76561198000000002")

    def test_write_acf_uses_active_steam_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp)
            config = steam_root / "config"
            config.mkdir(parents=True)
            (config / "loginusers.vdf").write_text(
                '"users"\n'
                "{\n"
                '\t"76561198000000002"\n'
                "\t{\n"
                '\t\t"MostRecent"\t\t"1"\n'
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )

            acf_path = write_acf_file(
                str(steam_root),
                {
                    "appid": "999",
                    "game_name": "Owner Test",
                    "buildid": "1",
                    "selected_depots_list": [],
                    "manifests": {},
                    "depots": {},
                },
                0,
                include_depots=False,
            )

            self.assertIsNotNone(acf_path)
            text = Path(acf_path).read_text(encoding="utf-8")
            self.assertIn('"LastOwner"\t\t"76561198000000002"', text)


if __name__ == "__main__":
    unittest.main()
