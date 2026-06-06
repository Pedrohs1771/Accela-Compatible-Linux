from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from core.platform.linux import LinuxBackend
from utils.helpers import get_base_path, resource_path
from utils.steam_config_helper import set_steam_launch_options

from .base import PlatformBackend


class LinuxPlatformBackend(PlatformBackend):
    platform_name = "linux"

    def __init__(self, inner: LinuxBackend | None = None):
        self.inner = inner or LinuxBackend()

    def find_steam_install(self) -> Path | None:
        root = self.inner.find_steam_install()
        return Path(root) if root else None

    def get_steam_executable(self) -> Path | None:
        for candidate in self.inner.get_steam_launch_command():
            if candidate:
                resolved = shutil.which(candidate) or candidate
                return Path(resolved)
        return None

    def get_steam_libraries(self) -> list[Path]:
        return [Path(path) for path in self.inner.get_steam_libraries()]

    def get_lumatools_data_dir(self) -> Path:
        return Path(get_base_path())

    def get_steamcmd_path(self) -> Path:
        return self.get_lumatools_data_dir() / "steamcmd" / "steamcmd.sh"

    def get_depotdownloader_command(self) -> list[str]:
        dotnet = shutil.which("dotnet") or "dotnet"
        return [dotnet, resource_path("deps/DepotDownloader.dll")]

    def read_libraryfolders_vdf(self, steam_root: str | Path | None = None) -> list[Path]:
        root = Path(steam_root) if steam_root else self.find_steam_install()
        if not root:
            return []
        return [
            path
            for path in (
                root / "steamapps" / "libraryfolders.vdf",
                root / "config" / "libraryfolders.vdf",
            )
            if path.exists()
        ]

    def read_localconfig_vdf(self, user_id: str, steam_root: str | Path | None = None) -> str:
        root = Path(steam_root) if steam_root else self.find_steam_install()
        if not root:
            return ""
        path = root / "userdata" / str(user_id) / "config" / "localconfig.vdf"
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return ""

    def write_localconfig_vdf(
        self, user_id: str, content: str, steam_root: str | Path | None = None
    ) -> Path:
        root = Path(steam_root) if steam_root else self.find_steam_install()
        if not root:
            raise FileNotFoundError("Steam root not found")
        path = root / "userdata" / str(user_id) / "config" / "localconfig.vdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def set_launch_options(self, appid: str | int, launch_options: str) -> bool:
        root = self.find_steam_install()
        return bool(root and set_steam_launch_options(str(root), str(appid), launch_options))

    def kill_steam(self) -> bool:
        return subprocess.run(["pkill", "-f", "steam"], check=False).returncode in {0, 1}

    def start_steam(self) -> bool:
        exe = self.get_steam_executable()
        if not exe:
            return False
        subprocess.Popen([str(exe)])
        return True

    def is_linux(self) -> bool:
        return True
