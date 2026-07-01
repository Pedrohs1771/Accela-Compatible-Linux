from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from managers.gif_manager import GIFManager


class GifColorizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = GIFManager.__new__(GIFManager)

    def test_rgba_colorization_preserves_pixel_brightness(self) -> None:
        source = np.array(
            [[[180, 40, 70, 255], [70, 160, 110, 255], [30, 50, 170, 255]]],
            dtype=np.float32,
        )

        result = self.manager._apply_color_transform(
            source, target_h=345.0, target_s=0.55, target_v=0.75
        )

        np.testing.assert_allclose(
            np.max(result[..., :3], axis=-1),
            np.max(source[..., :3], axis=-1),
            atol=1.0,
        )

    def test_palette_colorization_preserves_entry_brightness(self) -> None:
        palette = [180, 40, 70, 70, 160, 110, 30, 50, 170, 25, 25, 25]

        result = self.manager._apply_color_to_palette(
            palette, target_h=345.0, target_s=0.55, target_v=0.75
        )

        source_values = np.max(np.array(palette).reshape(-1, 3), axis=1)
        result_values = np.max(np.array(result).reshape(-1, 3), axis=1)
        np.testing.assert_allclose(result_values, source_values, atol=1.0)

    def test_cache_key_separates_copy_and_colorization_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "sample.gif"
            source.write_bytes(b"GIF89a-cache-test")

            colorized_hash = self.manager._calculate_cache_hash(source, False)
            copied_hash = self.manager._calculate_cache_hash(source, True)

            self.assertIsNotNone(colorized_hash)
            self.assertIsNotNone(copied_hash)
            self.assertNotEqual(colorized_hash, copied_hash)

    def test_gif_is_colorized_before_atomic_publish(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = root / "source.gif"
            output = root / "output.gif"
            palette = [0, 0, 0, 180, 40, 70, 70, 160, 110] + [0] * (256 * 3 - 9)
            first = Image.new("P", (2, 1))
            second = Image.new("P", (2, 1))
            first.putpalette(palette)
            second.putpalette(palette)
            first.putdata([1, 2])
            second.putdata([2, 1])
            first.save(
                source,
                save_all=True,
                append_images=[second],
                duration=[80, 90],
                loop=0,
                disposal=2,
            )

            self.assertTrue(
                self.manager._apply_color_to_gif(
                    source, output, "#3AA76D", source.name
                )
            )

            with Image.open(source) as original, Image.open(output) as colorized:
                self.assertEqual(colorized.n_frames, original.n_frames)
                original_pixel = original.convert("RGB").getpixel((0, 0))
                colorized_pixel = colorized.convert("RGB").getpixel((0, 0))
                self.assertNotEqual(colorized_pixel, original_pixel)
                self.assertEqual(max(colorized_pixel), max(original_pixel))


if __name__ == "__main__":
    unittest.main()
