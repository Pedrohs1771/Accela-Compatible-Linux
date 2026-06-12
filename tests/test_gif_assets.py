from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image


GIF_DIR = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
    / "res"
    / "gif"
)
VISUAL_PRESET_DIR = GIF_DIR.parent / "visual_presets"
EXPECTED_GIFS = {"main.gif", "navi.gif"} | {
    f"downloading_default{index}.gif" for index in range(1, 12)
}
VISUAL_PRESETS = ("wired_lain", "ghoul_touka", "clock_homura")


def _rgba_pixels(frame: Image.Image) -> list[tuple[int, int, int, int]]:
    if hasattr(frame, "get_flattened_data"):
        return list(frame.get_flattened_data())
    return list(frame.getdata())


class GifAssetTests(unittest.TestCase):
    def test_default_theme_uses_animated_gifs_only(self) -> None:
        actual = {path.name for path in GIF_DIR.glob("*.gif")}
        self.assertEqual(actual, EXPECTED_GIFS)

        for path in sorted(GIF_DIR.glob("*.gif")):
            with self.subTest(path=path.name), Image.open(path) as image:
                self.assertGreater(image.n_frames, 1)

    def test_default_theme_has_recolorable_pixels(self) -> None:
        for path in sorted(GIF_DIR.glob("*.gif")):
            with self.subTest(path=path.name), Image.open(path) as image:
                frame = image.convert("RGBA")
                pixels = _rgba_pixels(frame)
                colorful = sum(
                    1
                    for red, green, blue, alpha in pixels
                    if alpha > 10 and max(red, green, blue) - min(red, green, blue) > 10
                )
                self.assertGreater(colorful / max(len(pixels), 1), 0.02)

    def test_visual_presets_have_complete_recolorable_gif_sets(self) -> None:
        for preset in VISUAL_PRESETS:
            gif_dir = VISUAL_PRESET_DIR / preset / "gif"
            with self.subTest(preset=preset):
                self.assertTrue(gif_dir.is_dir())
                actual = {path.name for path in gif_dir.glob("*.gif")}
                self.assertEqual(actual, EXPECTED_GIFS)

            for path in sorted(gif_dir.glob("*.gif")):
                with self.subTest(preset=preset, path=path.name), Image.open(path) as image:
                    self.assertGreater(image.n_frames, 1)
                    image.seek(0)
                    frame = image.convert("RGBA")
                    pixels = _rgba_pixels(frame)
                    colorful = sum(
                        1
                        for red, green, blue, alpha in pixels
                        if alpha > 10
                        and max(red, green, blue) - min(red, green, blue) > 10
                    )
                    self.assertGreater(colorful / max(len(pixels), 1), 0.02)

    def test_visual_preset_main_gifs_are_visible(self) -> None:
        for preset in VISUAL_PRESETS:
            path = VISUAL_PRESET_DIR / preset / "gif" / "main.gif"
            with self.subTest(preset=preset), Image.open(path) as image:
                image.seek(0)
                frame = image.convert("RGB")
                pixels = list(
                    frame.get_flattened_data()
                    if hasattr(frame, "get_flattened_data")
                    else frame.getdata()
                )
                luma = sum(
                    0.2126 * red + 0.7152 * green + 0.0722 * blue
                    for red, green, blue in pixels
                ) / max(len(pixels), 1)
                self.assertGreater(luma, 18.0)


if __name__ == "__main__":
    unittest.main()
