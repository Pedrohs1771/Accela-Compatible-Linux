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


class _QSettingsStub:
    def __init__(self, *_args, **_kwargs):
        self._values = {}

    def value(self, _key, default=None, type=None):
        if _key in self._values:
            return self._values[_key]
        if type is bool:
            return bool(default)
        return default

    def setValue(self, key, value):
        self._values[key] = value

    def sync(self):
        pass


qtcore = types.ModuleType("PyQt6.QtCore")
qtcore.QObject = object
qtcore.QSettings = _QSettingsStub
qtcore.QTimer = type("QTimer", (), {})
qtcore.Qt = type("Qt", (), {})
qtcore.pyqtSignal = lambda *args, **kwargs: None
qtgui = types.ModuleType("PyQt6.QtGui")
qtgui.QColor = type("QColor", (), {})
qtgui.QFont = type("QFont", (), {})
qtwidgets = types.ModuleType("PyQt6.QtWidgets")
qtwidgets.QMessageBox = type("QMessageBox", (), {})
for name in (
    "QCheckBox",
    "QHBoxLayout",
    "QLabel",
    "QLineEdit",
    "QPushButton",
    "QSlider",
    "QVBoxLayout",
    "QWidget",
):
    setattr(qtwidgets, name, type(name, (), {}))
pyqt6 = types.ModuleType("PyQt6")
pyqt6.QtCore = qtcore
pyqt6.QtGui = qtgui
pyqt6.QtWidgets = qtwidgets
sys.modules.setdefault("PyQt6", pyqt6)
sys.modules.setdefault("PyQt6.QtCore", qtcore)
sys.modules.setdefault("PyQt6.QtGui", qtgui)
sys.modules.setdefault("PyQt6.QtWidgets", qtwidgets)

from core.auto_fix_backend import auto_fix_install_state
from core.tasks.download_depots_task import DownloadDepotsTask


class _SignalRecorder:
    def __init__(self) -> None:
        self.values = []

    def emit(self, *args):
        self.values.append(args)


class AutoFixBackendTests(unittest.TestCase):
    def test_download_output_throttles_file_path_flood(self) -> None:
        task = DownloadDepotsTask()
        task.progress = _SignalRecorder()
        task.progress_percentage = _SignalRecorder()
        task.total_download_size_for_this_job = 100
        task.current_depot_size = 100

        task._handle_downloader_output("58.60% /tmp/Game/Resources/icons/ship_70.png")

        self.assertEqual(task.progress_percentage.values, [(58,)])
        self.assertEqual(task.progress.values, [("Baixando arquivos... 58%",)])
        self.assertEqual(task._log_buffer, [])

    def test_download_output_detects_encrypted_content(self) -> None:
        task = DownloadDepotsTask()
        task.progress = _SignalRecorder()
        task.progress_percentage = _SignalRecorder()
        task._current_depot_id = "999"

        task._handle_downloader_output("Depot 999 content still encrypted")

        self.assertTrue(task.encrypted_content_detected)
        self.assertTrue(task._current_depot_encrypted)
        self.assertIn("encrypted_content_or_unsupported_depot", task.last_error_reason)

    def test_repairs_update_state_last_owner_and_depotcache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "SteamLibrary"
            steam_root = root / "Steam"
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "Game"
            game_dir.mkdir(parents=True)
            (game_dir / "game.exe").write_text("binary", encoding="utf-8")
            (steamapps / "downloading" / "123").mkdir(parents=True)
            (library / "depotcache").mkdir(parents=True)
            (library / "depotcache" / "456_789.manifest").write_text("manifest", encoding="utf-8")
            (steam_root / "config").mkdir(parents=True)
            (steam_root / "config" / "loginusers.vdf").write_text(
                '"users"\n{\n"76561198000000000"\n{\n"MostRecent" "1"\n}\n}\n',
                encoding="utf-8",
            )
            (steamapps / "appmanifest_123.acf").write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"123"\n'
                '\t"name"\t\t"Game"\n'
                '\t"StateFlags"\t\t"1026"\n'
                '\t"installdir"\t\t"Game"\n'
                '\t"BytesToDownload"\t\t"100"\n'
                '\t"TargetBuildID"\t\t"456"\n'
                '\t"LastOwner"\t\t"0"\n'
                '\t"InstalledDepots"\n'
                '\t{\n'
                '\t\t"456"\n'
                '\t\t{\n'
                '\t\t\t"manifest"\t\t"789"\n'
                '\t\t}\n'
                '\t}\n'
                "}\n",
                encoding="utf-8",
            )

            game_data = {
                "appid": "123",
                "game_name": "Game",
                "installdir": "Game",
                "selected_depots_list": ["456"],
                "manifests": {"456": "789"},
                "depots": {"456": {"size": "6"}},
            }

            with patch("core.auto_fix_backend.steam_helpers.find_steam_install", return_value=str(steam_root)):
                result = auto_fix_install_state(
                    game_data,
                    str(library),
                    size_on_disk=6,
                    auto_restart_steam=False,
                )

            self.assertTrue(result.ok, result.to_dict())
            repaired = (steamapps / "appmanifest_123.acf").read_text(encoding="utf-8")
            self.assertIn('"StateFlags"\t\t"4"', repaired)
            self.assertIn('"BytesToDownload"\t\t"0"', repaired)
            self.assertIn('"TargetBuildID"\t\t"0"', repaired)
            self.assertIn('"LastOwner"\t\t"76561198000000000"', repaired)
            self.assertFalse((steamapps / "downloading" / "123").exists())
            self.assertTrue((steamapps / "depotcache" / "456_789.manifest").is_file())

    def test_rejects_windows_install_without_main_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "SteamLibrary"
            steam_root = root / "Steam"
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "RuntimeOnly"
            game_dir.mkdir(parents=True)
            (game_dir / "steam_api64.dll").write_text("dll", encoding="utf-8")
            (game_dir / "steam_appid.txt").write_text("123", encoding="utf-8")
            (steamapps / "depotcache").mkdir(parents=True)
            (steamapps / "depotcache" / "456_789.manifest").write_text("manifest", encoding="utf-8")
            (steam_root / "config").mkdir(parents=True)
            (steam_root / "config" / "loginusers.vdf").write_text(
                '"users"\n{\n"76561198000000000"\n{\n"MostRecent" "1"\n}\n}\n',
                encoding="utf-8",
            )
            (steamapps / "appmanifest_123.acf").write_text(
                '"AppState"\n'
                "{\n"
                '\t"appid"\t\t"123"\n'
                '\t"name"\t\t"RuntimeOnly"\n'
                '\t"StateFlags"\t\t"4"\n'
                '\t"installdir"\t\t"RuntimeOnly"\n'
                '\t"LastOwner"\t\t"76561198000000000"\n'
                '\t"InstalledDepots"\n'
                '\t{\n'
                '\t\t"456"\n'
                '\t\t{\n'
                '\t\t\t"manifest"\t\t"789"\n'
                '\t\t}\n'
                '\t}\n'
                "}\n",
                encoding="utf-8",
            )
            game_data = {
                "appid": "123",
                "game_name": "RuntimeOnly",
                "installdir": "RuntimeOnly",
                "selected_depots_list": ["456"],
                "manifests": {"456": "789"},
                "depots": {"456": {"oslist": "windows", "size": "6"}},
            }

            with patch("core.auto_fix_backend.steam_helpers.find_steam_install", return_value=str(steam_root)):
                result = auto_fix_install_state(
                    game_data,
                    str(library),
                    auto_restart_steam=False,
                )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "missing_base_game_content")

    def test_detects_encrypted_content_log_as_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "SteamLibrary"
            steam_root = root / "Steam"
            steamapps = library / "steamapps"
            game_dir = steamapps / "common" / "Game"
            game_dir.mkdir(parents=True)
            (game_dir / "game.exe").write_text("binary", encoding="utf-8")
            (steamapps / "appmanifest_123.acf").write_text(
                '"AppState"\n{\n'
                '\t"appid"\t\t"123"\n'
                '\t"name"\t\t"Game"\n'
                '\t"StateFlags"\t\t"4"\n'
                '\t"installdir"\t\t"Game"\n'
                '\t"LastOwner"\t\t"1"\n'
                "}\n",
                encoding="utf-8",
            )
            (steam_root / "logs").mkdir(parents=True)
            (steam_root / "logs" / "content_log.txt").write_text(
                "AppID 123: Content still encrypted for depot 999\n",
                encoding="utf-8",
            )
            game_data = {
                "appid": "123",
                "game_name": "Game",
                "installdir": "Game",
                "selected_depots_list": [],
                "manifests": {},
                "depots": {},
            }

            with patch("core.auto_fix_backend.steam_helpers.find_steam_install", return_value=str(steam_root)):
                result = auto_fix_install_state(
                    game_data,
                    str(library),
                    auto_restart_steam=False,
                )

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "encrypted_content_or_unsupported_depot")


if __name__ == "__main__":
    unittest.main()
