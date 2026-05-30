from __future__ import annotations

import sys

from .base import PlatformBackend, SteamInstall
from .linux import LinuxBackend
from .windows import WindowsBackend


def get_platform_backend(platform_name: str | None = None) -> PlatformBackend:
    target = (platform_name or sys.platform).lower()
    if target.startswith("win"):
        return WindowsBackend()
    return LinuxBackend()


__all__ = [
    "PlatformBackend",
    "SteamInstall",
    "LinuxBackend",
    "WindowsBackend",
    "get_platform_backend",
]
