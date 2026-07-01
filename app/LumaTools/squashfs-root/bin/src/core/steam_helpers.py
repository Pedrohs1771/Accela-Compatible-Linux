import logging
import os
import sys
import psutil
import shutil
import subprocess
import re
import time
from pathlib import Path

from core.linux_paths import (
    detect_linux_steam_mode,
    find_primary_steam_root,
    find_slssteam_paths,
    get_plain_steam_launch_command,
    get_steam_launch_command,
    is_slssteam_supported,
    FLATPAK_APP_ID,
)
from core.platform import get_platform_backend
from core.platform.common import (
    parse_libraryfolders_vdf,
    resolve_steam_library_path as _resolve_steam_library_path,
)

logger = logging.getLogger(__name__)

_slssteam_so_path_cache = None
_library_inject_so_path_cache = None


def _elf_class(path: str | None) -> int | None:
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as handle:
            header = handle.read(5)
    except OSError:
        return None
    if len(header) < 5 or header[:4] != b"\x7fELF":
        return None
    if header[4] == 1:
        return 32
    if header[4] == 2:
        return 64
    return None


def _steam_audit_target_path(steam_mode: str | None = None) -> str | None:
    if sys.platform != "linux":
        return None

    mode = steam_mode or detect_linux_steam_mode()
    root = find_primary_steam_root(preferred_mode=mode if mode != "missing" else None)
    if root is not None:
        for candidate in (
            root / "ubuntu12_32" / "steam",
            root / "steam.sh",
        ):
            if candidate.exists():
                return str(candidate)

    launch_command = get_steam_launch_command(mode)
    if launch_command and os.path.isabs(launch_command[0]) and os.path.exists(launch_command[0]):
        return launch_command[0]
    return None


def _steam_audit_target_class(steam_mode: str | None = None) -> int | None:
    target_path = _steam_audit_target_path(steam_mode)
    target_class = _elf_class(target_path)
    if target_class:
        return target_class
    if sys.platform == "linux":
        # Native Steam's bootstrap executable is commonly 32-bit even on x86_64 systems.
        return 32
    return None


def _valid_ld_audit_pair(
    slssteam_path: str | None,
    library_inject_path: str | None,
    expected_class: int | None = None,
) -> bool:
    sls_class = _elf_class(slssteam_path)
    inject_class = _elf_class(library_inject_path)
    if expected_class is None:
        expected_class = _steam_audit_target_class()

    if (
        expected_class in (32, 64)
        and sls_class == expected_class
        and inject_class == expected_class
    ):
        return True

    logger.warning(
        "SLSsteam LD_AUDIT ignorado: bibliotecas incompatíveis "
        "(esperado=%s-bit, SLSsteam.so=%s-bit, library-inject.so=%s-bit).",
        expected_class or "desconhecido",
        sls_class or "desconhecido",
        inject_class or "desconhecido",
    )
    return False


def _prepare_slssteam_config_for_launch() -> None:
    """Run cheap config repairs before SLSsteam parses config.yaml."""
    if sys.platform != "linux":
        return

    try:
        from utils.yaml_config_manager import (
            ensure_slssteam_api_enabled,
            ensure_slssteam_config,
            fix_slssteam_config_indentation,
            get_user_config_path,
        )
    except Exception:
        logger.debug("SLSsteam config helpers unavailable", exc_info=True)
        return

    try:
        config_path = get_user_config_path()
        ensure_slssteam_config(config_path)
        fix_slssteam_config_indentation(config_path)
        ensure_slssteam_api_enabled(config_path)
    except Exception:
        logger.warning("Failed to prepare SLSsteam config before launch", exc_info=True)


def _unblock_native_steam_updates(steam_mode: str | None = None) -> None:
    """Move steam.cfg out of the way when it prevents Steam bootstrap updates."""
    if sys.platform != "linux" or steam_mode == "flatpak":
        return

    root = find_primary_steam_root(preferred_mode="native")
    if root is None:
        return

    config_path = root / "steam.cfg"
    try:
        content = config_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return

    blocked_flags = (
        "BootStrapperInhibitAll=enable",
        "BootStrapperForceSelfUpdate=disable",
    )
    if not any(flag in content for flag in blocked_flags):
        return

    backup_path = config_path.with_name(
        f"steam.cfg.lumatools-backup-{time.strftime('%Y%m%d_%H%M%S')}"
    )
    try:
        config_path.replace(backup_path)
        logger.info("Moved Steam update inhibitor to %s", backup_path)
    except OSError:
        logger.warning("Failed to move Steam update inhibitor %s", config_path, exc_info=True)


def _command_exists(command: list[str]) -> bool:
    if not command:
        return False
    executable = command[0]
    if os.path.isabs(executable) or os.sep in executable:
        return os.path.exists(executable) and os.access(executable, os.X_OK)
    return shutil.which(executable) is not None


def _is_slssteam_wrapper_command(command: list[str]) -> bool:
    if not command:
        return False
    normalized = command[0].replace("\\", "/")
    return "/SLSsteam/path/" in normalized


def _slssteam_launch_command(launch_command: list[str] | None = None) -> list[str]:
    candidates: list[list[str]] = []

    system_steam = Path("/usr/bin/steam")
    if system_steam.exists() and os.access(system_steam, os.X_OK):
        candidates.append([str(system_steam)])

    if launch_command:
        candidates.append(launch_command)

    plain_command = get_plain_steam_launch_command("native")
    if plain_command:
        candidates.append(plain_command)

    detected_command = get_steam_launch_command("native")
    if detected_command:
        candidates.append(detected_command)

    candidates.append(["steam"])

    seen: set[tuple[str, ...]] = set()
    for command in candidates:
        key = tuple(command)
        if key in seen:
            continue
        seen.add(key)
        if _is_slssteam_wrapper_command(command):
            continue
        if _command_exists(command):
            return command

    return ["steam"]


def _flatpak_slssteam_override_ready(
    slssteam_path: str | None = None,
    library_inject_path: str | None = None,
) -> bool:
    """Return True when the official SLSsteam Flatpak override is installed.

    SLSsteam's Flatpak installer intentionally uses Flatpak's
    libshared-library-guard in front of the 32-bit SLSsteam libraries. Starting
    Flatpak with our own --env=LD_AUDIT=... bypasses that guard and makes 64-bit
    helper processes fail with ELFCLASS32. For Flatpak, the override is the
    source of truth; Luma must not replace it at launch time.
    """
    if shutil.which("flatpak") is None:
        return False
    try:
        result = subprocess.run(
            ["flatpak", "override", "--user", "--show", FLATPAK_APP_ID],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    output = result.stdout or ""
    if "SHARED_LIBRARY_GUARD=0" not in output:
        return False
    if "LD_AUDIT=" not in output or "libshared-library-guard.so" not in output:
        return False
    if "SLSsteam.so" not in output or "library-inject.so" not in output:
        return False
    if slssteam_path and str(slssteam_path) not in output:
        logger.debug("Flatpak SLSsteam override points to a different SLSsteam.so")
    if library_inject_path and str(library_inject_path) not in output:
        logger.debug("Flatpak SLSsteam override points to a different library-inject.so")
    return True


def _is_linux_steam_process(name: str, cmdline: str, exe: str) -> bool:
    lowered_name = (name or "").lower()
    lowered_cmdline = (cmdline or "").lower()
    lowered_exe = (exe or "").lower()

    if lowered_name in {"steam", "steamwebhelper", "steam-runtime-launcher-service"}:
        return True

    runtime_names = {"bash", "srt-logger", "srt-bwrap", "pv-adverb"}
    steam_markers = (
        "/steam/steam.sh",
        "/steam/ubuntu12_32/",
        "/steam/ubuntu12_64/",
        "/steam/steamrt",
        "steamwebhelper",
        "steam-runtime-launcher-service",
    )
    return lowered_name in runtime_names and any(
        marker in lowered_cmdline or marker in lowered_exe for marker in steam_markers
    )


def _iter_linux_steam_processes():
    if sys.platform != "linux":
        return
    try:
        processes = psutil.process_iter(["pid", "name", "cmdline", "exe"])
    except (AttributeError, psutil.Error):
        return

    for proc in processes:
        try:
            name = proc.info.get("name") or ""
            cmdline = " ".join(proc.info.get("cmdline") or [])
            exe = proc.info.get("exe") or ""
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if _is_linux_steam_process(name, cmdline, exe):
            yield proc


def _steam_processes_running() -> bool:
    return any(True for _proc in _iter_linux_steam_processes())


def _steam_processes_have_slssteam(
    slssteam_path: str | None,
    library_inject_path: str | None,
) -> bool:
    sls_needles = {
        "SLSsteam.so",
        "libSLSsteam.so",
    }
    inject_needles = {
        "library-inject.so",
        "libSLS-library-inject.so",
    }
    if slssteam_path:
        sls_needles.add(str(Path(slssteam_path).resolve()))
    if library_inject_path:
        inject_needles.add(str(Path(library_inject_path).resolve()))

    for proc in _iter_linux_steam_processes():
        maps_file = Path("/proc") / str(proc.pid) / "maps"
        try:
            content = maps_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(needle in content for needle in sls_needles) and any(
            needle in content for needle in inject_needles
        ):
            return True
    return False


def _wait_for_slssteam_launch(
    slssteam_path: str | None,
    library_inject_path: str | None,
    process: subprocess.Popen | None,
    timeout_seconds: float = 10.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    saw_steam_process = False

    while time.monotonic() < deadline:
        if _steam_processes_have_slssteam(slssteam_path, library_inject_path):
            return "SUCCESS"
        if _steam_processes_running():
            saw_steam_process = True
        if process is not None and process.poll() is not None and not saw_steam_process:
            # The launcher may exit before Steam hands off to its real process.
            # Keep polling briefly so a slow runtime bootstrap still has a chance.
            pass
        time.sleep(0.5)

    if saw_steam_process:
        return "SLSSTEAM_NOT_LOADED"
    return "SLSSTEAM_CRASHED"


def find_steam_install():
    backend = get_platform_backend(sys.platform)
    steam_path = backend.find_steam_install()
    if steam_path:
        logger.info("Found Steam installation at: %s", steam_path)
        return steam_path

    logger.warning(
        "Automatic Steam path detection is not supported or failed on this OS: %s.",
        sys.platform,
    )
    return None


def _find_steam_windows():
    backend = get_platform_backend("win32")
    return backend.find_steam_install()


def _find_steam_linux():
    backend = get_platform_backend("linux")
    root = backend.find_steam_install()
    if root is not None:
        logger.info("Found Steam installation at: %s", root)
        return str(root)

    logger.error("Could not find Steam installation in common Linux directories.")
    return None


def parse_library_folders(vdf_path):
    return parse_libraryfolders_vdf(vdf_path)


def get_steam_libraries():
    backend = get_platform_backend(sys.platform)
    return backend.get_steam_libraries()


def get_preferred_steam_library():
    """Return the most sensible default Steam library for installations.

    Preference order:
    1. If exactly one library is detected, use it directly.
    2. Otherwise use the main Steam install path when valid.
    3. Fall back to the first detected library if any exist.
    """
    backend = get_platform_backend(sys.platform)
    return backend.get_preferred_steam_library()


def resolve_steam_library_path(path, library_paths=None):
    """Normalize a selected Steam path to its library root."""
    return _resolve_steam_library_path(path, tuple(library_paths or ()))


def kill_steam_process():
    global _slssteam_so_path_cache, _library_inject_so_path_cache
    _slssteam_so_path_cache = None
    _library_inject_so_path_cache = None

    if sys.platform == "linux":
        launch_command = get_steam_launch_command(detect_linux_steam_mode()) or ["steam"]
        try:
            subprocess.run(
                [*launch_command, "-shutdown"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=8,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            logger.debug("Steam graceful shutdown command failed", exc_info=True)

    target_name = "steam.exe" if sys.platform == "win32" else "steam"
    steam_processes = []

    def is_steam_process(proc) -> bool:
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            exe = (proc.info.get("exe") or "").lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

        if sys.platform == "win32":
            return name == target_name

        if name in {"steam", "steamwebhelper", "steam-runtime-launcher-service"}:
            return True

        runtime_names = {"bash", "srt-logger", "srt-bwrap", "pv-adverb"}
        steam_markers = (
            "/steam/steam.sh",
            "/steam/ubuntu12_32/",
            "/steam/ubuntu12_64/",
            "/steam/steamrt",
            "steamwebhelper",
            "steam-runtime-launcher-service",
        )
        return name in runtime_names and any(
            marker in cmdline or marker in exe for marker in steam_markers
        )

    for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
        if is_steam_process(proc):
            steam_processes.append(proc)

    if not steam_processes:
        logger.warning("%s process not found.", target_name)
        return False

    if sys.platform == "linux":
        for proc in steam_processes:
            maps_file = f"/proc/{proc.pid}/maps"
            try:
                with open(maps_file, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "SLSsteam.so" in line:
                            parts = line.split()
                            if len(parts) > 5 and os.path.exists(parts[-1]):
                                _slssteam_so_path_cache = parts[-1]
                                logger.info("Found and cached SLSsteam.so path: %s", _slssteam_so_path_cache)
                        elif "library-inject.so" in line or "libSLS-library-inject.so" in line:
                            parts = line.split()
                            if len(parts) > 5 and os.path.exists(parts[-1]):
                                _library_inject_so_path_cache = parts[-1]
                                logger.info("Found and cached library-inject.so path: %s", _library_inject_so_path_cache)
            except OSError:
                continue

    for proc in steam_processes:
        try:
            proc.terminate()
        except psutil.Error:
            continue

    gone, alive = psutil.wait_procs(steam_processes, timeout=5)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            continue
    if alive:
        psutil.wait_procs(alive, timeout=3)

    logger.info(
        "Terminated Steam process tree: %s graceful, %s forced.",
        len(gone),
        len(alive),
    )
    return True


def start_steam():
    """Start Steam on Windows, or attempt to start Steam with SLSsteam integration on Linux
    Returns: "SUCCESS", "FAILED", or "NEEDS_USER_PATH"
    """
    global _slssteam_so_path_cache, _library_inject_so_path_cache
    logger.info("Attempting to start Steam...")

    try:
        if sys.platform == "win32":
            fix_greenluma_offline_mode()
            steam_path = find_steam_install()
            if not steam_path:
                return "FAILED"
            launch_command = get_platform_backend("win32").get_steam_launch_command()
            if not launch_command:
                return "FAILED"
            subprocess.Popen(launch_command)
            return "SUCCESS"

        elif sys.platform == "linux":
            steam_mode = detect_linux_steam_mode()
            launch_command = get_steam_launch_command(steam_mode)
            target_class = _steam_audit_target_class(steam_mode)
            if not launch_command:
                logger.warning("Could not determine how to launch Steam on Linux.")
                return "FAILED"

            if not is_slssteam_supported(steam_mode):
                logger.warning(
                    "SLSsteam não é suportado pelo modo Steam %s.",
                    steam_mode,
                )
                return "SLSSTEAM_UNSUPPORTED"

            _unblock_native_steam_updates(steam_mode)
            _prepare_slssteam_config_for_launch()

            if steam_mode == "flatpak":
                slssteam_path = _slssteam_so_path_cache
                library_inject_path = _library_inject_so_path_cache

                if not slssteam_path or not library_inject_path:
                    detected_slssteam_path, detected_library_inject_path = find_slssteam_paths(
                        steam_mode,
                    )
                    slssteam_path = slssteam_path or detected_slssteam_path
                    library_inject_path = library_inject_path or detected_library_inject_path

                if (
                    slssteam_path
                    and library_inject_path
                    and _flatpak_slssteam_override_ready(slssteam_path, library_inject_path)
                ):
                    logger.info(
                        "Launching Steam Flatpak with official SLSsteam Flatpak override"
                    )
                    subprocess.Popen(
                        launch_command,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return "SUCCESS"
                
                logger.warning("SLSsteam Flatpak override missing or incomplete")
                return "MISSING_SLSSTEAM"

            slssteam_path = _slssteam_so_path_cache
            library_inject_path = _library_inject_so_path_cache

            if not slssteam_path or not library_inject_path:
                detected_slssteam_path, detected_library_inject_path = (
                    find_slssteam_paths(steam_mode, expected_elf_class=target_class)
                )
                slssteam_path = slssteam_path or detected_slssteam_path
                library_inject_path = (
                    library_inject_path or detected_library_inject_path
                )

            # If we have both libraries, start with them
            if slssteam_path and library_inject_path:
                if (
                    os.path.exists(slssteam_path)
                    and os.path.exists(library_inject_path)
                    and _valid_ld_audit_pair(
                        slssteam_path,
                        library_inject_path,
                        expected_class=target_class,
                    )
                ):
                    # Start Steam with both libraries
                    success = start_steam_with_slssteam(
                        slssteam_path,
                        library_inject_path,
                        launch_command=launch_command,
                        expected_class=target_class,
                    )
                    # Only clear caches if successful
                    if success == "SUCCESS":
                        _slssteam_so_path_cache = None
                        _library_inject_so_path_cache = None
                    return success
                logger.warning("SLSsteam libraries missing or incompatible")
                return "SLSSTEAM_INCOMPATIBLE"
            else:
                # Missing one or both libraries
                missing = []
                if not slssteam_path:
                    missing.append("SLSsteam.so")
                if not library_inject_path:
                    missing.append("library-inject.so")
                logger.warning(f"Missing libraries: {', '.join(missing)}")
                return "MISSING_SLSSTEAM"
        else:
            return "FAILED"
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(f"Failed to execute Steam: {e}", exc_info=True)
        return "FAILED"


def start_steam_plain():
    """Start Steam without LD_AUDIT injection."""
    if sys.platform == "win32":
        launch_command = get_platform_backend("win32").get_steam_launch_command()
    elif sys.platform == "linux":
        launch_command = get_plain_steam_launch_command(detect_linux_steam_mode())
    else:
        launch_command = None

    if not launch_command:
        return "FAILED"

    try:
        logger.info("Starting Steam without SLSsteam injection: %s", " ".join(launch_command))
        clean_env = os.environ.copy()
        for variable in ("LD_AUDIT", "LD_PRELOAD", "SHARED_LIBRARY_GUARD"):
            clean_env.pop(variable, None)
        subprocess.Popen(launch_command, env=clean_env)
        return "SUCCESS"
    except (OSError, subprocess.SubprocessError) as e:
        logger.error("Failed to start Steam without SLSsteam injection: %s", e, exc_info=True)
        return "FAILED"


def start_steam_with_slssteam(
    slssteam_path=None,
    library_inject_path=None,
    launch_command=None,
    expected_class=None,
):
    """Start Steam on Linux with SLSsteam.so AND library-inject.so via LD_AUDIT.

    Returns: "SUCCESS", "FAILED", "NEEDS_USER_PATH", "SLSSTEAM_CRASHED", or
    "SLSSTEAM_NOT_LOADED".
    """

    if sys.platform != "linux":
        logger.error("start_steam_with_slssteam is only supported on Linux")
        return "FAILED"

    # Validate paths
    if not slssteam_path or not os.path.exists(slssteam_path):
        logger.error(f"SLSsteam.so path is invalid or does not exist: {slssteam_path}")
        return "NEEDS_USER_PATH"

    if not library_inject_path or not os.path.exists(library_inject_path):
        logger.error(
            f"library-inject.so path is invalid or does not exist: {library_inject_path}"
        )
        return "NEEDS_USER_PATH"

    expected_class = expected_class or _steam_audit_target_class()
    if not _valid_ld_audit_pair(
        slssteam_path,
        library_inject_path,
        expected_class=expected_class,
    ):
        return "MISSING_SLSSTEAM"

    try:
        logger.info(
            f"Executing Steam with LD_AUDIT: {library_inject_path}:{slssteam_path}"
        )
        env = os.environ.copy()
        env["LD_AUDIT"] = f"{library_inject_path}:{slssteam_path}"
        command = _slssteam_launch_command(launch_command)
        logger.info("Starting Steam command: %s", " ".join(command))
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        result = _wait_for_slssteam_launch(
            slssteam_path,
            library_inject_path,
            process,
            timeout_seconds=15.0,
        )
        if result != "SUCCESS":
            logger.error("Steam started but SLSsteam did not load correctly: %s", result)
        return result
    except (OSError, subprocess.SubprocessError) as e:
        logger.error(
            f"Failed to execute steam with provided libraries: {e}", exc_info=True
        )
        return "FAILED"


def get_library_index(library_path: str, steam_path: str | None = None) -> int:
    """Get the library index from libraryfolders.vdf for a given library path.

    If `steam_path` is provided, it will be used instead of calling
    `find_steam_install()` (useful to avoid repeated lookups).
    """
    if not steam_path:
        steam_path = find_steam_install()
    if not steam_path:
        return 0

    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.exists(vdf_path):
        return 0

    try:
        with open(vdf_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse each library entry - format is like:
        # "1"
        # {
        #     "path"  "path/to/library"
        #     ...
        # }
        lines = content.split("\n")
        current_index = None

        for line in lines:
            # Match numeric indices like "0", "1", "2"
            index_match = re.match(r'^\s*"(\d+)"\s*$', line)
            if index_match:
                current_index = int(index_match.group(1))
                continue

            # Match path line
            path_match = re.match(r'^\s*"path"\s*"([^"]+)"', line)
            if path_match and current_index is not None:
                path = path_match.group(1).replace("\\\\", "\\")
                if os.path.realpath(path) == os.path.realpath(library_path):
                    return current_index

        # Default to 0 if not found (main library)
        return 0
    except (OSError, ValueError) as e:
        logger.error(f"Failed to get library index: {e}")
        return 0


def slssteam_api_send(command: str) -> bool:
    """Send a command to SLSsteam API via named pipe."""
    if sys.platform != "linux":
        return False

    pipe_path = "/tmp/SLSsteam.API"

    try:
        with open(pipe_path, "w") as f:
            f.write(command)
            f.flush()
        logger.info(f"SLSsteam API command sent: {command}")
        return True
    except OSError:
        # Silently fail - API may not be available
        return False


def fix_greenluma_offline_mode():
    """Fix Windows autologin accounts stuck with WantsOfflineMode=1.

    The Windows build should restart Steam back into the normal online flow when a
    remembered account is available. If Steam stores WantsOfflineMode=1 in
    ``loginusers.vdf``, later restarts can reopen straight into offline mode.
    """
    if sys.platform != "win32":
        return

    try:
        from utils.settings import get_settings
    except ImportError:
        return

    settings = get_settings()
    if not settings.value("sls_config_management", True, type=bool):
        return

    steam_path = find_steam_install()
    if not steam_path:
        return

    login_file = os.path.join(steam_path, "config", "loginusers.vdf")
    if not os.path.exists(login_file):
        return

    try:
        import vdf

        with open(login_file, "r", encoding="utf-8", errors="ignore") as f:
            data = vdf.load(f)

        fixed = False
        for user in data.get("users", {}).values():
            wants_offline = user.get("WantsOfflineMode") == "1"
            can_autologin = (
                user.get("RememberPassword") == "1"
                or user.get("AllowAutoLogin") == "1"
            )
            if wants_offline and can_autologin:
                user["WantsOfflineMode"] = "0"
                fixed = True

        if fixed:
            with open(login_file, "w", encoding="utf-8") as f:
                vdf.dump(data, f)
            logger.info(
                "Fixed WantsOfflineMode in loginusers.vdf for Windows Steam autologin"
            )
    except ImportError:
        logger.warning("vdf library not installed, cannot fix offline mode")
    except OSError as e:
        logger.error(f"Failed to fix offline mode: {e}")


def find_next_applist_number(app_list_dir):
    """Find the next available AppList number"""
    if not os.path.exists(app_list_dir):
        os.makedirs(app_list_dir)
        return 1

    max_num = 0
    try:
        for filename in os.listdir(app_list_dir):
            match = re.match(r"^(\d+)\.txt$", filename)
            if match:
                num = int(match.group(1))
                if num > max_num:
                    max_num = num
    except OSError as e:
        logger.error(f"Error scanning AppList directory: {e}")

    return max_num + 1


def app_id_exists_in_applist(app_list_dir, app_id_to_check):
    """Check if AppID already exists in AppList"""
    if not os.path.exists(app_list_dir):
        return False

    try:
        for filename in os.listdir(app_list_dir):
            if filename.lower().endswith(".txt"):
                filepath = os.path.join(app_list_dir, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content == app_id_to_check:
                            return True
                except (OSError, UnicodeDecodeError):
                    continue
    except OSError:
        pass

    return False
