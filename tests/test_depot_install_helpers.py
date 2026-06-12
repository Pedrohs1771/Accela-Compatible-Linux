import sys
import tempfile
import unittest
import zipfile
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

from utils.depot_manifest_cache import cache_depot_manifests
from utils.depot_selection import complete_base_depot_selection, extract_base_depot_ids
from utils.windows_redist_detector import (
    detect_windows_redists,
    protontricks_command,
    write_proton_requirements_report,
)
from core.tasks.download_depots_task import DownloadDepotsTask


class DepotInstallHelpersTests(unittest.TestCase):
    def test_marks_encrypted_depot_output_as_failure(self):
        task = DownloadDepotsTask()
        task._current_depot_id = "123"

        task._handle_downloader_output(
            "Error: encountered content still encrypted while processing depot"
        )

        self.assertTrue(task.encrypted_content_detected)
        self.assertTrue(task._current_depot_encrypted)
        self.assertEqual(
            task.last_error_reason,
            "encrypted_content_or_unsupported_depot: depot 123",
        )

    def test_extracts_only_main_app_depots(self):
        lua = """
-- MAIN APP DEPOTS
addappid(10, 1, "key") -- Content Windows
addappid(11, 1, "key") -- Engine Windows
-- SHARED DEPOTS
addappid(12, 1, "key") -- Redist
-- DLCS WITH DEDICATED DEPOTS
addappid(13, 1, "key") -- DLC
"""
        self.assertEqual(extract_base_depot_ids(lua), ["10", "11"])

    def test_completes_split_base_depots_for_selected_platform(self):
        depots = {
            "10": {"oslist": "windows"},
            "11": {"oslist": "windows"},
            "12": {"oslist": "linux"},
            "13": {"oslist": "windows"},
        }
        selected = complete_base_depot_selection(
            ["10", "13"], depots, ["10", "11", "12"]
        )
        self.assertEqual(selected, ["10", "13", "11"])

    def test_recovers_manifest_from_source_zip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("nested/10_20.manifest", b"manifest-data")

            result = cache_depot_manifests(
                str(root / "library"),
                {"10": "20"},
                selected_depots=["10"],
                source_zip=str(archive),
            )

            target = root / "library" / "steamapps" / "depotcache" / "10_20.manifest"
            self.assertTrue(result.ok)
            self.assertEqual(result.recovered_from_zip, 1)
            self.assertEqual(target.read_bytes(), b"manifest-data")

    def test_detects_terraria_dotnet_xna_redists(self):
        with tempfile.TemporaryDirectory() as temp:
            game_dir = Path(temp) / "Terraria"
            game_dir.mkdir()
            (game_dir / "installscript.vdf").write_text(
                '"process 1" "%INSTALLDIR%\\\\dotNetFx40_Full_setup.exe"\n'
                '"hasrunkey" "HKEY_LOCAL_MACHINE\\\\Software\\\\Microsoft\\\\XNA\\\\Framework\\\\v4.0"\n'
                '"command 1" "/package \\"%INSTALLDIR%\\\\xnafx40_redist.msi\\" /passive"\n',
                encoding="utf-8",
            )

            requirements = detect_windows_redists(game_dir)

            self.assertEqual([item.key for item in requirements], ["dotnet40", "xna40"])
            self.assertEqual(
                protontricks_command("105600", requirements),
                "protontricks 105600 dotnet40 xna40",
            )

            report = write_proton_requirements_report(
                game_dir,
                appid="105600",
                game_name="Terraria",
                requirements=requirements,
                proton_tool="Proton - Experimental",
                online_fix=True,
            )

            self.assertIsNotNone(report)
            text = report.read_text(encoding="utf-8")
            self.assertIn("Microsoft .NET Framework 4.x", text)
            self.assertIn("Microsoft XNA Framework 4.0", text)
            self.assertIn("protontricks 105600 dotnet40 xna40", text)


if __name__ == "__main__":
    unittest.main()
