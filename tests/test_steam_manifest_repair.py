import tempfile
import unittest
from pathlib import Path

from utils.steam_manifest import (
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
