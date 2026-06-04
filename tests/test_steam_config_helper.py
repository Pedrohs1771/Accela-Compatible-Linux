import tempfile
import unittest
from pathlib import Path

from utils.steam_config_helper import (
    _merge_launch_options,
    repair_online_fix_launch_options,
    set_steam_launch_options,
)


ONLINE_FIX_OPTIONS = (
    'WINEDLLOVERRIDES="onlinefix64=n,b;steamoverlay64=n,b;'
    'winmm=n,b;steam_api64=n,b;winhttp=n,b" %command%'
)


class SteamConfigHelperTests(unittest.TestCase):
    def test_repairs_old_semicolon_broken_onlinefix_overrides(self):
        old = (
            'WINEDLLOVERRIDES="onlinefix64=n;b;steamoverlay64=n;'
            'winmm=n;steam_api64=n;winhttp=n" %command%'
        )

        merged = _merge_launch_options(old, ONLINE_FIX_OPTIONS)

        self.assertIn("onlinefix64=n,b", merged)
        self.assertIn("steamoverlay64=n,b", merged)
        self.assertIn("winmm=n,b", merged)
        self.assertIn("steam_api64=n,b", merged)
        self.assertIn("winhttp=n,b", merged)
        self.assertNotIn("n;b", merged)
        self.assertNotIn(",b;b", merged)

    def test_preserves_extra_launch_flags_while_replacing_dll_entries(self):
        old = 'PROTON_LOG=1 WINEDLLOVERRIDES="steam_api64=n;winmm=n" %command%'

        merged = _merge_launch_options(old, ONLINE_FIX_OPTIONS)

        self.assertIn("PROTON_LOG=1", merged)
        self.assertIn("steam_api64=n,b", merged)
        self.assertIn("winmm=n,b", merged)
        self.assertNotIn("steam_api64=n;", merged)
        self.assertNotIn("winmm=n;", merged)

    def test_set_launch_options_updates_all_user_configs(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp)
            for user in ("111", "222"):
                config_dir = steam_root / "userdata" / user / "config"
                config_dir.mkdir(parents=True)
                (config_dir / "localconfig.vdf").write_text(
                    '"UserLocalConfigStore"\n'
                    "{\n"
                    '\t"Software"\n'
                    "\t{\n"
                    '\t\t"Valve"\n'
                    "\t\t{\n"
                    '\t\t\t"Steam"\n'
                    "\t\t\t{\n"
                    '\t\t\t\t"apps"\n'
                    "\t\t\t\t{\n"
                    '\t\t\t\t\t"1966720"\n'
                    "\t\t\t\t\t{\n"
                    '\t\t\t\t\t\t"LaunchOptions"\t\t"WINEDLLOVERRIDES=\\"onlinefix64=n;b;winmm=n\\" %command%"\n'
                    "\t\t\t\t\t}\n"
                    "\t\t\t\t}\n"
                    "\t\t\t}\n"
                    "\t\t}\n"
                    "\t}\n"
                    "}\n",
                    encoding="utf-8",
                )

            self.assertTrue(set_steam_launch_options(str(steam_root), "1966720", ONLINE_FIX_OPTIONS))

            for localconfig in steam_root.glob("userdata/*/config/localconfig.vdf"):
                text = localconfig.read_text(encoding="utf-8")
                self.assertIn("onlinefix64=n,b", text)
                self.assertIn("winmm=n,b", text)
                self.assertNotIn("n;b", text)

            self.assertTrue(set_steam_launch_options(str(steam_root), "1966720", ONLINE_FIX_OPTIONS))

    def test_repairs_online_fix_launch_options_from_game_info(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp)
            library = steam_root
            game_dir = library / "steamapps" / "common" / "Lethal Company"
            game_dir.mkdir(parents=True)
            (game_dir / "LUMA_ONLINE_FIX_INFO.txt").write_text(
                "Launch Options:\n"
                + ONLINE_FIX_OPTIONS
                + "\n\nDLLs: ['onlinefix64']",
                encoding="utf-8",
            )
            (library / "steamapps" / "appmanifest_1966720.acf").write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"1966720"\n'
                '\t"installdir"\t\t"Lethal Company"\n'
                "}\n",
                encoding="utf-8",
            )
            config_dir = steam_root / "userdata" / "111" / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "localconfig.vdf").write_text(
                '"UserLocalConfigStore"\n'
                "{\n"
                '\t"Software"\n'
                "\t{\n"
                '\t\t"Valve"\n'
                "\t\t{\n"
                '\t\t\t"Steam"\n'
                "\t\t\t{\n"
                '\t\t\t\t"apps"\n'
                "\t\t\t\t{\n"
                "\t\t\t\t}\n"
                "\t\t\t}\n"
                "\t\t}\n"
                "\t}\n"
                "}\n",
                encoding="utf-8",
            )

            result = repair_online_fix_launch_options(str(steam_root), [str(library)])

            self.assertEqual(result["updated"], ["1966720"])
            text = (config_dir / "localconfig.vdf").read_text(encoding="utf-8")
            self.assertIn("onlinefix64=n,b", text)
            self.assertNotIn("n;b", text)


if __name__ == "__main__":
    unittest.main()
