from __future__ import annotations

import unittest
from unittest import mock

from managers.steam_bridge_manager import build_bridge_status


class _Settings:
    def value(self, key, default=None, type=None):
        values = {
            "library_mode": True,
            "preferred_steam_library_path": "/mnt/games/SteamLibrary",
            "accent_color": "#C06C84",
        }
        value = values.get(key, default)
        return type(value) if type is not None else value


class _TaskManager:
    is_processing = True
    is_download_paused = False
    current_job = "/tmp/lumatools_fetch_123.zip"
    game_data = {"game_name": "Example Game"}


class _JobQueue:
    job_queue = [{"path": "/tmp/a.zip"}, {"path": "/tmp/b.zip"}]


class _GameManager:
    games = [{"appid": "1"}]


class _MainWindow:
    settings = _Settings()
    task_manager = _TaskManager()
    job_queue = _JobQueue()
    game_manager = _GameManager()


class SteamBridgeStatusTests(unittest.TestCase):
    def test_status_payload_is_read_only_and_reports_lumatools_state(self):
        with mock.patch(
            "managers.steam_bridge_manager.steam_helpers.get_steam_libraries",
            return_value=["/home/user/.steam", "/mnt/games/SteamLibrary"],
        ):
            payload = build_bridge_status(_MainWindow(), 32175)

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["busy"])
        self.assertEqual(payload["current_job"], "lumatools_fetch_123.zip")
        self.assertEqual(payload["current_game"], "Example Game")
        self.assertEqual(payload["queue_count"], 2)
        self.assertEqual(payload["games_count"], 1)
        self.assertEqual(payload["preferred_library"], "/mnt/games/SteamLibrary")
        self.assertEqual(len(payload["steam_libraries"]), 2)


if __name__ == "__main__":
    unittest.main()
