import tempfile
import unittest
import zipfile
from pathlib import Path

from core.online_fix_injector import OnlineFixInjector


class OnlineFixExtractorTests(unittest.TestCase):
    def test_extracts_zip_through_temp_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_dir = tmp_path / "game"
            game_dir.mkdir()
            archive = tmp_path / "fix.zip"

            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("BepInEx/config.ini", "ok=1")

            ok, extractor = OnlineFixInjector._extract_archive(str(archive), str(game_dir))

            self.assertTrue(ok, extractor)
            self.assertEqual((game_dir / "BepInEx" / "config.ini").read_text(), "ok=1")

    def test_rejects_zip_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            game_dir = tmp_path / "game"
            game_dir.mkdir()
            archive = tmp_path / "bad.zip"

            with zipfile.ZipFile(archive, "w") as zip_file:
                zip_file.writestr("../evil.txt", "bad")

            ok, message = OnlineFixInjector._extract_archive(str(archive), str(game_dir))

            self.assertFalse(ok)
            self.assertIn("Caminho inseguro", message)
            self.assertFalse((tmp_path / "evil.txt").exists())

    def test_normalizes_onlinefix_language_to_brazilian(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            ini_path = game_dir / "engine" / "OnlineFix.ini"
            ini_path.parent.mkdir()
            ini_path.write_bytes(
                b"[Main]\r\nRealAppId=238370\r\nLanguage=russian\r\n"
            )

            updated = OnlineFixInjector._normalize_onlinefix_language(str(game_dir))

            self.assertEqual(updated, [str(ini_path)])
            content = ini_path.read_text(encoding="utf-8")
            self.assertIn("Language=brazilian", content)
            self.assertNotIn("Language=russian", content)
            self.assertIn("RealAppId=238370", content)


if __name__ == "__main__":
    unittest.main()
