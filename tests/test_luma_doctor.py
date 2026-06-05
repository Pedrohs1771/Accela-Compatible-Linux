import tempfile
import unittest
from pathlib import Path

from core.diagnostics.luma_doctor import inspect_appmanifest, run_doctor


class LumaDoctorTests(unittest.TestCase):
    def test_inspect_appmanifest_flags_pending_update_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp)
            game_dir = library / "steamapps" / "common" / "Example"
            game_dir.mkdir(parents=True)
            (game_dir / ".LumaTools").write_text("", encoding="utf-8")
            acf = library / "steamapps" / "appmanifest_123.acf"
            logs = library / "logs"
            logs.mkdir(parents=True)
            (logs / "content_log.txt").write_text(
                "[2026-06-04] AppID 123 update prefetch canceled : "
                "Failed to initialize depot 124, manifest 999 (Missing decryption key)\n",
                encoding="utf-8",
            )
            acf.write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"123"\n'
                '\t"name"\t\t"Example"\n'
                '\t"StateFlags"\t\t"6"\n'
                '\t"installdir"\t\t"Example"\n'
                '\t"LastOwner"\t\t"0"\n'
                '\t"BytesToDownload"\t\t"42"\n'
                '\t"TargetBuildID"\t\t"999"\n'
                "}\n",
                encoding="utf-8",
            )

            report = inspect_appmanifest(acf)

            self.assertTrue(report["managed_by_lumatools"])
            self.assertIn("stateflags_not_installed", report["issues"])
            self.assertIn("bytestodownload_nonzero", report["issues"])
            self.assertIn("targetbuildid_nonzero", report["issues"])
            self.assertIn("lastowner_missing_or_zero", report["issues"])
            self.assertIn("missing_decryption_key", report["issues"])
            self.assertIn("Missing decryption key", report["decryption_key_log"])

    def test_run_doctor_marks_missing_onlinefix_launch_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            steam_root = Path(tmp)
            game_dir = steam_root / "steamapps" / "common" / "Online Game"
            game_dir.mkdir(parents=True)
            (game_dir / "LUMA_ONLINE_FIX_INFO.txt").write_text(
                "Launch Options:\nWINEDLLOVERRIDES=\"onlinefix64=n,b\" %command%\n",
                encoding="utf-8",
            )
            (steam_root / "steamapps" / "appmanifest_456.acf").write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"456"\n'
                '\t"name"\t\t"Online Game"\n'
                '\t"StateFlags"\t\t"4"\n'
                '\t"installdir"\t\t"Online Game"\n'
                '\t"LastOwner"\t\t"111"\n'
                "}\n",
                encoding="utf-8",
            )

            report = run_doctor("456", steam_root=steam_root, library_paths=[steam_root])

            self.assertFalse(report["summary"]["ok"])
            self.assertIn("onlinefix_launch_options_missing", report["apps"][0]["issues"])


if __name__ == "__main__":
    unittest.main()
