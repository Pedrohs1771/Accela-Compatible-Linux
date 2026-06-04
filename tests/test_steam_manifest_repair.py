import tempfile
import unittest
from pathlib import Path

from utils.steam_manifest import repair_lumatools_library_manifests


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


if __name__ == "__main__":
    unittest.main()
