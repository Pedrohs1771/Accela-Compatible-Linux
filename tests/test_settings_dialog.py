import os
import tempfile
import unittest

from PyQt6.QtWidgets import QApplication, QComboBox, QGroupBox, QScrollArea

from core.visual_presets import all_visual_presets
from ui.dialogs.settings import SettingsDialog


class SettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_settings_tabs_are_scrollable_and_cleanly_titled(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_config = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                dialog = SettingsDialog()
                try:
                    self.assertGreaterEqual(dialog.tab_widget.count(), 8)
                    for index in range(dialog.tab_widget.count()):
                        self.assertIsInstance(dialog.tab_widget.widget(index), QScrollArea)

                    titles = [
                        group.title()
                        for group in dialog.findChildren(QGroupBox)
                    ]
                    self.assertNotIn("Assistente de APIs", titles)
                    self.assertFalse(any("🦋" in title for title in titles))

                    self.assertIsInstance(dialog.visual_preset_combo, QComboBox)
                    expected_presets = {
                        preset.key for preset in all_visual_presets()
                    }
                    actual_presets = {
                        dialog.visual_preset_combo.itemData(index)
                        for index in range(dialog.visual_preset_combo.count())
                    }
                    self.assertEqual(actual_presets, expected_presets)
                finally:
                    dialog.close()
            finally:
                if old_config is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old_config


if __name__ == "__main__":
    unittest.main()
