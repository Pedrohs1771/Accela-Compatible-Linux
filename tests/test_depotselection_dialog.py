import sys
import unittest
from pathlib import Path
from unittest import mock

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


SOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
)
sys.path.insert(0, str(SOURCE_ROOT))

from ui.dialogs.depotselection import DepotSelectionDialog


@unittest.skipUnless(sys.platform == "linux", "Proton depot controls are Linux-only")
class DepotSelectionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self):
        depots = {
            "504230": {
                "oslist": "linux",
                "desc": "[LINUX] Celeste Linux",
                "size": "120000000",
            },
            "504231": {
                "oslist": "windows",
                "desc": "[WINDOWS] Celeste Windows",
                "size": "1080000000",
            },
            "504232": {
                "oslist": "macos",
                "desc": "[MACOS] Celeste OSX",
                "size": "120000000",
            },
            "504233": {
                "oslist": "",
                "desc": "Shared Content",
                "size": "1000",
            },
        }
        with mock.patch.object(
            DepotSelectionDialog, "_fetch_header_image", lambda self, app_id: None
        ):
            dialog = DepotSelectionDialog("504230", "Celeste", depots, "", None)
        dialog.show()
        self.app.processEvents()
        return dialog

    def _set_checked(self, dialog, depot_id):
        for index in range(dialog.list_widget.count()):
            item = dialog.list_widget.item(index)
            item.setCheckState(Qt.CheckState.Unchecked)
            if item.data(Qt.ItemDataRole.UserRole) == depot_id:
                item.setCheckState(Qt.CheckState.Checked)

    def test_linux_depot_hides_proton_and_onlinefix_controls(self):
        dialog = self._dialog()
        self.addCleanup(dialog.close)

        with mock.patch.object(dialog, "get_selected_depots", return_value=["504230"]):
            dialog._refresh_proton_section()
            self.assertTrue(dialog.proton_container.isHidden())

    def test_windows_depot_shows_proton_and_onlinefix_controls(self):
        dialog = self._dialog()
        self.addCleanup(dialog.close)

        with mock.patch.object(dialog, "get_selected_depots", return_value=["504231"]):
            dialog._refresh_proton_section()
            self.assertFalse(dialog.proton_container.isHidden())


if __name__ == "__main__":
    unittest.main()
