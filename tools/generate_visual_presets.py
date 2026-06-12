#!/usr/bin/env python3
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "tools" / "assets" / "visual_preset_reference.png"
PRESET_ROOT = (
    ROOT
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
    / "res"
    / "visual_presets"
)


@dataclass(frozen=True)
class Preset:
    slug: str
    panel: int
    accent: tuple[int, int, int]
    secondary: tuple[int, int, int]
    motif: str


PRESETS = (
    Preset(
        slug="wired_lain",
        panel=0,
        accent=(216, 74, 106),
        secondary=(42, 8, 24),
        motif="wired",
    ),
    Preset(
        slug="ghoul_touka",
        panel=1,
        accent=(226, 59, 85),
        secondary=(54, 4, 12),
        motif="ghoul",
    ),
    Preset(
        slug="clock_homura",
        panel=2,
        accent=(182, 108, 255),
        secondary=(38, 12, 68),
        motif="clock",
    ),
)

DOWNLOAD_CROPS = (
    (0.04, 0.00, 0.96, 0.55),
    (0.10, 0.08, 0.90, 0.68),
    (0.00, 0.24, 1.00, 0.84),
    (0.18, 0.00, 0.82, 0.46),
    (0.00, 0.42, 1.00, 1.00),
    (0.23, 0.14, 0.77, 0.62),
    (0.00, 0.05, 0.68, 0.66),
    (0.32, 0.05, 1.00, 0.66),
    (0.08, 0.34, 0.92, 0.92),
    (0.00, 0.00, 0.74, 0.82),
    (0.26, 0.00, 1.00, 0.82),
)


def _rgba(color: tuple[int, int, int], alpha: int) -> tuple[int, int, int, int]:
    return color[0], color[1], color[2], alpha


def _panel(sheet: Image.Image, index: int) -> Image.Image:
    panel_w = sheet.width // 3
    return sheet.crop((panel_w * index, 0, panel_w * (index + 1), sheet.height))


def _relative_crop(image: Image.Image, crop: tuple[float, float, float, float]) -> Image.Image:
    left, top, right, bottom = crop
    return image.crop(
        (
            round(left * image.width),
            round(top * image.height),
            round(right * image.width),
            round(bottom * image.height),
        )
    )


def _fit_cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.42))


def _fit_contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    work = image.copy()
    work.thumbnail(size, Image.Resampling.LANCZOS)
    canvas.alpha_composite(work, ((size[0] - work.width) // 2, (size[1] - work.height) // 2))
    return canvas


def _grade(image: Image.Image, brightness: float = 0.82, contrast: float = 1.18) -> Image.Image:
    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    return image


def _vignette(image: Image.Image, strength: int = 185) -> None:
    w, h = image.size
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)
    for radius in range(max(w, h), 0, -18):
        value = int(strength * (1 - radius / max(w, h)))
        draw.ellipse(
            (w / 2 - radius, h / 2 - radius, w / 2 + radius, h / 2 + radius),
            fill=max(0, min(strength, value)),
        )
    shade = Image.new("RGBA", (w, h), (0, 0, 0, strength))
    shade.putalpha(mask)
    image.alpha_composite(shade)


def _scanlines(image: Image.Image, alpha: int = 20) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    for y in range(0, image.height, 4):
        draw.line((0, y, image.width, y), fill=(255, 255, 255, alpha))
    for x in range(0, image.width, 96):
        draw.line((x, 0, x, image.height), fill=(255, 255, 255, alpha // 4))


def _soft_glow(
    image: Image.Image,
    box: tuple[float, float, float, float],
    color: tuple[int, int, int],
    alpha: int,
    blur: int,
) -> None:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=_rgba(color, alpha))
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def _static_motif(image: Image.Image, preset: Preset, variant: int) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = image.size
    accent = preset.accent
    secondary = preset.secondary

    if preset.motif == "wired":
        rng = random.Random(4100 + variant)
        for i in range(12):
            y = rng.randrange(-20, h + 20)
            kink_x = rng.randrange(0, w)
            points = [(-20, y), (kink_x, y + rng.randrange(-30, 31)), (w + 20, y + rng.randrange(-18, 19))]
            draw.line(points, fill=_rgba(accent, 34), width=1)
            draw.rectangle((kink_x - 3, points[1][1] - 3, kink_x + 3, points[1][1] + 3), outline=_rgba(accent, 75))
        _scanlines(image, 22)
    elif preset.motif == "ghoul":
        for i in range(8):
            side = -1 if i % 2 else 1
            cx = w * (0.5 + side * (0.18 + i * 0.025))
            cy = h * (0.22 + i * 0.085)
            size = 24 + i * 5
            draw.polygon(
                [(cx, cy - size), (cx + side * size * 0.85, cy), (cx, cy + size)],
                fill=_rgba(accent, 28 + i * 7),
            )
        _soft_glow(image, (w * 0.18, h * 0.06, w * 0.82, h * 0.70), accent, 26, 26)
    elif preset.motif == "clock":
        for i, radius in enumerate((0.22, 0.32, 0.43)):
            cx = w * (0.22 + i * 0.25)
            cy = h * (0.24 + i * 0.10)
            r = min(w, h) * radius
            box = (cx - r, cy - r, cx + r, cy + r)
            draw.ellipse(box, outline=_rgba(accent, 42 + i * 18), width=1 + (i % 2))
            for tick in range(12):
                angle = tick / 12 * math.tau
                x = cx + math.cos(angle) * r
                y = cy + math.sin(angle) * r
                draw.ellipse((x - 1.7, y - 1.7, x + 1.7, y + 1.7), fill=_rgba(accent, 70))
        _soft_glow(image, (w * 0.28, h * 0.06, w * 0.98, h * 0.78), secondary, 60, 40)


def _particle(draw: ImageDraw.ImageDraw, x: float, y: float, size: float, preset: Preset, alpha: int) -> None:
    color = preset.accent
    if preset.motif == "wired":
        draw.rectangle((x - size, y - size, x + size, y + size), outline=_rgba(color, alpha), width=1)
        draw.line((x - size * 3, y, x + size * 3, y), fill=_rgba(color, alpha // 2), width=1)
    elif preset.motif == "ghoul":
        draw.polygon(
            [
                (x, y - size * 1.8),
                (x + size * 1.1, y),
                (x, y + size * 1.8),
                (x - size * 1.1, y),
            ],
            fill=_rgba(color, alpha),
        )
    else:
        draw.ellipse((x - size, y - size, x + size, y + size), fill=_rgba(color, alpha))
        draw.arc((x - size * 3, y - size * 3, x + size * 3, y + size * 3), 40, 210, fill=_rgba(color, alpha // 2), width=1)


def _animated_overlay(image: Image.Image, preset: Preset, frame: int, frames: int, variant: int) -> Image.Image:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer, "RGBA")
    rng = random.Random(7200 + variant)
    progress = frame / frames
    w, h = image.size
    count = 20 if min(w, h) > 100 else 7

    for i in range(count):
        base_x = rng.randrange(0, w)
        base_y = rng.randrange(0, h)
        drift = math.sin(progress * math.tau + i * 0.7) * (8 + i % 4)
        x = (base_x + drift) % w
        y = (base_y - progress * (h * 0.18 + i * 2.4)) % h
        alpha = int(45 + 75 * (0.5 + 0.5 * math.sin(progress * math.tau + i)))
        _particle(draw, x, y, 2.0 + i % 4, preset, alpha)

    if preset.motif == "wired" and frame % 5 in {1, 2}:
        band_h = max(2, h // 42)
        y = (frame * 23 + variant * 17) % max(1, h - band_h)
        strip = image.crop((0, y, w, y + band_h))
        image = image.copy()
        image.alpha_composite(strip, (5 if frame % 2 else -5, y))

    pulse = int(18 + 18 * (0.5 + 0.5 * math.sin(progress * math.tau)))
    _soft_glow(layer, (w * 0.24, h * 0.05, w * 0.76, h * 0.66), preset.accent, pulse, max(14, w // 18))
    image.alpha_composite(layer)
    return image


def _main_base(panel: Image.Image, preset: Preset) -> Image.Image:
    size = (640, 480)
    if preset.motif == "ghoul":
        bg_brightness, bg_contrast = 0.76, 1.18
        character_size = (410, 470)
        character_brightness, character_contrast = 1.95, 1.06
        vignette_strength, halo_alpha = 46, 106
    elif preset.motif == "clock":
        bg_brightness, bg_contrast = 0.72, 1.18
        character_size = (430, 470)
        character_brightness, character_contrast = 1.86, 1.08
        vignette_strength, halo_alpha = 54, 96
    else:
        bg_brightness, bg_contrast = 0.62, 1.28
        character_size = (390, 470)
        character_brightness, character_contrast = 1.50, 1.08
        vignette_strength, halo_alpha = 72, 72

    bg = _fit_cover(panel, size).filter(ImageFilter.GaussianBlur(10))
    bg = _grade(bg, brightness=bg_brightness, contrast=bg_contrast).convert("RGBA")
    _static_motif(bg, preset, 0)

    full = _fit_contain(panel, character_size)
    full = _grade(
        full,
        brightness=character_brightness,
        contrast=character_contrast,
    ).convert("RGBA")
    x = (size[0] - full.width) // 2
    y = 5
    _soft_glow(
        bg,
        (x - 70, y - 18, x + full.width + 70, y + full.height + 26),
        preset.accent,
        halo_alpha,
        38,
    )
    bg.alpha_composite(full, (x, y))
    _vignette(bg, vignette_strength)
    return bg


def _download_base(panel: Image.Image, preset: Preset, crop: tuple[float, float, float, float], variant: int) -> Image.Image:
    size = (420, 420)
    source = _relative_crop(panel, crop)
    base = _fit_cover(source, size).convert("RGBA")
    base = _grade(base, brightness=0.72, contrast=1.24).convert("RGBA")
    _static_motif(base, preset, variant)
    _vignette(base, 128)
    return base


def _navi_base(panel: Image.Image, preset: Preset) -> Image.Image:
    crop = _relative_crop(panel, (0.08, 0.05, 0.92, 0.34))
    base = _fit_cover(crop, (84, 29)).convert("RGBA")
    base = _grade(base, brightness=0.80, contrast=1.42).convert("RGBA")
    _scanlines(base, 32)
    _soft_glow(base, (0, 0, 84, 29), preset.accent, 28, 8)
    return base


def _frames(base: Image.Image, preset: Preset, variant: int, count: int) -> list[Image.Image]:
    return [
        _animated_overlay(base.copy(), preset, frame, count, variant).convert("RGB")
        for frame in range(count)
    ]


def _save_gif(frames: list[Image.Image], target: Path, duration: int, colors: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    palette = frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=colors)
    quantized = [palette]
    quantized.extend(
        frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        for frame in frames[1:]
    )
    quantized[0].save(
        target,
        save_all=True,
        append_images=quantized[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )


def generate() -> None:
    if not REFERENCE.exists():
        raise SystemExit(f"Reference sheet not found: {REFERENCE}")

    sheet = Image.open(REFERENCE).convert("RGBA")
    for preset in PRESETS:
        panel = _panel(sheet, preset.panel)
        out = PRESET_ROOT / preset.slug / "gif"

        _save_gif(_frames(_main_base(panel, preset), preset, 0, 18), out / "main.gif", duration=95, colors=128)
        _save_gif(_frames(_navi_base(panel, preset), preset, 30, 8), out / "navi.gif", duration=130, colors=64)

        for index, crop in enumerate(DOWNLOAD_CROPS, start=1):
            frames = _frames(_download_base(panel, preset, crop, index), preset, index, 10)
            _save_gif(frames, out / f"downloading_default{index}.gif", duration=115, colors=112)

        print(f"generated {preset.slug}")


if __name__ == "__main__":
    generate()
