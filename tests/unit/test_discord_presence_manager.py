from __future__ import annotations

import os
import unittest

from PyQt6.QtCore import QCoreApplication, QObject

from managers.discord_presence_manager import DiscordPresenceManager


class FakeSettings:
    def __init__(self, values=None):
        self.values = values or {}

    def value(self, key, default=None, type=None):  # noqa: A003
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        if type is str:
            return "" if value is None else str(value)
        return value

    def setValue(self, key, value):  # noqa: N802
        self.values[key] = value


class FakePresence:
    def __init__(self, client_id):
        self.client_id = client_id
        self.connected = False
        self.payloads = []

    def connect(self):
        self.connected = True

    def update(self, **payload):
        self.payloads.append(payload)

    def clear(self):
        return None

    def close(self):
        self.connected = False


class FakeProgressBar:
    def __init__(self, value=0, maximum=100, visible=False):
        self._value = value
        self._maximum = maximum
        self._visible = visible

    def isVisible(self):
        return self._visible

    def value(self):
        return self._value

    def maximum(self):
        return self._maximum


class FakeLabel:
    def __init__(self, text="", visible=False):
        self._text = text
        self._visible = visible

    def isVisible(self):
        return self._visible

    def text(self):
        return self._text


class FakeUpdateManager:
    def __init__(self, available=False, installing=False):
        self._available = available
        self._install_in_progress = installing
        self.latest_release = {"display_name": "main-abcdef12"}

    def is_update_available(self):
        return self._available


class FakeTaskManager:
    def __init__(self, processing=False, paused=False):
        self.is_processing = processing
        self.is_download_paused = paused
        self.game_data = {"game_name": "Balatro"}
        self.current_job = "/tmp/Balatro.zip"


class FakeJobQueue:
    def __init__(self, count=0):
        self.job_queue = [{"path": "a.zip"} for _ in range(count)]


class FakeGameManager:
    def __init__(self, count=0):
        self.games = [{"game_name": f"Game {i}"} for i in range(count)]


class FakeCloudSaveManager:
    def __init__(self, syncing=False):
        self._batch_state = {"1": {}} if syncing else {}


class FakeMainWindow(QObject):
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.task_manager = FakeTaskManager()
        self.job_queue = FakeJobQueue()
        self.game_manager = FakeGameManager()
        self.cloud_save_manager = FakeCloudSaveManager()
        self.update_manager = FakeUpdateManager()
        self.progress_bar = FakeProgressBar()
        self.speed_label = FakeLabel()


class DiscordPresenceManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_payload_prefers_update_state(self):
        settings = FakeSettings({"discord_presence_enabled": False})
        window = FakeMainWindow(settings)
        window.update_manager = FakeUpdateManager(available=True)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        settings.setValue("discord_presence_enabled", True)
        settings.setValue("discord_presence_client_id", "123456")
        settings.setValue("discord_presence_large_image", "accela_large")
        manager.reload_settings()
        payload = manager._build_payload()

        self.assertEqual(payload["details"], "Update disponível")
        self.assertEqual(payload["small_image"], "accela_update")
        self.assertEqual(payload["buttons"][0]["label"], "GitHub")

    def test_payload_uses_download_progress(self):
        settings = FakeSettings({"discord_presence_enabled": False})
        window = FakeMainWindow(settings)
        window.task_manager = FakeTaskManager(processing=True)
        window.progress_bar = FakeProgressBar(value=42, maximum=100, visible=True)
        window.speed_label = FakeLabel(text="18 MB/s", visible=True)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        settings.setValue("discord_presence_enabled", True)
        settings.setValue("discord_presence_client_id", "123456")
        manager.reload_settings()
        payload = manager._build_payload()

        self.assertIn("Baixando Balatro", payload["details"])
        self.assertIn("42% concluído", payload["state"])
        self.assertEqual(payload["small_image"], "accela_downloading")

    def test_missing_client_id_disconnects_cleanly(self):
        settings = FakeSettings({"discord_presence_enabled": True})
        window = FakeMainWindow(settings)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        manager.reload_settings()
        self.assertFalse(manager.connected)

    def test_official_client_id_fallback_is_supported(self):
        settings = FakeSettings({"discord_presence_enabled": True})
        window = FakeMainWindow(settings)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        manager.OFFICIAL_CLIENT_ID = "official-123"
        manager.reload_settings()
        self.assertEqual(manager.client_id, "official-123")

    def test_settings_override_official_client_id(self):
        settings = FakeSettings(
            {
                "discord_presence_enabled": True,
                "discord_presence_client_id": "custom-456",
            }
        )
        window = FakeMainWindow(settings)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        manager.OFFICIAL_CLIENT_ID = "official-123"
        manager.reload_settings()
        self.assertEqual(manager.client_id, "custom-456")

    def test_rate_limit_skips_redundant_push(self):
        settings = FakeSettings(
            {
                "discord_presence_enabled": True,
                "discord_presence_client_id": "123456",
            }
        )
        window = FakeMainWindow(settings)
        manager = DiscordPresenceManager(window)
        manager.presence_factory = FakePresence
        manager.reload_settings()
        manager.last_payload = None
        manager.last_push_at = 0.0
        manager.update_presence(force=True)
        first_count = len(manager.rpc.payloads)
        manager.update_presence(force=False)
        second_count = len(manager.rpc.payloads)
        self.assertEqual(first_count, second_count)


if __name__ == "__main__":
    unittest.main()
