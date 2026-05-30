from __future__ import annotations

import os
from pathlib import Path

from core.linux_paths import (
    detect_linux_steam_mode,
    get_steam_launch_command,
    list_steam_roots,
)

from .base import PlatformBackend, SteamInstall
from .common import normalize_path, parse_libraryfolders_vdf


class LinuxBackend(PlatformBackend):
    platform_name = "linux"

    def __init__(self, preferred_mode: str | None = None):
        self.preferred_mode = preferred_mode

    def describe_steam_install(self) -> SteamInstall:
        mode = self.preferred_mode or detect_linux_steam_mode()
        roots = list_steam_roots(preferred_mode=mode)
        libraries: list[str] = []
        seen: set[str] = set()

        for root in roots:
            root_str = normalize_path(root)
            if root_str not in seen:
                seen.add(root_str)
                libraries.append(root_str)

            vdf_path = Path(root_str) / "steamapps" / "libraryfolders.vdf"
            for library in parse_libraryfolders_vdf(vdf_path):
                if library in seen:
                    continue
                seen.add(library)
                libraries.append(library)

        root = libraries[0] if libraries else None
        launch_command = get_steam_launch_command(mode) or []
        notes: list[str] = []
        if not root:
            notes.append("Steam Linux não encontrada em paths nativos, Flatpak ou Snap.")

        return SteamInstall(
            platform=self.platform_name,
            mode=mode,
            root=root,
            libraries=libraries,
            launch_command=launch_command,
            notes=notes,
        )
