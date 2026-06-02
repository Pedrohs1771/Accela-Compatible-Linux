from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

qtcore = types.ModuleType("PyQt6.QtCore")
qtcore.QObject = object
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

from managers.update_manager import UpdateManager


class UpdateManagerWindowsManifestTests(unittest.TestCase):
    def test_prefers_windows_platform_payload(self) -> None:
        manifest = {
            "version": "1.2.3",
            "display_name": "1.2.3",
            "platforms": {
                "linux-x64": {"package_url": "https://example.invalid/linux.zip"},
                "windows-x64": {"package_url": "https://example.invalid/windows.zip"},
            },
        }
        with patch("managers.update_manager.sys.platform", "win32"):
            payload = UpdateManager._select_manifest_payload(manifest)
        self.assertEqual(payload["platform_key"], "windows-x64")
        self.assertEqual(payload["package_url"], "https://example.invalid/windows.zip")

    def test_rejects_manifest_without_windows_package(self) -> None:
        manifest = {
            "version": "1.2.3",
            "display_name": "1.2.3",
            "package_url": "https://example.invalid/lumatools-linux.zip",
        }
        with patch("managers.update_manager.sys.platform", "win32"):
            with self.assertRaises(RuntimeError):
                UpdateManager._select_manifest_payload(manifest)


if __name__ == "__main__":
    unittest.main()
