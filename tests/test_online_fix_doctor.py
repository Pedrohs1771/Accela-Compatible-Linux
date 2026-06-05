from __future__ import annotations

import tempfile
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

psutil_stub = types.ModuleType("psutil")
psutil_stub.process_iter = lambda *_args, **_kwargs: iter(())
psutil_stub.Error = Exception
psutil_stub.NoSuchProcess = Exception
sys.modules.setdefault("psutil", psutil_stub)

from core.online_fix_doctor import find_main_executable, repair_online_fix


class OnlineFixDoctorTests(unittest.TestCase):
    def _make_install(self, root: Path, appid: str = "728880"):
        steam_root = root / "Steam"
        library = root / "SteamLibrary"
        game_dir = library / "steamapps" / "common" / "Overcooked 2"
        user_config = steam_root / "userdata" / "123" / "config"

        game_dir.mkdir(parents=True)
        user_config.mkdir(parents=True)
        (steam_root / "config").mkdir(parents=True)
        (steam_root / "steamapps").mkdir(parents=True)
        (library / "steamapps").mkdir(parents=True, exist_ok=True)

        (game_dir / "Overcooked2.exe").write_bytes(b"MZ-game")
        (game_dir / "steam_api64.dll").write_bytes(b"dll")
        (game_dir / "onlinefix64.dll").write_bytes(b"dll")
        (game_dir / "LUMA_ONLINE_FIX_INFO.txt").write_text(
            'Launch Options:\nWINEDLLOVERRIDES="onlinefix64=n,b;steam_api64=n,b" %command%\n\n',
            encoding="utf-8",
        )
        (steam_root / "config" / "loginusers.vdf").write_text(
            '"users"\n{\n"123"\n{\n"MostRecent" "1"\n}\n}\n',
            encoding="utf-8",
        )
        (steam_root / "config" / "config.vdf").write_text(
            '"InstallConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"CompatToolMapping"\n\t\t\t\t{\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n',
            encoding="utf-8",
        )
        (user_config / "localconfig.vdf").write_text("", encoding="utf-8")
        (library / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            '"AppState"\n'
            "{\n"
            f'\t"appid"\t\t"{appid}"\n'
            '\t"name"\t\t"Overcooked 2"\n'
            '\t"installdir"\t\t"Overcooked 2"\n'
            '\t"buildid"\t\t"1"\n'
            "}\n",
            encoding="utf-8",
        )
        return steam_root, library, game_dir

    def _patch_environment(self, steam_root: Path, library: Path, reports_dir: Path):
        return patch.multiple(
            "core.online_fix_doctor",
            REPORTS_DIR=reports_dir,
        ), patch.multiple(
            "core.online_fix_doctor.steam_helpers",
            find_steam_install=lambda: str(steam_root),
            get_steam_libraries=lambda: [str(library)],
            get_preferred_steam_library=lambda: str(library),
        ), patch("core.online_fix_doctor.detect_linux_steam_mode", return_value="native")

    def test_main_exe_detection_ignores_unity_crash_handler(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            (game_dir / "UnityCrashHandler64.exe").write_bytes(b"bad")
            (game_dir / "Overcooked2.exe").write_bytes(b"good")

            main_exe = find_main_executable(game_dir, "Overcooked 2")

            self.assertTrue(main_exe.endswith("Overcooked2.exe"))

    def test_main_exe_detection_finds_exe_in_subfolder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            nested = game_dir / "Binaries" / "Win64"
            nested.mkdir(parents=True)
            (nested / "Game.exe").write_bytes(b"good")

            main_exe = find_main_executable(game_dir, "Game")

            self.assertTrue(main_exe.endswith("Binaries/Win64/Game.exe"))

    def test_launch_options_absent_are_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, _game_dir = self._make_install(root)
            reports = root / "reports"
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode:
                result = repair_online_fix("728880", auto=False, restart_steam=False)

            self.assertIn("LaunchOptions missing or incomplete.", result.warnings)

    def test_proton_absent_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, _game_dir = self._make_install(root)
            reports = root / "reports"
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode, patch("core.online_fix_doctor.discover_proton_tools", return_value=[]):
                result = repair_online_fix("728880", auto=False, restart_steam=False)

            self.assertIn("Proton mapping missing.", result.warnings)

    def test_profile_and_report_json_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, game_dir = self._make_install(root)
            reports = root / "reports"
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode, patch("core.online_fix_doctor.discover_proton_tools", return_value=[]):
                result = repair_online_fix("728880", auto=False, restart_steam=False)

            self.assertTrue((game_dir / ".LumaTools" / "online_fix_profile.json").is_file())
            self.assertTrue((reports / "728880.json").is_file())
            self.assertEqual(result.profile_path, str(game_dir / ".LumaTools" / "online_fix_profile.json"))
            self.assertEqual(result.report_path, str(reports / "728880.json"))

    def test_profile_expected_dll_path_must_exist_in_same_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, game_dir = self._make_install(root)
            reports = root / "reports"
            profile_dir = game_dir / ".LumaTools"
            profile_dir.mkdir()
            (profile_dir / "online_fix_profile.json").write_text(
                '{"dlls_expected": ["Plugins/x86_64/steam_api64.dll"], "launch_options": ""}',
                encoding="utf-8",
            )
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode, patch("core.online_fix_doctor.discover_proton_tools", return_value=[]):
                result = repair_online_fix("728880", auto=False, restart_steam=False)

            self.assertTrue(
                any("Plugins/x86_64/steam_api64.dll" in error for error in result.errors)
            )

    def test_does_not_restart_steam_when_nothing_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, _game_dir = self._make_install(root)
            reports = root / "reports"
            launch = 'WINEDLLOVERRIDES="onlinefix64=n,b;steam_api64=n,b" %command%'
            escaped_launch = launch.replace('"', '\\"')
            (steam_root / "userdata" / "123" / "config" / "localconfig.vdf").write_text(
                '"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"728880"\n\t\t\t\t\t{\n'
                f'\t\t\t\t\t\t"LaunchOptions"\t\t"{escaped_launch}"\n'
                "\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n",
                encoding="utf-8",
            )
            (steam_root / "config" / "config.vdf").write_text(
                '"Steam"\n{\n\t"CompatToolMapping"\n\t{\n\t\t"728880"\n\t\t{\n\t\t\t"name"\t\t"proton_experimental"\n\t\t}\n\t}\n}\n',
                encoding="utf-8",
            )
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode, patch("core.online_fix_doctor._restart_steam") as restart:
                result = repair_online_fix("728880", auto=True, restart_steam=True)

            self.assertFalse(result.restart_needed)
            restart.assert_not_called()

    def test_marks_restart_needed_when_launch_options_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            steam_root, library, _game_dir = self._make_install(root)
            reports = root / "reports"
            (steam_root / "config" / "config.vdf").write_text(
                '"Steam"\n{\n\t"CompatToolMapping"\n\t{\n\t\t"728880"\n\t\t{\n\t\t\t"name"\t\t"proton_experimental"\n\t\t}\n\t}\n}\n',
                encoding="utf-8",
            )
            patch_reports, patch_steam, patch_mode = self._patch_environment(steam_root, library, reports)
            with patch_reports, patch_steam, patch_mode, patch("core.online_fix_doctor._restart_steam", return_value=(True, "SUCCESS")):
                result = repair_online_fix("728880", auto=True, restart_steam=True)

            self.assertTrue(result.restart_needed)
            self.assertTrue(result.steam_restarted)


if __name__ == "__main__":
    unittest.main()
