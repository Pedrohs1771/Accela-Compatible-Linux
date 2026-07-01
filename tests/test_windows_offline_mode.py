import copy
import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


def _ensure_psutil_stub():
    if "psutil" in sys.modules:
        return
    try:
        __import__("psutil")
    except ModuleNotFoundError:
        sys.modules["psutil"] = types.ModuleType("psutil")


def _job_queue_import_stubs():
    pyqt6 = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtwidgets = types.ModuleType("PyQt6.QtWidgets")

    class QObject:
        def __init__(self, *args, **kwargs):
            pass

    class _Signal:
        def connect(self, *_args, **_kwargs):
            return None

        def emit(self, *_args, **_kwargs):
            return None

    class QMetaObject:
        @staticmethod
        def invokeMethod(*_args, **_kwargs):
            return None

    class QTimer:
        @staticmethod
        def singleShot(*_args, **_kwargs):
            return None

    class Qt:
        class ConnectionType:
            QueuedConnection = 0

    class QApplication:
        @staticmethod
        def activeWindow():
            return None

    class QMessageBox:
        class StandardButton:
            Yes = 1
            No = 2

        @staticmethod
        def critical(*_args, **_kwargs):
            return None

        @staticmethod
        def information(*_args, **_kwargs):
            return None

        @staticmethod
        def question(*_args, **_kwargs):
            return QMessageBox.StandardButton.No

        @staticmethod
        def warning(*_args, **_kwargs):
            return None

    qtcore.Q_ARG = lambda *_args, **_kwargs: None
    qtcore.QMetaObject = QMetaObject
    qtcore.QObject = QObject
    qtcore.QTimer = QTimer
    qtcore.Qt = Qt
    qtcore.pyqtSignal = lambda *_args, **_kwargs: _Signal()
    qtwidgets.QApplication = QApplication
    qtwidgets.QMessageBox = QMessageBox
    pyqt6.QtCore = qtcore
    pyqt6.QtWidgets = qtwidgets

    fake_download_module = types.ModuleType("core.tasks.download_slssteam_task")

    class DownloadSLSsteamTask:
        @staticmethod
        def install_latest_blocking():
            return "ok"

        @staticmethod
        def installed_library_status():
            return {"compatible": True}

    fake_download_module.DownloadSLSsteamTask = DownloadSLSsteamTask

    fake_helpers_module = types.ModuleType("utils.helpers")
    fake_helpers_module.get_base_path = lambda: Path(".")

    fake_config_helper = types.ModuleType("utils.steam_config_helper")
    fake_config_helper.repair_online_fix_launch_options = lambda *_args, **_kwargs: {}

    fake_manifest_module = types.ModuleType("utils.steam_manifest")
    fake_manifest_module.repair_lumatools_library_manifests = (
        lambda *_args, **_kwargs: {"repaired": []}
    )

    return {
        "PyQt6": pyqt6,
        "PyQt6.QtCore": qtcore,
        "PyQt6.QtWidgets": qtwidgets,
        "core.tasks.download_slssteam_task": fake_download_module,
        "utils.helpers": fake_helpers_module,
        "utils.steam_config_helper": fake_config_helper,
        "utils.steam_manifest": fake_manifest_module,
    }


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value


class WindowsOfflineModeTests(unittest.TestCase):
    def test_fix_offline_mode_clears_flag_for_autologin_user(self):
        _ensure_psutil_stub()
        from core import steam_helpers

        users = {
            "7656119": {
                "AccountName": "pedro",
                "RememberPassword": "1",
                "AllowAutoLogin": "1",
                "WantsOfflineMode": "1",
            }
        }
        dumped = {}

        fake_settings_module = types.ModuleType("utils.settings")
        fake_settings_module.get_settings = lambda: _Settings(
            {"sls_config_management": True}
        )

        fake_vdf_module = types.ModuleType("vdf")
        fake_vdf_module.load = lambda _handle: {"users": copy.deepcopy(users)}

        def _dump(data, _handle):
            dumped["data"] = copy.deepcopy(data)

        fake_vdf_module.dump = _dump

        with tempfile.TemporaryDirectory() as tmpdir:
            steam_root = Path(tmpdir) / "Steam"
            login_file = steam_root / "config" / "loginusers.vdf"
            login_file.parent.mkdir(parents=True)
            login_file.write_text("placeholder", encoding="utf-8")

            with (
                mock.patch.object(steam_helpers.sys, "platform", "win32"),
                mock.patch.object(
                    steam_helpers,
                    "find_steam_install",
                    return_value=str(steam_root),
                ),
                mock.patch.dict(
                    sys.modules,
                    {
                        "utils.settings": fake_settings_module,
                        "vdf": fake_vdf_module,
                    },
                ),
            ):
                steam_helpers.fix_greenluma_offline_mode()

        self.assertEqual(
            dumped["data"]["users"]["7656119"]["WantsOfflineMode"],
            "0",
        )

    def test_fix_offline_mode_keeps_manual_offline_user_unchanged(self):
        _ensure_psutil_stub()
        from core import steam_helpers

        users = {
            "7656119": {
                "AccountName": "pedro",
                "RememberPassword": "0",
                "AllowAutoLogin": "0",
                "WantsOfflineMode": "1",
            }
        }
        dump_calls = []

        fake_settings_module = types.ModuleType("utils.settings")
        fake_settings_module.get_settings = lambda: _Settings(
            {"sls_config_management": True}
        )

        fake_vdf_module = types.ModuleType("vdf")
        fake_vdf_module.load = lambda _handle: {"users": copy.deepcopy(users)}
        fake_vdf_module.dump = lambda data, handle: dump_calls.append((data, handle))

        with tempfile.TemporaryDirectory() as tmpdir:
            steam_root = Path(tmpdir) / "Steam"
            login_file = steam_root / "config" / "loginusers.vdf"
            login_file.parent.mkdir(parents=True)
            login_file.write_text("placeholder", encoding="utf-8")

            with (
                mock.patch.object(steam_helpers.sys, "platform", "win32"),
                mock.patch.object(
                    steam_helpers,
                    "find_steam_install",
                    return_value=str(steam_root),
                ),
                mock.patch.dict(
                    sys.modules,
                    {
                        "utils.settings": fake_settings_module,
                        "vdf": fake_vdf_module,
                    },
                ),
            ):
                steam_helpers.fix_greenluma_offline_mode()

        self.assertEqual(dump_calls, [])

    def test_windows_manifest_cache_targets_steam_root_depotcache(self):
        _ensure_psutil_stub()
        from utils.depot_manifest_cache import cache_depot_manifests

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            library = root / "Library"
            steam_root = root / "Steam"
            source_dir = root / "manifests"

            source_dir.mkdir(parents=True)
            (source_dir / "105601_5751495116255795831.manifest").write_bytes(b"manifest")

            with mock.patch("utils.depot_manifest_cache.sys.platform", "win32"), mock.patch(
                "core.steam_helpers.find_steam_install",
                return_value=str(steam_root),
            ):
                result = cache_depot_manifests(
                    str(library),
                    {"105601": "5751495116255795831"},
                    source_dir=str(source_dir),
                )

            self.assertEqual(result.copied, 1)
            self.assertTrue(
                (
                    steam_root
                    / "depotcache"
                    / "105601_5751495116255795831.manifest"
                ).is_file()
            )
            self.assertFalse(
                (
                    library
                    / "steamapps"
                    / "depotcache"
                    / "105601_5751495116255795831.manifest"
                ).exists()
            )

    def test_windows_restart_repairs_managed_state_before_relaunch(self):
        _ensure_psutil_stub()

        with mock.patch.dict(sys.modules, _job_queue_import_stubs()):
            job_queue_manager = importlib.import_module("managers.job_queue_manager")

            manager = job_queue_manager.JobQueueManager.__new__(
                job_queue_manager.JobQueueManager
            )
            manager._repair_managed_steam_state = mock.Mock()
            manager._show_message_safe = mock.Mock()

            with (
                mock.patch.object(job_queue_manager.sys, "platform", "win32"),
                mock.patch.object(job_queue_manager.time, "sleep"),
                mock.patch.object(
                    job_queue_manager.steam_helpers,
                    "find_steam_install",
                    return_value=r"C:\\Program Files (x86)\\Steam",
                ),
                mock.patch.object(
                    job_queue_manager.steam_helpers,
                    "kill_steam_process",
                    return_value=True,
                ),
                mock.patch.object(
                    job_queue_manager.steam_helpers,
                    "start_steam",
                    return_value="SUCCESS",
                ) as start_steam,
            ):
                manager._perform_steam_restart()

        manager._repair_managed_steam_state.assert_called_once_with()
        start_steam.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
