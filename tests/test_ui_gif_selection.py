from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from managers.ui_state_manager import (
    colorized_cache_matches_visual_preset,
    resolve_default_download_gifs,
)


class DummySettings:
    def __init__(self, preset: str):
        self.preset = preset

    def value(self, key: str, default=None, type=None):
        if key == "visual_preset":
            return self.preset
        return default


class DefaultDownloadGifSelectionTests(unittest.TestCase):
    def test_uses_bundled_download_gifs_when_colorized_cache_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            colored = root / "colorized"
            resources = root / "resources"
            colored.mkdir()
            resources.mkdir()
            bundled = resources / "downloading_default1.gif"
            bundled.touch()

            self.assertEqual(
                resolve_default_download_gifs(colored, resources),
                [str(bundled)],
            )

    def test_prefers_colorized_download_gifs_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            colored = root / "colorized"
            resources = root / "resources"
            colored.mkdir()
            resources.mkdir()
            colorized = colored / "downloading_default1.gif"
            bundled = resources / "downloading_default1.gif"
            colorized.touch()
            bundled.touch()

            self.assertEqual(
                resolve_default_download_gifs(colored, resources),
                [str(colorized)],
            )

    def test_colorized_cache_without_marker_only_matches_default_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            colored = Path(tmpdir)

            self.assertTrue(
                colorized_cache_matches_visual_preset(
                    DummySettings("hellgirl"),
                    colored,
                )
            )
            self.assertFalse(
                colorized_cache_matches_visual_preset(
                    DummySettings("wired_lain"),
                    colored,
                )
            )

    def test_colorized_cache_marker_must_match_selected_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            colored = Path(tmpdir)
            (colored / "active_visual_preset.txt").write_text(
                "ghoul_touka",
                encoding="utf-8",
            )

            self.assertTrue(
                colorized_cache_matches_visual_preset(
                    DummySettings("ghoul_touka"),
                    colored,
                )
            )
            self.assertFalse(
                colorized_cache_matches_visual_preset(
                    DummySettings("clock_homura"),
                    colored,
                )
            )


if __name__ == "__main__":
    unittest.main()
