from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkshopProfile:
    engine: str
    target_root: str
    strategy: str = "isolated_item_directory"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_workshop_profile(game_dir: str | Path) -> WorkshopProfile:
    root = Path(game_dir).expanduser().resolve()
    checks = (
        ("unreal", root / "Content" / "Paks", root / "Content" / "Paks" / "~mods"),
        ("bepinex", root / "BepInEx" / "plugins", root / "BepInEx" / "plugins"),
        ("melonloader", root / "MelonLoader" / "Mods", root / "MelonLoader" / "Mods"),
        ("source", root / "gameinfo.txt", root / "custom"),
        ("source_addons", root / "addons", root / "addons"),
        ("generic_mods", root / "Mods", root / "Mods"),
        ("generic_mods", root / "mods", root / "mods"),
    )
    for engine, marker, target in checks:
        if marker.exists():
            return WorkshopProfile(engine=engine, target_root=str(target))
    return WorkshopProfile(engine="generic", target_root=str(root / "Workshop"))
