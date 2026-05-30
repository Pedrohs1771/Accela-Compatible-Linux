from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class SteamInstall:
    platform: str
    mode: str
    root: Optional[str]
    libraries: list[str] = field(default_factory=list)
    launch_command: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class PlatformBackend:
    platform_name = "unknown"

    def find_steam_install(self) -> Optional[str]:
        return self.describe_steam_install().root

    def get_steam_libraries(self) -> list[str]:
        return self.describe_steam_install().libraries

    def get_preferred_steam_library(self) -> Optional[str]:
        install = self.describe_steam_install()
        if len(install.libraries) == 1:
            return install.libraries[0]
        if install.root:
            return install.root
        return install.libraries[0] if install.libraries else None

    def get_steam_launch_command(self) -> list[str]:
        return list(self.describe_steam_install().launch_command)

    def describe_steam_install(self) -> SteamInstall:
        raise NotImplementedError
