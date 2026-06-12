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


def _read_proc_cmdline(pid_dir: Path) -> str:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()


def _read_proc_environ(pid_dir: Path) -> str:
    try:
        raw = (pid_dir / "environ").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b"\n").decode("utf-8", errors="ignore")


def _read_proc_comm(pid_dir: Path) -> str:
    try:
        return (pid_dir / "comm").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""


def _read_proc_exe(pid_dir: Path) -> Optional[Path]:
    try:
        return Path(os.readlink(pid_dir / "exe"))
    except OSError:
        return None


def _steam_root_from_executable(executable: Optional[Path]) -> Optional[Path]:
    if executable is None:
        return None

    path = executable.expanduser()
    candidates: list[Path] = []
    if path.name == "steam.sh":
        candidates.append(path.parent)
    if path.parent.name in {"ubuntu12_32", "ubuntu12_64"}:
        candidates.append(path.parent.parent)
    candidates.extend(list(path.parents)[:6])

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if _is_steam_root(candidate):
            return candidate
    return None


def _steam_root_from_environ(environ: str) -> Optional[Path]:
    values: dict[str, str] = {}
    for line in (environ or "").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            values[key.strip()] = value.strip()

    for key in ("STEAM_COMPAT_CLIENT_INSTALL_PATH", "STEAMROOT"):
        raw_path = values.get(key)
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if _is_steam_root(candidate):
            return candidate
    return None


def _classify_steam_process(comm: str, cmdline: str, environ: str = "") -> Optional[str]:
    name = (comm or "").strip().lower()
    cmd = (cmdline or "").strip().lower()
    env = (environ or "").lower()
    first_arg = Path(cmd.split(" ", 1)[0]).name if cmd else ""
    flatpak_marker = f".var/app/{FLATPAK_APP_ID.lower()}"

    is_flatpak_steam = (
        name == "flatpak"
        and " run " in f" {cmd} "
        and FLATPAK_APP_ID.lower() in cmd
    )
    is_snap_steam = (
        (name == "snap" and " run " in f" {cmd} " and " steam" in f" {cmd}")
        or "snap_name=steam" in env
    )
    is_steam_binary = (
        name in {"steam", "steamwebhelper", "steam-runtime-launcher-service"}
        or name.startswith("steam-")
        or first_arg in {"steam", "steam.sh", "steamwebhelper"}
        or first_arg.startswith("steam-")
    )

    if not (is_flatpak_steam or is_snap_steam or is_steam_binary):
        return None
    if (
        is_flatpak_steam
        or FLATPAK_APP_ID.lower() in cmd
        or FLATPAK_APP_ID.lower() in env
        or flatpak_marker in cmd
        or flatpak_marker in env
    ):
        return "flatpak"
    if is_snap_steam or "snap/steam" in cmd or "snap/steam" in env:
        return "snap"
    return "native"


def iter_running_steam_root_candidates() -> Iterable[tuple[str, Path]]:
    proc = Path("/proc")
    if not proc.is_dir():
        return

    seen: set[Path] = set()
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue

        comm = _read_proc_comm(pid_dir)
        cmdline = _read_proc_cmdline(pid_dir)
        environ = _read_proc_environ(pid_dir)
        mode = _classify_steam_process(comm, cmdline, environ)
        if not mode:
            continue

        candidates = [
            _steam_root_from_environ(environ),
            _steam_root_from_executable(_read_proc_exe(pid_dir)),
        ]
        first_arg = cmdline.split(" ", 1)[0] if cmdline else ""
        if first_arg.startswith("/"):
            candidates.append(_steam_root_from_executable(Path(first_arg)))

        for candidate in candidates:
            if candidate is None or candidate in seen:
                continue
            seen.add(candidate)
            yield mode, candidate


def detect_running_steam_mode() -> Optional[str]:
    """Detect the Steam mode from the process that is actually running.

    This avoids the common Linux case where native Steam and Flatpak Steam are
    both installed. Installed packages are only hints; the running process is
    the source of truth.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return None

    detected_modes: set[str] = set()

    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        comm = _read_proc_comm(pid_dir)
        cmdline = _read_proc_cmdline(pid_dir)
        environ = _read_proc_environ(pid_dir)
        mode = _classify_steam_process(comm, cmdline, environ)
        if mode:
            detected_modes.add(mode)

    # A Flatpak Steam session spawns helper processes whose names can look
    # native. If any running Steam process clearly belongs to Flatpak, that is
    # the active Steam mode.
    for preferred in ("flatpak", "snap", "native"):
        if preferred in detected_modes:
            return preferred
    return None


def detect_linux_steam_mode() -> str:
    running_mode = detect_running_steam_mode()
    if running_mode:
        return running_mode

    roots = _candidate_roots_by_mode()
    native_roots_exist = any(_is_steam_root(path) for path in roots["native"])
    flatpak_roots_exist = any(_is_steam_root(path) for path in roots["flatpak"])
    snap_roots_exist = any(_is_steam_root(path) for path in roots["snap"])

    if native_roots_exist:
        return "native"

    if flatpak_roots_exist:
        return "flatpak"
    if any(marker.exists() for marker in _flatpak_markers()) and not native_roots_exist:
        return "flatpak"
    if shutil.which("flatpak") and _can_run(["flatpak", "info", FLATPAK_APP_ID]):
        return "flatpak"

    if snap_roots_exist:
        return "snap"
    if any(marker.exists() for marker in _snap_markers()) and not native_roots_exist:
        return "snap"
    if shutil.which("snap") and _can_run(["snap", "list", "steam"]):
        return "snap"
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
    running_candidates = list(iter_running_steam_root_candidates())
    if preferred_mode in ordered_modes:
        running_candidates.sort(key=lambda item: item[0] != preferred_mode)

    for mode, candidate in running_candidates:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield mode, resolved

    current_environ = "\n".join(
        f"{key}={value}" for key, value in os.environ.items()
    )
    environment_root = _steam_root_from_environ(current_environ)
    if environment_root is not None and environment_root not in seen:
        seen.add(environment_root)
        mode = preferred_mode if preferred_mode in ordered_modes else "native"
        yield mode, environment_root

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


def get_plain_steam_launch_command(mode: Optional[str] = None) -> Optional[list[str]]:
    """Return a Steam command that bypasses persistent SLSsteam injection."""
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        if shutil.which("flatpak"):
            return [
                "flatpak",
                "run",
                "--unset-env=LD_AUDIT",
                "--unset-env=LD_PRELOAD",
                "--unset-env=SHARED_LIBRARY_GUARD",
                FLATPAK_APP_ID,
            ]
        return None

    if steam_mode == "snap":
        if shutil.which("snap"):
            return ["snap", "run", "steam"]
        return None

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


def snap_slssteam_dir() -> Path:
    return _home() / "snap" / "steam" / "common" / ".local" / "share" / "SLSsteam"


def is_slssteam_supported(mode: Optional[str] = None) -> bool:
    steam_mode = mode or detect_linux_steam_mode()
    return steam_mode in {"native", "flatpak"}


def get_slssteam_install_dir(mode: Optional[str] = None) -> Path:
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        return flatpak_slssteam_dir()
    if steam_mode == "snap":
        return snap_slssteam_dir()
    return native_slssteam_dir()


def get_slssteam_setup_command(mode: Optional[str] = None) -> str:
    steam_mode = mode or detect_linux_steam_mode()
    if steam_mode == "flatpak":
        return "flatpak-install"
    if steam_mode == "snap":
        raise RuntimeError(
            "O instalador oficial do SLSsteam não oferece suporte ao Steam Snap."
        )
    return "install"


def find_slssteam_paths(
    mode: Optional[str] = None,
    expected_elf_class: Optional[int] = None,
) -> tuple[Optional[str], Optional[str]]:
    steam_mode = mode or detect_linux_steam_mode()
    dirs: list[Path] = []

    if steam_mode == "flatpak":
        base_dirs = [
            flatpak_slssteam_dir(),
            _home() / ".var" / "app" / FLATPAK_APP_ID / "data" / "SLSsteam",
            native_slssteam_dir(),
        ]
    elif steam_mode == "snap":
        base_dirs = [snap_slssteam_dir()]
    else:
        base_dirs = [native_slssteam_dir(), flatpak_slssteam_dir()]

    arch_subdirs = {
        64: ["linux-x64", "linux-amd64", "x86_64", "amd64", "lib64"],
        32: ["linux-x86", "linux-i386", "i386", "i686", "lib32"],
    }

    for base_dir in base_dirs:
        for subdir in arch_subdirs.get(expected_elf_class, []):
            dirs.append(base_dir / subdir)
        dirs.append(base_dir)

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
        for p in ["/usr/lib32/libSLSsteam.so", "/usr/lib/slssteam/SLSsteam.so", "/usr/local/lib/slssteam/SLSsteam.so"]:
            path = Path(p)
            if path.exists():
                slssteam_path = str(path)
                break

    if library_inject_path is None:
        for p in ["/usr/lib32/libSLS-library-inject.so", "/usr/lib/slssteam/library-inject.so", "/usr/local/lib/slssteam/library-inject.so"]:
            path = Path(p)
            if path.exists():
                library_inject_path = str(path)
                break

    return slssteam_path, library_inject_path
