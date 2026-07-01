import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

SOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
)
sys.path.insert(0, str(SOURCE_ROOT))


def _install_pyqt_stub():
    pyqt6 = sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
    qtcore = sys.modules.setdefault("PyQt6.QtCore", types.ModuleType("PyQt6.QtCore"))

    class QObject:
        def __init__(self, *_args, **_kwargs):
            pass

    class _Signal:
        def emit(self, *_args, **_kwargs):
            return None

        def connect(self, *_args, **_kwargs):
            return None

    qtcore.QObject = QObject
    qtcore.pyqtSignal = lambda *_args, **_kwargs: _Signal()
    pyqt6.QtCore = qtcore


class DownloadSLSsteamTaskTests(unittest.TestCase):
    def setUp(self):
        _install_pyqt_stub()
        self.module = importlib.import_module("core.tasks.download_slssteam_task")

    def test_flatpak_override_accepts_official_override_with_different_paths(self):
        result = mock.Mock(
            stdout=(
                "[Context]\n"
                "filesystems=/tmp/SLSsteam/SLSsteam.so;/tmp/SLSsteam/library-inject.so\n"
                "[Environment]\n"
                "SHARED_LIBRARY_GUARD=0\n"
                "LD_AUDIT=/app/lib/libshared-library-guard.so\n"
            )
        )
        with (
            mock.patch.object(self.module.shutil, "which", return_value="/usr/bin/flatpak"),
            mock.patch.object(self.module.subprocess, "run", return_value=result),
        ):
            self.assertTrue(
                self.module.DownloadSLSsteamTask._flatpak_override_ready(
                    "/different/SLSsteam.so",
                    "/different/library-inject.so",
                )
            )

    def test_blocking_install_does_not_write_version_when_incompatible(self):
        task = self.module.DownloadSLSsteamTask
        fake_release = {
            "tag_name": "v9.9.9",
            "assets": [{"browser_download_url": "https://example.invalid/SLSsteam.7z"}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            install_dir = Path(tmpdir) / "SLSsteam"
            with (
                mock.patch.object(self.module.sys, "platform", "linux"),
                mock.patch.object(self.module, "detect_linux_steam_mode", return_value="native"),
                mock.patch.object(self.module, "is_slssteam_supported", return_value=True),
                mock.patch.object(task, "install_dir", return_value=install_dir),
                mock.patch.object(task, "_fetch_latest_release", return_value=fake_release),
                mock.patch.object(task, "_pick_asset", return_value=fake_release["assets"][0]),
                mock.patch.object(task, "_download_asset_blocking", return_value=None),
                mock.patch.object(task, "_extract_archive", return_value=None),
                mock.patch.object(task, "_run_setup", return_value=None),
                mock.patch.object(task, "installed_library_status", return_value={"compatible": False}),
            ):
                with self.assertRaises(RuntimeError):
                    task.install_latest_blocking()

            self.assertFalse((install_dir / "VERSION").exists())


if __name__ == "__main__":
    unittest.main()
