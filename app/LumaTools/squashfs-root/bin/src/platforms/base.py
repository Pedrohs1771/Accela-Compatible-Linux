from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class SteamLibrary:
    path: Path
    steamapps: Path
    common: Path
    depotcache: Path


@dataclass(slots=True)
class SteamProfile:
    platform: str
    mode: str
    steam_root: Path | None
    steam_executable: Path | None
    libraries: list[SteamLibrary] = field(default_factory=list)
    userdata_paths: list[Path] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class PlatformBackend:
    platform_name = "unknown"

    def find_steam_install(self) -> Path | None:
        raise NotImplementedError

    def get_steam_executable(self) -> Path | None:
        raise NotImplementedError

    def get_steam_libraries(self) -> list[Path]:
        raise NotImplementedError

    def get_preferred_steam_library(self) -> Path | None:
        libraries = self.get_steam_libraries()
        return libraries[0] if libraries else self.find_steam_install()

    def get_steamapps_dir(self, library: str | Path) -> Path:
        return Path(library) / "steamapps"

    def get_depotcache_dir(self, library: str | Path) -> Path:
        return self.get_steamapps_dir(library) / "depotcache"

    def get_appmanifest_path(self, appid: str | int, library: str | Path) -> Path:
        return self.get_steamapps_dir(library) / f"appmanifest_{appid}.acf"

    def get_common_dir(self, library: str | Path) -> Path:
        return self.get_steamapps_dir(library) / "common"

    def get_game_install_dir(
        self, appid: str | int, installdir: str, library: str | Path
    ) -> Path:
        safe_name = installdir or f"App_{appid}"
        return self.get_common_dir(library) / safe_name

    def get_lumatools_data_dir(self) -> Path:
        raise NotImplementedError

    def get_jobs_dir(self) -> Path:
        return self.get_lumatools_data_dir() / "jobs"

    def get_temp_job_dir(self, job_id: str) -> Path:
        return self.get_jobs_dir() / str(job_id)

    def get_steamcmd_path(self) -> Path:
        raise NotImplementedError

    def get_depotdownloader_command(self) -> list[str]:
        raise NotImplementedError

    def read_libraryfolders_vdf(self, steam_root: str | Path | None = None) -> list[Path]:
        raise NotImplementedError

    def read_localconfig_vdf(self, user_id: str, steam_root: str | Path | None = None) -> str:
        raise NotImplementedError

    def write_localconfig_vdf(
        self, user_id: str, content: str, steam_root: str | Path | None = None
    ) -> Path:
        raise NotImplementedError

    def set_launch_options(self, appid: str | int, launch_options: str) -> bool:
        raise NotImplementedError

    def kill_steam(self) -> bool:
        raise NotImplementedError

    def start_steam(self) -> bool:
        raise NotImplementedError

    def describe(self) -> SteamProfile:
        root = self.find_steam_install()
        libraries = [
            SteamLibrary(
                path=library,
                steamapps=self.get_steamapps_dir(library),
                common=self.get_common_dir(library),
                depotcache=self.get_depotcache_dir(library),
            )
            for library in self.get_steam_libraries()
        ]
        userdata_paths: list[Path] = []
        if root:
            userdata = root / "userdata"
            if userdata.is_dir():
                userdata_paths = [path for path in userdata.iterdir() if path.is_dir()]
        return SteamProfile(
            platform=self.platform_name,
            mode="native",
            steam_root=root,
            steam_executable=self.get_steam_executable(),
            libraries=libraries,
            userdata_paths=userdata_paths,
        )

    def is_windows(self) -> bool:
        return False

    def is_linux(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        profile = self.describe()
        return {
            "platform": profile.platform,
            "mode": profile.mode,
            "steam_root": str(profile.steam_root) if profile.steam_root else None,
            "steam_executable": (
                str(profile.steam_executable) if profile.steam_executable else None
            ),
            "libraries": [str(library.path) for library in profile.libraries],
            "userdata_paths": [str(path) for path in profile.userdata_paths],
            "notes": profile.notes,
        }
