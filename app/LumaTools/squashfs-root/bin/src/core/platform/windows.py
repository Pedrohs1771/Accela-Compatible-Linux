from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Mapping, Optional

from .base import PlatformBackend, SteamInstall
from .common import normalize_path, parse_libraryfolders_vdf


class WindowsBackend(PlatformBackend):
    platform_name = "windows"

    def __init__(
        self,
        env: Optional[Mapping[str, str]] = None,
        registry_reader: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.env = dict(env or os.environ)
        self.registry_reader = registry_reader or self._read_registry_path

    def describe_steam_install(self) -> SteamInstall:
        root = self._detect_root()
        libraries: list[str] = []
        notes: list[str] = []
        if root:
            libraries.append(root)
            vdf_path = Path(root) / "steamapps" / "libraryfolders.vdf"
            for library in parse_libraryfolders_vdf(vdf_path):
                if library not in libraries:
                    libraries.append(library)
        else:
            notes.append("Steam Windows não encontrada em registry nem em Program Files.")

        launch_command = []
        if root:
            exe_path = Path(root) / "steam.exe"
            if exe_path.exists():
                launch_command = [str(exe_path)]
        if not launch_command:
            steam_on_path = shutil.which("steam") or shutil.which("steam.exe")
            if steam_on_path:
                launch_command = [steam_on_path]

        return SteamInstall(
            platform=self.platform_name,
            mode="native",
            root=root,
            libraries=libraries,
            launch_command=launch_command,
            notes=notes,
        )

    def _detect_root(self) -> Optional[str]:
        registry_path = self.registry_reader()
        if registry_path and os.path.isdir(os.path.join(registry_path, "steamapps")):
            return normalize_path(registry_path)

        candidates = self._candidate_roots()
        for candidate in candidates:
            if os.path.isdir(os.path.join(candidate, "steamapps")):
                return normalize_path(candidate)
        return None

    def _candidate_roots(self) -> list[str]:
        candidates: list[str] = []
        for env_key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = self.env.get(env_key)
            if not base:
                continue
            candidates.append(os.path.join(base, "Steam"))
            candidates.append(os.path.join(base, "Programs", "Steam"))

        drive = self.env.get("SystemDrive", "C:")
        candidates.extend(
            [
                os.path.join(drive, os.sep, "Steam"),
                os.path.join(drive, os.sep, "Program Files (x86)", "Steam"),
                os.path.join(drive, os.sep, "Program Files", "Steam"),
            ]
        )
        deduped: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = normalize_path(candidate)
            if normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        return deduped

    @staticmethod
    def _read_registry_path() -> Optional[str]:
        try:
            import winreg

            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            try:
                steam_path, _ = winreg.QueryValueEx(key, "SteamPath")
                return steam_path
            finally:
                winreg.CloseKey(key)
        except OSError:
            return None
