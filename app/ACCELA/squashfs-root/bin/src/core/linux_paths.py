import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

FLATPAK_APP_ID = "com.valvesoftware.Steam"


def _home() -> Path:
    return Path.home()


def _candidate_roots_by_mode() -> dict[str, list[Path]]:
    home = _home()
    flatpak_prefix = home / ".var" / "app" / FLATPAK_APP_ID
    snap_prefix = home / "snap" / "steam" / "common"
    return {
        "native": [
            home / ".steam" / "root",
            home / ".steam" / "steam",
            home / ".steam" / "debian-installation",
            home / ".local" / "share" / "Steam",
        ],
        "flatpak": [
            flatpak_prefix / "data" / "Steam",
            flatpak_prefix / ".local" / "share" / "Steam",
            flatpak_prefix / ".steam" / "root",
            flatpak_prefix / ".steam" / "steam",
        ],
        "snap": [
            snap_prefix / ".steam" / "steam",
            snap_prefix / ".local" / "share" / "Steam",
        ],
    }


def _flatpak_markers() -> list[Path]:
    home = _home()
    return [
        home / ".local" / "share" / "flatpak" / "app" / FLATPAK_APP_ID,
        home / ".var" / "app" / FLATPAK_APP_ID,
    ]


def _snap_markers() -> list[Path]:
    home = _home()
    return [
        home / "snap" / "steam",
    ]


def _is_steam_root(path: Path) -> bool:
    return path.is_dir() and (path / "steamapps").is_dir()


def _can_run(command: list[str]) -> bool:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def detect_linux_steam_mode() -> str:
    roots = _candidate_roots_by_mode()
    native_roots_exist = any(_is_steam_root(path) for path in roots["native"])

    if shutil.which("flatpak") and _can_run(["flatpak", "info", FLATPAK_APP_ID]):
        return "flatpak"
    if any(_is_steam_root(path) for path in roots["flatpak"]):
        return "flatpak"
    if any(marker.exists() for marker in _flatpak_markers()) and not native_roots_exist:
        return "flatpak"

    if shutil.which("snap") and _can_run(["snap", "list", "steam"]):
        return "snap"
    if any(_is_steam_root(path) for path in roots["snap"]):
        return "snap"
    if any(marker.exists() for marker in _snap_markers()) and not native_roots_exist:
        return "snap"

    if native_roots_exist:
        return "native"
    if shutil.which("steam"):
        return "native"

    return "missing"


def iter_steam_root_candidates(preferred_mode: Optional[str] = None) -> Iterable[tuple[str, Path]]:
    candidate_map = _candidate_roots_by_mode()
    ordered_modes = ["native", "flatpak", "snap"]

    if preferred_mode in ordered_modes:
        ordered_modes = [preferred_mode] + [
            mode for mode in ordered_modes if mode != preferred_mode
        ]

    seen: set[Path] = set()
    for mode in ordered_modes:
        for candidate in candidate_map[mode]:
            resolved = candidate.expanduser()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield mode, resolved


def list_steam_roots(preferred_mode: Optional[str] = None) -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for mode, candidate in iter_steam_root_candidates(preferred_mode):
        if not _is_steam_root(candidate):
            continue
        resolved = candidate.resolve()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
        logger.debug("Detected Steam root (%s): %s", mode, resolved)
    return roots


def find_primary_steam_root(preferred_mode: Optional[str] = None) -> Optional[Path]:
    roots = list_steam_roots(preferred_mode=preferred_mode)
    return roots[0] if roots else None


def get_steam_launch_command(mode: Optional[str] = None) -> Optional[list[str]]:
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        if shutil.which("flatpak"):
            return ["flatpak", "run", FLATPAK_APP_ID]
        if shutil.which("steam"):
            return ["steam"]
        return None

    if steam_mode == "snap":
        if shutil.which("snap"):
            return ["snap", "run", "steam"]
        if shutil.which("steam"):
            return ["steam"]
        return None

    wrapper = _home() / ".local" / "share" / "SLSsteam" / "path" / "steam"
    if wrapper.exists() and os.access(wrapper, os.X_OK):
        return [str(wrapper)]

    if shutil.which("steam"):
        return ["steam"]

    root = find_primary_steam_root(preferred_mode="native")
    if root is not None:
        steam_sh = root / "steam.sh"
        if steam_sh.exists() and os.access(steam_sh, os.X_OK):
            return [str(steam_sh)]

    return None


def flatpak_slssteam_dir() -> Path:
    return _home() / ".var" / "app" / FLATPAK_APP_ID / ".local" / "share" / "SLSsteam"


def native_slssteam_dir() -> Path:
    return _home() / ".local" / "share" / "SLSsteam"


def get_slssteam_install_dir(mode: Optional[str] = None) -> Path:
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        return flatpak_slssteam_dir()
    return native_slssteam_dir()


def get_slssteam_setup_command(mode: Optional[str] = None) -> str:
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        return "flatpak-install"
    return "install"


def find_slssteam_paths(mode: Optional[str] = None) -> tuple[Optional[str], Optional[str]]:
    steam_mode = mode or detect_linux_steam_mode()
    dirs: list[Path] = []

    if steam_mode == "flatpak":
        dirs.extend(
            [
                flatpak_slssteam_dir(),
                _home() / ".var" / "app" / FLATPAK_APP_ID / "data" / "SLSsteam",
                native_slssteam_dir(),
            ]
        )
    else:
        dirs.extend([native_slssteam_dir(), flatpak_slssteam_dir()])

    slssteam_path: Optional[str] = None
    library_inject_path: Optional[str] = None

    for base_dir in dirs:
        if slssteam_path is None:
            candidate = base_dir / "SLSsteam.so"
            if candidate.exists():
                slssteam_path = str(candidate.resolve())
        if library_inject_path is None:
            candidate = base_dir / "library-inject.so"
            if candidate.exists():
                library_inject_path = str(candidate.resolve())
        if slssteam_path and library_inject_path:
            return slssteam_path, library_inject_path

    if slssteam_path is None:
        system_slssteam = Path("/usr/lib32/libSLSsteam.so")
        if system_slssteam.exists():
            slssteam_path = str(system_slssteam)

    if library_inject_path is None:
        system_inject = Path("/usr/lib32/libSLS-library-inject.so")
        if system_inject.exists():
            library_inject_path = str(system_inject)

    return slssteam_path, library_inject_path
