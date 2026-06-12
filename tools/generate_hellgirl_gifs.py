#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance

ROOT = Path(__file__).resolve().parents[1]
THEME_DIR = (
    ROOT
    / "app"
    / "LumaTools"
    / "squashfs-root"
    / "bin"
    / "src"
    / "res"
    / "theme"
    / "hellgirl"
)
OUTPUT_DIR = THEME_DIR.parent.parent / "gif"


def _cover(
    source: Image.Image,
    size: tuple[int, int],
    *,
    anchor: tuple[float, float],
    zoom: float,
    shift: tuple[float, float],
) -> Image.Image:
    width, height = size
    scale = max(width / source.width, height / source.height) * zoom
    resized = source.resize(
        (max(width, round(source.width * scale)), max(height, round(source.height * scale))),
        Image.Resampling.LANCZOS,
    )
    overflow_x = max(0, resized.width - width)
    overflow_y = max(0, resized.height - height)
    left = round(overflow_x * anchor[0] + shift[0])
    top = round(overflow_y * anchor[1] + shift[1])
    left = min(max(left, 0), overflow_x)
    top = min(max(top, 0), overflow_y)
    return resized.crop((left, top, left + width, top + height)).convert("RGB")


def _glitch(frame: Image.Image, frame_index: int, strength: int) -> Image.Image:
    if strength <= 0 or frame_index % 5 not in {1, 2}:
        return frame

    result = frame.copy()
    band_height = max(2, frame.height // 42)
    for band in range(3):
        y = (frame_index * 47 + band * 83) % max(1, frame.height - band_height)
        offset = strength if band % 2 == 0 else -strength
        strip = frame.crop((0, y, frame.width, y + band_height))
        result.paste(strip, (offset, y))
    return result


def _accent_thread(frame: Image.Image, phase: float, opacity: int = 90) -> Image.Image:
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    y = int(frame.height * (0.72 + 0.03 * math.sin(phase)))
    draw.line(
        [(-20, y), (frame.width + 20, y - frame.height // 7)],
        fill=(255, 0, 96, opacity),
        width=max(1, frame.width // 320),
    )
    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


def _moving_glow(frame: Image.Image, phase: float) -> Image.Image:
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    center_y = int((0.15 + 0.7 * ((phase / math.tau) % 1.0)) * frame.height)
    band_height = max(12, frame.height // 18)
    for offset in range(-band_height, band_height + 1):
        distance = abs(offset) / band_height
        alpha = int(28 * (1.0 - distance))
        draw.line(
            [(0, center_y + offset), (frame.width, center_y + offset)],
            fill=(255, 0, 96, alpha),
            width=1,
        )
    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


def _floating_particles(frame: Image.Image, phase: float) -> Image.Image:
    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    progress = (phase / math.tau) % 1.0

    for index in range(16):
        x = int((index * 97 + 31) % frame.width)
        if frame.width * 0.34 < x < frame.width * 0.66:
            x = int(frame.width * (0.22 if index % 2 == 0 else 0.78))
        start_y = (index * 53 + 17) % frame.height
        y = int((start_y - progress * (frame.height * 0.34 + index * 3)) % frame.height)
        pulse = 0.45 + 0.55 * math.sin(phase * 2 + index * 0.9) ** 2
        radius = 1 + index % 2
        alpha = int(55 + 120 * pulse)
        petal = max(2, radius * 2)
        draw.ellipse(
            (x - petal, y - radius, x, y + radius),
            fill=(255, 0, 96, alpha),
        )
        draw.ellipse(
            (x, y - radius, x + petal, y + radius),
            fill=(255, 0, 96, alpha),
        )
        draw.ellipse(
            (x - radius, y - petal, x + radius, y),
            fill=(255, 0, 96, alpha),
        )
        draw.ellipse(
            (x - radius, y, x + radius, y + petal),
            fill=(255, 0, 96, alpha),
        )
        draw.point((x, y), fill=(255, 180, 210, min(255, alpha + 50)))

    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


def _animated_frames(
    source: Image.Image,
    size: tuple[int, int],
    *,
    count: int,
    anchor: tuple[float, float],
    motion: tuple[float, float],
    zoom: float,
    zoom_amplitude: float = 0.012,
    brightness_amplitude: float = 0.06,
    glitch_strength: int = 0,
    thread: bool = False,
    moving_glow: bool = False,
    particles: bool = False,
) -> list[Image.Image]:
    frames: list[Image.Image] = []
    for index in range(count):
        phase = (index / count) * math.tau
        frame = _cover(
            source,
            size,
            anchor=anchor,
            zoom=zoom + zoom_amplitude * math.sin(phase),
            shift=(
                motion[0] * math.sin(phase),
                motion[1] * math.cos(phase),
            ),
        )
        brightness = 0.96 + brightness_amplitude * (
            0.5 + 0.5 * math.sin(phase + 0.8)
        )
        frame = ImageEnhance.Brightness(frame).enhance(brightness)
        frame = _glitch(frame, index, glitch_strength)
        if thread:
            frame = _accent_thread(frame, phase)
        if moving_glow:
            frame = _moving_glow(frame, phase)
        if particles:
            frame = _floating_particles(frame, phase)
        frames.append(frame)
    return frames


def _save_gif(
    frames: list[Image.Image],
    target: Path,
    *,
    duration: int,
    colors: int = 128,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    palette = frames[0].convert("P", palette=Image.Palette.ADAPTIVE, colors=colors)
    quantized = [palette]
    quantized.extend(frame.quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG) for frame in frames[1:])
    quantized[0].save(
        target,
        save_all=True,
        append_images=quantized[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )


def _load_sources() -> dict[str, Image.Image]:
    sources = {}
    for name in ("main", "boat", "eye", "shrine"):
        path = THEME_DIR / f"{name}.png"
        sources[name] = Image.open(path).convert("RGB")
    return sources


def generate() -> None:
    sources = _load_sources()

    main_frames = _animated_frames(
        sources["main"],
        (640, 480),
        count=24,
        anchor=(0.5, 0.48),
        motion=(0, 0),
        zoom=1.01,
        zoom_amplitude=0.0,
        brightness_amplitude=0.035,
        thread=True,
        moving_glow=True,
        particles=True,
    )
    _save_gif(main_frames, OUTPUT_DIR / "main.gif", duration=80, colors=160)

    download_specs = [
        ("boat", (0.50, 0.42), (5, 8), 1.03, 0, False),
        ("eye", (0.48, 0.50), (8, 2), 1.05, 5, True),
        ("shrine", (0.50, 0.52), (3, 7), 1.04, 0, False),
        ("main", (0.50, 0.44), (5, 4), 1.13, 3, True),
        ("boat", (0.43, 0.33), (8, 5), 1.17, 4, False),
        ("eye", (0.33, 0.48), (10, 3), 1.14, 7, True),
        ("shrine", (0.50, 0.34), (4, 9), 1.15, 3, False),
        ("main", (0.50, 0.32), (7, 3), 1.28, 5, False),
        ("boat", (0.55, 0.58), (6, 9), 1.22, 0, True),
        ("eye", (0.62, 0.50), (9, 2), 1.20, 6, False),
        ("shrine", (0.50, 0.68), (3, 8), 1.22, 4, True),
    ]
    for index, (source_name, anchor, motion, zoom, glitch, thread) in enumerate(
        download_specs,
        start=1,
    ):
        frames = _animated_frames(
            sources[source_name],
            (420, 420),
            count=12,
            anchor=anchor,
            motion=motion,
            zoom=zoom,
            zoom_amplitude=0.018,
            brightness_amplitude=0.08,
            glitch_strength=glitch,
            thread=thread,
            moving_glow=index % 3 == 0,
            particles=index % 2 == 1,
        )
        _save_gif(
            frames,
            OUTPUT_DIR / f"downloading_default{index}.gif",
            duration=100,
        )

    navi_frames = _animated_frames(
        sources["eye"],
        (84, 29),
        count=8,
        anchor=(0.26, 0.48),
        motion=(3, 1),
        zoom=1.38,
        glitch_strength=2,
    )
    _save_gif(navi_frames, OUTPUT_DIR / "navi.gif", duration=120, colors=64)


if __name__ == "__main__":
    generate()
