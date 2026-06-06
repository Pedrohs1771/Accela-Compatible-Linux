from __future__ import annotations

import sys

from .base import PlatformBackend, SteamLibrary, SteamProfile


def get_backend(platform_name: str | None = None) -> PlatformBackend:
    target = (platform_name or sys.platform).lower()
    if target.startswith("win"):
        from .windows_backend import WindowsPlatformBackend

        return WindowsPlatformBackend()
    from .linux_backend import LinuxPlatformBackend

    return LinuxPlatformBackend()


__all__ = [
    "PlatformBackend",
    "SteamLibrary",
    "SteamProfile",
    "get_backend",
]
