from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.workshop.workshop_errors import (
    WorkshopErrorCode,
    classify_steamcmd_error,
)
from core.workshop.workshop_installer import INSTALL_MANIFEST, WorkshopInstaller
from core.workshop.workshop_profiles import resolve_workshop_profile


class WorkshopBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.game = self.root / "Game"
        self.source = self.root / "download" / "123456"
        self.game.mkdir()
        self.source.mkdir(parents=True)
        (self.source / "mod.dll").write_bytes(b"mod")
        self.installer = WorkshopInstaller()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_error_classification(self) -> None:
        self.assertEqual(
            classify_steamcmd_error("ERROR! No subscription"),
            WorkshopErrorCode.NO_LICENSE,
        )
        self.assertEqual(
            classify_steamcmd_error("Workshop agreement must accept"),
            WorkshopErrorCode.AGREEMENT_REQUIRED,
        )
        self.assertEqual(
            classify_steamcmd_error("Network is unreachable"),
            WorkshopErrorCode.NETWORK_ERROR,
        )

    def test_profile_detection(self) -> None:
        (self.game / "BepInEx" / "plugins").mkdir(parents=True)
        profile = resolve_workshop_profile(self.game)
        self.assertEqual(profile.engine, "bepinex")
        self.assertEqual(
            Path(profile.target_root),
            self.game / "BepInEx" / "plugins",
        )

    def test_install_enable_disable_repair_and_uninstall(self) -> None:
        record = self.installer.install(
            appid="100",
            workshop_id="123456",
            source=self.source,
            game_dir=self.game,
            title="Test Mod",
        )
        active = Path(record["installed_path"])
        self.assertTrue((active / "mod.dll").is_file())
        self.assertTrue((active / INSTALL_MANIFEST).is_file())
        self.assertTrue(self.installer.repair(record)["ok"])

        self.installer.set_enabled(record, False)
        disabled = Path(record["disabled_path"])
        self.assertFalse(active.exists())
        self.assertTrue((disabled / "mod.dll").is_file())
        self.assertFalse(record["enabled"])

        self.installer.set_enabled(record, True)
        self.assertTrue((active / "mod.dll").is_file())
        self.assertTrue(record["enabled"])

        unrelated = active / "user-note.txt"
        unrelated.write_text("keep", encoding="utf-8")
        self.installer.uninstall(record)
        self.assertFalse((active / "mod.dll").exists())
        self.assertTrue(unrelated.exists())
        self.assertEqual(record["status"], "removed")

    def test_empty_update_does_not_replace_existing_install(self) -> None:
        record = self.installer.install(
            appid="100",
            workshop_id="123456",
            source=self.source,
            game_dir=self.game,
        )
        installed = Path(record["installed_path"])
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaisesRegex(RuntimeError, "workshop_item_empty"):
            self.installer.install(
                appid="100",
                workshop_id="123456",
                source=empty,
                game_dir=self.game,
            )
        self.assertTrue((installed / "mod.dll").is_file())


if __name__ == "__main__":
    unittest.main()
