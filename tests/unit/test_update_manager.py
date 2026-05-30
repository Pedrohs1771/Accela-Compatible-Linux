from __future__ import annotations

import unittest
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication, QObject

from managers.update_manager import UpdateManager


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


class FakeTaskManager:
    is_processing = False


class FakeJobQueue:
    job_queue = []


class FakeWindow(QObject):
    def __init__(self):
        super().__init__()
        self.settings = FakeSettings(
            {
                "github_updates_enabled": True,
                "github_signed_updates_only": True,
            }
        )
        self.task_manager = FakeTaskManager()
        self.job_queue = FakeJobQueue()
        self.visible = True

    def isVisible(self):
        return self.visible

    def request_quit(self, reason):  # noqa: ARG002
        return None


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class UpdateManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_identical_revision_is_not_update(self):
        manager = UpdateManager(FakeWindow())
        state = manager._determine_update_state(
            repo="owner/repo",
            installed_revision="a" * 40,
            latest_revision="a" * 40,
        )
        self.assertFalse(state["available"])

    def test_compare_behind_revision_is_update(self):
        manager = UpdateManager(FakeWindow())
        with patch(
            "managers.update_manager.requests.get",
            return_value=FakeResponse(
                payload={"status": "behind", "ahead_by": 0, "behind_by": 1}
            ),
        ):
            state = manager._determine_update_state(
                repo="owner/repo",
                installed_revision="a" * 40,
                latest_revision="b" * 40,
            )
        self.assertTrue(state["available"])

    def test_local_revision_disables_auto_update(self):
        manager = UpdateManager(FakeWindow())
        state = manager._determine_update_state(
            repo="owner/repo",
            installed_revision="local-12345678-dirty",
            latest_revision="b" * 40,
        )
        self.assertFalse(state["available"])
        self.assertIn("Build local", state["message"])

    def test_release_detection_notifies_only_once_per_revision(self):
        manager = UpdateManager(FakeWindow())
        manager.main_window.visible = False
        notices = []
        manager.notification_requested.connect(
            lambda title, body: notices.append((title, body))
        )
        release = {"commit_sha": "b" * 40, "display_name": "main-bbbbbbbb"}
        manager._handle_release_detected(dict(release))
        manager._handle_release_detected(dict(release))
        self.assertEqual(len(notices), 1)


if __name__ == "__main__":
    unittest.main()
