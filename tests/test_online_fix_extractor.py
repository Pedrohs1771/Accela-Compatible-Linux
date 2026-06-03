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


if __name__ == "__main__":
    unittest.main()
