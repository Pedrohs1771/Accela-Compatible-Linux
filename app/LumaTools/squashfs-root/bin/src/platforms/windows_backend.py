from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Mapping

from core.platform.common import normalize_path, parse_libraryfolders_vdf
from utils.steam_config_helper import _replace_or_insert_launch_options

from .base import PlatformBackend


def _resource_path(relative_path: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return str(Path(base) / relative_path)
    return str(Path(__file__).resolve().parents[1] / relative_path)


class WindowsPlatformBackend(PlatformBackend):
    platform_name = "windows"

    def __init__(
        self,
        env: Mapping[str, str] | None = None,
        registry_reader: Callable[[], str | None] | None = None,
        process_runner: Callable[..., subprocess.CompletedProcess] | None = None,
    ):
        self.env = dict(env or os.environ)
        self.registry_reader = registry_reader or self._read_registry_steam_path
        self.process_runner = process_runner or subprocess.run

    def find_steam_install(self) -> Path | None:
        for candidate in self._candidate_steam_roots():
            steamapps = candidate / "steamapps"
            if steamapps.is_dir():
                return candidate
        return None

    def get_steam_executable(self) -> Path | None:
        root = self.find_steam_install()
        if root:
            exe = root / "steam.exe"
            if exe.exists():
                return exe
        on_path = shutil.which("steam.exe") or shutil.which("steam")
        return Path(on_path) if on_path else None

    def get_steam_libraries(self) -> list[Path]:
        root = self.find_steam_install()
        if not root:
            return []
        libraries: list[Path] = [root]
        for library in parse_libraryfolders_vdf(root / "steamapps" / "libraryfolders.vdf"):
            path = Path(library)
            if path not in libraries:
                libraries.append(path)
        return libraries

    def get_lumatools_data_dir(self) -> Path:
        local = self.env.get("LOCALAPPDATA")
        if local:
            return Path(local) / "LumaTools"
        return Path.home() / "AppData" / "Local" / "LumaTools"

    def get_steamcmd_path(self) -> Path:
        return self.get_lumatools_data_dir() / "tools" / "SteamCMD" / "steamcmd.exe"

    def get_depotdownloader_command(self) -> list[str]:
        dotnet = shutil.which("dotnet.exe") or shutil.which("dotnet") or "dotnet"
        return [dotnet, _resource_path("deps/DepotDownloader.dll")]

    def read_libraryfolders_vdf(self, steam_root: str | Path | None = None) -> list[Path]:
        root = Path(steam_root) if steam_root else self.find_steam_install()
        if not root:
            return []
        return [Path(path) for path in parse_libraryfolders_vdf(root / "steamapps" / "libraryfolders.vdf")]

    def read_localconfig_vdf(self, user_id: str, steam_root: str | Path | None = None) -> str:
        path = self._localconfig_path(user_id, steam_root)
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def write_localconfig_vdf(
        self, user_id: str, content: str, steam_root: str | Path | None = None
    ) -> Path:
        path = self._localconfig_path(user_id, steam_root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            backup = path.with_suffix(path.suffix + f".lumatools-{int(time.time())}.bak")
            shutil.copy2(path, backup)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
        return path

    def set_launch_options(self, appid: str | int, launch_options: str) -> bool:
        root = self.find_steam_install()
        if not root:
            return False
        userdata = root / "userdata"
        if not userdata.is_dir():
            return False

        changed_any = False
        for user_dir in userdata.iterdir():
            if not user_dir.is_dir():
                continue
            localconfig = user_dir / "config" / "localconfig.vdf"
            content = ""
            if localconfig.exists():
                content = localconfig.read_text(encoding="utf-8", errors="ignore")
            new_content, changed = _replace_or_insert_launch_options(
                content, str(appid), launch_options
            )
            if changed:
                self.write_localconfig_vdf(user_dir.name, new_content, root)
                changed_any = True
        return changed_any

    def kill_steam(self) -> bool:
        result = self.process_runner(
            ["taskkill", "/IM", "steam.exe", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(getattr(result, "returncode", 1)) in {0, 128}

    def start_steam(self) -> bool:
        exe = self.get_steam_executable()
        if not exe:
            return False
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
        return True

    def ensure_data_layout(self) -> dict[str, Path]:
        root = self.get_lumatools_data_dir()
        layout = {
            "root": root,
            "logs": root / "logs",
            "backups": root / "backups",
            "jobs": root / "jobs",
            "temp": root / "temp",
            "dlc_cache": root / "dlc_cache",
            "workshop_cache": root / "workshop_cache",
            "hubcap_manifests": root / "hubcap_manifests",
            "ryuu_content": root / "ryuu_content",
            "doctor_reports": root / "doctor_reports",
            "online_reports": root / "online_reports",
            "downloads": root / "downloads",
            "tools": root / "tools",
            "depotdownloader": root / "tools" / "DepotDownloader",
            "steamcmd": root / "tools" / "SteamCMD",
            "redist": root / "tools" / "redist",
        }
        for path in layout.values():
            path.mkdir(parents=True, exist_ok=True)
        return layout

    def make_job_layout(self, job_id: str) -> dict[str, Path]:
        root = self.get_temp_job_dir(job_id)
        layout = {
            "root": root,
            "keys": root / "keys.vdf",
            "manifests": root / "manifests",
            "staging": root / "staging",
            "logs": root / "logs",
            "download_plan": root / "download_plan.json",
            "result": root / "result.json",
        }
        for key, path in layout.items():
            if key in {"keys", "download_plan", "result"}:
                path.parent.mkdir(parents=True, exist_ok=True)
            else:
                path.mkdir(parents=True, exist_ok=True)
        return layout

    def is_windows(self) -> bool:
        return True

    def _candidate_steam_roots(self) -> list[Path]:
        candidates: list[Path] = []
        registry_path = self.registry_reader()
        if registry_path:
            candidates.append(Path(registry_path))

        for key in ("PROGRAMFILES(X86)", "PROGRAMFILES"):
            value = self.env.get(key)
            if value:
                candidates.append(Path(value) / "Steam")

        drive = self.env.get("SystemDrive", "C:")
        candidates.extend(
            [
                Path(drive + "\\") / "Program Files (x86)" / "Steam",
                Path(drive + "\\") / "Program Files" / "Steam",
            ]
        )

        seen: set[str] = set()
        result: list[Path] = []
        for candidate in candidates:
            normalized = Path(normalize_path(candidate))
            key = str(normalized).lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result

    def _localconfig_path(self, user_id: str, steam_root: str | Path | None = None) -> Path:
        root = Path(steam_root) if steam_root else self.find_steam_install()
        if not root:
            raise FileNotFoundError("Steam root not found")
        return root / "userdata" / str(user_id) / "config" / "localconfig.vdf"

    @staticmethod
    def _read_registry_steam_path() -> str | None:
        try:
            import winreg
        except ImportError:
            return None

        probes = (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (
                winreg.HKEY_LOCAL_MACHINE,
                r"Software\WOW6432Node\Valve\Steam",
                "InstallPath",
            ),
        )
        for hive, key_path, value_name in probes:
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
                    if value:
                        return str(value)
            except OSError:
                continue
        return None
