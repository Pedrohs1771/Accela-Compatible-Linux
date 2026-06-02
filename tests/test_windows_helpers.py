from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

qtcore = types.ModuleType("PyQt6.QtCore")
qtcore.Qt = type("Qt", (), {})
qtgui = types.ModuleType("PyQt6.QtGui")
qtgui.QColor = type("QColor", (), {})
qtgui.QFont = type("QFont", (), {})
qtwidgets = types.ModuleType("PyQt6.QtWidgets")
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

from utils import helpers


class WindowsHelperTests(unittest.TestCase):
    def test_windows_program_root_uses_localappdata(self) -> None:
        with patch.dict("os.environ", {"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"}, clear=False):
            path = helpers.get_windows_program_root()
        self.assertTrue(str(path).endswith("Programs/LumaTools") or str(path).endswith(r"Programs\LumaTools"))
        self.assertIn(r"C:\Users\Test\AppData\Local", str(path))

    def test_windows_launcher_target_prefers_cmd_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install_root = Path(tmp)
            launcher = install_root / "Launch-LumaTools.cmd"
            launcher.write_text("@echo off\n", encoding="utf-8")
            with patch("utils.helpers.get_install_root", return_value=install_root):
                target = helpers.get_windows_launcher_target()
            self.assertEqual(target, launcher)


if __name__ == "__main__":
    unittest.main()
