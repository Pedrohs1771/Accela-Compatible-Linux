import json
import sys
import tempfile
import unittest
from pathlib import Path


SOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
)
sys.path.insert(0, str(SOURCE_ROOT))

from managers.game_manager import GameManager


class GameManagerAppIDTests(unittest.TestCase):
    def test_prefers_real_appid_over_fake_appid(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            (game_dir / "OnlineFix.ini").write_text(
                "[Main]\nRealAppId=2881650\nFakeAppId=480\n",
                encoding="utf-8",
            )

            self.assertEqual(
                GameManager._detect_appid_from_install(str(game_dir)),
                "2881650",
            )

    def test_reads_nested_steam_appid(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            executable_dir = game_dir / "Game" / "Binaries" / "Win64"
            executable_dir.mkdir(parents=True)
            (executable_dir / "steam_appid.txt").write_text(
                "477160\n", encoding="utf-8"
            )

            self.assertEqual(
                GameManager._detect_appid_from_install(str(game_dir)),
                "477160",
            )

    def test_reads_lumatools_profile_and_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            profile_dir = game_dir / ".LumaTools"
            profile_dir.mkdir()
            (profile_dir / "online_fix_profile.json").write_text(
                json.dumps({"appid": "238370"}),
                encoding="utf-8",
            )
            (game_dir / "LUMA_ONLINE_FIX_INFO.txt").write_text(
                "OnlineFix installed\n",
                encoding="utf-8",
            )

            self.assertEqual(
                GameManager._detect_appid_from_install(str(game_dir)),
                "238370",
            )
            self.assertEqual(
                GameManager._get_lumatools_marker_path(str(game_dir)),
                str(game_dir / ".LumaTools"),
            )


if __name__ == "__main__":
    unittest.main()
