import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest import mock


def _ensure_qsettings_stub():
    qtcore = sys.modules.get("PyQt6.QtCore")
    if qtcore is None:
        pyqt6 = sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
        qtcore = types.ModuleType("PyQt6.QtCore")
        sys.modules["PyQt6.QtCore"] = qtcore
        setattr(pyqt6, "QtCore", qtcore)
    if not hasattr(qtcore, "QSettings"):
        class QSettings:
            def value(self, _key, default=None, type=None):
                return default

            def setValue(self, _key, _value):
                return None

        qtcore.QSettings = QSettings


class LinuxSteamModeTests(unittest.TestCase):
    def test_process_classifier_ignores_file_managers_opening_steam_paths(self):
        from core import linux_paths

        self.assertIsNone(
            linux_paths._classify_steam_process(
                "dolphin",
                "/usr/bin/dolphin /home/user/.local/share/Steam/steamapps/common/Game",
                "",
            )
        )

    def test_process_classifier_detects_flatpak_steam_launcher(self):
        from core import linux_paths

        self.assertEqual(
            linux_paths._classify_steam_process(
                "flatpak",
                "flatpak run com.valvesoftware.Steam",
                "",
            ),
            "flatpak",
        )

    def test_native_root_wins_when_flatpak_is_only_installed(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            native_root = home / ".local" / "share" / "Steam" / "steamapps"
            native_root.mkdir(parents=True)

            with (
                mock.patch.object(linux_paths, "_home", return_value=home),
                mock.patch.object(linux_paths, "detect_running_steam_mode", return_value=None),
                mock.patch.object(linux_paths.shutil, "which", return_value="/usr/bin/flatpak"),
                mock.patch.object(linux_paths, "_can_run", return_value=True),
            ):
                self.assertEqual(linux_paths.detect_linux_steam_mode(), "native")

    def test_running_flatpak_overrides_native_root(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            native_root = home / ".local" / "share" / "Steam" / "steamapps"
            native_root.mkdir(parents=True)

            with (
                mock.patch.object(linux_paths, "_home", return_value=home),
                mock.patch.object(linux_paths, "detect_running_steam_mode", return_value="flatpak"),
            ):
                self.assertEqual(linux_paths.detect_linux_steam_mode(), "flatpak")


class SLSsteamConfigPathTests(unittest.TestCase):
    def test_flatpak_config_path_is_returned_even_when_missing(self):
        _ensure_qsettings_stub()
        from core import linux_paths
        from utils import yaml_config_manager

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            expected = (
                home
                / ".var"
                / "app"
                / linux_paths.FLATPAK_APP_ID
                / "config"
                / "slssteam"
                / "config.yaml"
            )
            with (
                mock.patch("pathlib.Path.home", return_value=home),
                mock.patch.object(linux_paths, "detect_linux_steam_mode", return_value="flatpak"),
            ):
                self.assertEqual(yaml_config_manager.get_user_config_path(), expected)
                self.assertFalse(expected.exists())

    def test_snap_config_path_is_not_native_config_path(self):
        _ensure_qsettings_stub()
        from utils import yaml_config_manager
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            expected = home / "snap" / "steam" / "common" / ".config" / "slssteam" / "config.yaml"
            with (
                mock.patch("pathlib.Path.home", return_value=home),
                mock.patch.object(linux_paths, "detect_linux_steam_mode", return_value="snap"),
            ):
                self.assertEqual(yaml_config_manager.get_user_config_path(), expected)


class RyuuPostDownloadTests(unittest.TestCase):
    def test_task_manager_never_auto_offers_ryuu_after_download(self):
        task_manager_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "LumaTools"
            / "squashfs-root"
            / "bin"
            / "src"
            / "managers"
            / "task_manager.py"
        )
        source = task_manager_path.read_text(encoding="utf-8")
        finalize_body = source.split("# --- FINISH ---", 1)[0].rsplit(
            "def _finalize_job_logic", 1
        )[-1]

        self.assertNotIn("_start_ryuu_check_step()", finalize_body)


if __name__ == "__main__":
    unittest.main()
