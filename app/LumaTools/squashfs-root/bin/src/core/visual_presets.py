from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from utils.paths import Paths


DEFAULT_VISUAL_PRESET = "hellgirl"


@dataclass(frozen=True)
class VisualPreset:
    key: str
    label: str
    accent: str
    background: str
    gif_resource: str

    @property
    def gif_dir(self) -> Path:
        return Paths.resource(self.gif_resource)


VISUAL_PRESETS: tuple[VisualPreset, ...] = (
    VisualPreset(
        key="hellgirl",
        label="Hell Girl / Jigoku Shoujo",
        accent="#C06C84",
        background="#000000",
        gif_resource="gif",
    ),
    VisualPreset(
        key="wired_lain",
        label="Serial Experiments Lain",
        accent="#D84A6A",
        background="#020104",
        gif_resource="visual_presets/wired_lain/gif",
    ),
    VisualPreset(
        key="ghoul_touka",
        label="Tokyo Ghoul / Touka",
        accent="#E23B55",
        background="#030203",
        gif_resource="visual_presets/ghoul_touka/gif",
    ),
    VisualPreset(
        key="clock_homura",
        label="Madoka Magica / Homura",
        accent="#B66CFF",
        background="#030106",
        gif_resource="visual_presets/clock_homura/gif",
    ),
)


def all_visual_presets() -> tuple[VisualPreset, ...]:
    return VISUAL_PRESETS


def normalize_visual_preset(value: str | None) -> str:
    key = str(value or "").strip()
    valid = {preset.key for preset in VISUAL_PRESETS}
    return key if key in valid else DEFAULT_VISUAL_PRESET


def get_visual_preset(value: str | None) -> VisualPreset:
    key = normalize_visual_preset(value)
    for preset in VISUAL_PRESETS:
        if preset.key == key:
            return preset
    return VISUAL_PRESETS[0]
