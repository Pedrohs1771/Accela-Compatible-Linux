import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


_EMPTY_PLATFORM_CONFIG = '\t"UserConfig"\n\t{\n\t}\n\t"MountedConfig"\n\t{\n\t}'


def sanitize_game_name(game_name: str) -> str:
    return re.sub(r"[^\w\s-]", "", game_name or "").strip().replace(" ", "_")


def get_install_folder_name(game_data: Dict[str, Any]) -> str:
    safe_game_name = sanitize_game_name(game_data.get("game_name", ""))
    install_folder_name = game_data.get("installdir") or safe_game_name
    if not install_folder_name:
        install_folder_name = f"App_{game_data.get('appid')}"
    return install_folder_name


def get_game_directory(dest_path: str, game_data: Dict[str, Any]) -> str:
    return os.path.join(
        dest_path, "steamapps", "common", get_install_folder_name(game_data)
    )


def get_active_steam_owner(steam_root: str | os.PathLike[str] | None) -> str:
    if not steam_root:
        return "0"
    loginusers_path = Path(steam_root) / "config" / "loginusers.vdf"
    if not loginusers_path.exists():
        return "0"

    try:
        content = loginusers_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "0"

    users: list[tuple[str, str]] = []
    for match in re.finditer(r'"(?P<steamid>7656\d+)"\s*\{(?P<body>.*?)\n\s*\}', content, re.DOTALL):
        steamid = match.group("steamid")
        body = match.group("body")
        if re.search(r'"MostRecent"\s*"1"', body):
            return steamid
        rank = "1" if re.search(r'"AllowAutoLogin"\s*"1"', body) else "2"
        users.append((rank, steamid))

    if users:
        return sorted(users)[0][1]
    return "0"


def _get_depot_platform(depot_info: Dict[str, Any]) -> str:
    try:
        platform = (depot_info.get("oslist") or "").lower()
    except AttributeError:
        return "unknown"
    return platform or "unknown"


def _build_platform_config(
    selected_depots: Iterable[Any],
    all_depots: Dict[str, Any],
    log_proton: bool,
    logger,
) -> str:
    if sys.platform != "linux":
        return _EMPTY_PLATFORM_CONFIG

    downloading_windows_depots = False
    downloading_linux_depots = False

    for depot_id in selected_depots:
        depot_id_str = str(depot_id)
        depot_info = all_depots.get(depot_id_str, {})
        platform = _get_depot_platform(depot_info)

        if platform == "windows":
            downloading_windows_depots = True
        elif platform == "linux":
            downloading_linux_depots = True

    if downloading_windows_depots:
        if log_proton and logger:
            logger.info("Windows depots on Linux - adding Proton configuration")
        return (
            '\t"UserConfig"\n'
            "\t{\n"
            '\t\t"platform_override_dest"\t\t"linux"\n'
            '\t\t"platform_override_source"\t\t"windows"\n'
            "\t}\n"
            '\t"MountedConfig"\n'
            "\t{\n"
            '\t\t"platform_override_dest"\t\t"linux"\n'
            '\t\t"platform_override_source"\t\t"windows"\n'
            "\t}"
        )

    if downloading_linux_depots:
        return _EMPTY_PLATFORM_CONFIG

    return _EMPTY_PLATFORM_CONFIG


def _build_depots_content(
    selected_depots: Iterable[Any],
    all_manifests: Dict[str, Any],
    all_depots: Dict[str, Any],
) -> str:
    depots_content = ""
    for depot_id in selected_depots:
        depot_id_str = str(depot_id)
        manifest_gid = all_manifests.get(depot_id_str)
        depot_info = all_depots.get(depot_id_str, {})
        depot_size = depot_info.get("size", "0")

        if manifest_gid:
            depots_content += (
                f'\t\t"{depot_id_str}"\n'
                f"\t\t{{\n"
                f'\t\t\t"manifest"\t\t"{manifest_gid}"\n'
                f'\t\t\t"size"\t\t"{depot_size}"\n'
                f"\t\t}}\n"
            )
    return depots_content


def _filter_depots_for_linux_platform(
    selected_depots: Iterable[Any],
    all_depots: Dict[str, Any],
    logger=None,
) -> list[Any]:
    """Keep appmanifest depots aligned with the platform Steam will mount."""
    selected = list(selected_depots)
    if sys.platform != "linux":
        return selected

    platforms = {
        str(depot_id): _get_depot_platform(all_depots.get(str(depot_id), {}))
        for depot_id in selected
    }
    has_windows = any(platform == "windows" for platform in platforms.values())
    has_linux = any(platform == "linux" for platform in platforms.values())

    if has_windows:
        allowed = {"windows", "unknown"}
    elif has_linux:
        allowed = {"linux", "unknown"}
    else:
        return selected

    filtered = [
        depot_id
        for depot_id in selected
        if platforms.get(str(depot_id), "unknown") in allowed
    ]
    if filtered != selected and logger:
        logger.info(
            "Filtered appmanifest depots for Linux platform: kept %s, skipped %s",
            [str(item) for item in filtered],
            [str(item) for item in selected if item not in filtered],
        )
    return filtered


def build_acf_content(
    game_data: Dict[str, Any],
    size_on_disk: int,
    install_folder_name: str,
    include_depots: bool,
    log_proton: bool = False,
    logger=None,
) -> str:
    buildid = game_data.get("buildid", "0")
    selected_depots = game_data.get("selected_depots_list", [])
    all_manifests = game_data.get("manifests", {})
    all_depots = game_data.get("depots", {})
    last_owner = str(game_data.get("lastowner") or game_data.get("LastOwner") or "0")
    acf_depots = _filter_depots_for_linux_platform(
        selected_depots, all_depots, logger
    )

    platform_config = _build_platform_config(
        acf_depots, all_depots, log_proton, logger
    )
    depots_content = _build_depots_content(acf_depots, all_manifests, all_depots)

    installed_depots_str = (
        f'\t"InstalledDepots"\n\t{{\n{depots_content}\t}}'
        if include_depots and depots_content
        else '\t"InstalledDepots"\n\t{\n\t}'
    )

    acf_content = (
        f'"AppState"\n'
        f"{{\n"
        f'\t"appid"\t\t"{game_data["appid"]}"\n'
        f'\t"Universe"\t\t"1"\n'
        f'\t"name"\t\t"{game_data["game_name"]}"\n'
        f'\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{install_folder_name}"\n'
        f'\t"LastUpdated"\t\t"{int(time.time())}"\n'
        f'\t"LastOwner"\t\t"{last_owner}"\n'
        f'\t"SizeOnDisk"\t\t"{size_on_disk}"\n'
        f'\t"StagingSize"\t\t"0"\n'
        f'\t"buildid"\t\t"{buildid}"\n'
        f'\t"LastPlayed"\t\t"0"\n'
        f'\t"UpdateResult"\t\t"0"\n'
        f'\t"BytesToDownload"\t\t"0"\n'
        f'\t"BytesDownloaded"\t\t"0"\n'
        f'\t"BytesToStage"\t\t"0"\n'
        f'\t"BytesStaged"\t\t"0"\n'
        f'\t"TargetBuildID"\t\t"0"\n'
        f'\t"AutoUpdateBehavior"\t\t"1"\n'
        f'\t"AllowOtherDownloadsWhileRunning"\t\t"0"\n'
        f'\t"ScheduledAutoUpdate"\t\t"0"\n'
        f"{installed_depots_str}"
    )

    if platform_config:
        acf_content += f"\n{platform_config}"

    acf_content += "\n}"
    return acf_content


def write_acf_file(
    dest_path: str,
    game_data: Dict[str, Any],
    size_on_disk: int,
    include_depots: bool,
    log_proton: bool = False,
    logger=None,
) -> Optional[str]:
    if not dest_path or not game_data:
        return None

    install_folder_name = get_install_folder_name(game_data)
    game_data = dict(game_data)
    if not game_data.get("lastowner"):
        game_data["lastowner"] = get_active_steam_owner(dest_path)
    acf_path = os.path.join(
        dest_path, "steamapps", f"appmanifest_{game_data['appid']}.acf"
    )
    os.makedirs(os.path.dirname(acf_path), exist_ok=True)

    acf_content = build_acf_content(
        game_data,
        size_on_disk,
        install_folder_name,
        include_depots=include_depots,
        log_proton=log_proton,
        logger=logger,
    )

    with open(acf_path, "w", encoding="utf-8") as f:
        f.write(acf_content)

    return acf_path


def repair_installed_app_state(dest_path: str, appid: str, logger=None) -> bool:
    if not dest_path or not appid:
        return False

    steamapps_dir = os.path.join(dest_path, "steamapps")
    acf_path = os.path.join(steamapps_dir, f"appmanifest_{appid}.acf")
    if not os.path.exists(acf_path):
        return False

    try:
        with open(acf_path, "r", encoding="utf-8", errors="ignore") as handle:
            content = handle.read()

        installdir = _parse_acf_value(content, "installdir")
        size_on_disk = _parse_acf_value(content, "SizeOnDisk")
        if installdir:
            game_dir = Path(dest_path) / "steamapps" / "common" / installdir
            computed_size = _compute_directory_size(game_dir)
            if computed_size > 0 and (not size_on_disk.isdigit() or int(size_on_disk) <= 0):
                size_on_disk = str(computed_size)

        replacements = {
            "StateFlags": "4",
            "UpdateResult": "0",
            "BytesToDownload": "0",
            "BytesDownloaded": "0",
            "BytesToStage": "0",
            "BytesStaged": "0",
            "StagingSize": "0",
            "TargetBuildID": "0",
            "DownloadType": "0",
            "ScheduledAutoUpdate": "0",
            "AutoUpdateBehavior": "1",
            "LastUpdated": str(int(time.time())),
        }
        if size_on_disk and size_on_disk.isdigit() and int(size_on_disk) > 0:
            replacements["SizeOnDisk"] = size_on_disk
        last_owner = get_active_steam_owner(dest_path)
        if last_owner != "0":
            replacements["LastOwner"] = last_owner

        for key, value in replacements.items():
            pattern = rf'("{re.escape(key)}"\s*)"[^"]*"'
            if re.search(pattern, content):
                content = re.sub(
                    pattern,
                    lambda match: f'{match.group(1)}"{value}"',
                    content,
                    count=1,
                )
            else:
                insert_at = content.rfind("}")
                if insert_at != -1:
                    content = (
                        content[:insert_at]
                        + f'\t"{key}"\t\t"{value}"\n'
                        + content[insert_at:]
                    )

        shutil.copy2(acf_path, f"{acf_path}.lumatools-{int(time.time())}.bak")
        with open(acf_path, "w", encoding="utf-8") as handle:
            handle.write(content)

        for folder in ("downloading", "temp", "shadercache"):
            path = os.path.join(steamapps_dir, folder, str(appid))
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)

        # Steam can leave state files around after an interrupted validation.
        for state_file in (
            os.path.join(steamapps_dir, f"appmanifest_{appid}.acf.tmp"),
            os.path.join(steamapps_dir, f"appmanifest_{appid}.acf.old"),
        ):
            if os.path.exists(state_file):
                try:
                    os.remove(state_file)
                except OSError:
                    pass

        decryption_issue = detect_recent_decryption_key_issue(dest_path, appid)
        if decryption_issue and logger:
            logger.warning(
                "Steam recusou update/prefetch do AppID %s por falta de chave de depot. "
                "O Luma reparou o manifest/cache, mas a Steam pode continuar pedindo update "
                "ate a conta ter acesso ao depot. Ultimo log: %s",
                appid,
                decryption_issue,
            )

        if logger:
            logger.info("Steam appmanifest reparado para AppID %s", appid)
        return True
    except OSError as exc:
        if logger:
            logger.warning("Falha ao reparar appmanifest %s: %s", acf_path, exc)
        return False


_LUMATOOLS_MARKERS = {
    ".LumaTools",
    ".DepotDownloader",
    "LUMA_ONLINE_FIX_INFO.txt",
    "LUMA_FIX_STACK.json",
    "LUMA_RYUU_FIX_INFO.txt",
}


def _parse_acf_value(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*"([^"]*)"', content)
    return match.group(1) if match else ""


def _compute_directory_size(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            file_path = os.path.join(root, name)
            try:
                total += os.path.getsize(file_path)
            except OSError:
                continue
    return total


def detect_recent_decryption_key_issue(
    steam_root_or_library: str | os.PathLike[str] | None,
    appid: str | int,
    *,
    max_lines: int = 700,
) -> str:
    """Return the last Steam content log line showing a depot key failure.

    This is diagnostic only. A "Missing decryption key" line means Steam itself
    cannot initialize one of the app's depots, so resetting appmanifest state
    may clear stale update flags but cannot make Steam download that depot.
    """
    if not steam_root_or_library or not appid:
        return ""

    root = Path(steam_root_or_library).expanduser()
    candidates = [
        root / "logs" / "content_log.txt",
        root.parent / "logs" / "content_log.txt",
    ]
    appid_text = str(appid)
    last_match = ""

    for log_path in candidates:
        if not log_path.is_file():
            continue
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines[-max_lines:]:
            if (
                f"AppID {appid_text}" in line
                and "Missing decryption key" in line
            ):
                last_match = line.strip()

    return last_match


def _is_lumatools_managed_game(game_dir: Path) -> bool:
    if not game_dir.is_dir():
        return False
    return any((game_dir / marker).exists() for marker in _LUMATOOLS_MARKERS)


def repair_lumatools_library_manifests(
    library_paths: Iterable[str | os.PathLike[str]],
    logger=None,
) -> dict[str, Any]:
    """Repair Steam update state for all LumaTools-managed appmanifests.

    Steam can rewrite appmanifest state while it is running. This helper is
    meant to run after Steam is closed and before it is restarted, so managed
    games do not come back as "update required" after a successful install.
    """
    repaired: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    decryption_key_blocked: list[str] = []
    seen: set[str] = set()

    for library_path in library_paths or []:
        library = Path(library_path).expanduser()
        steamapps = library / "steamapps"
        common = steamapps / "common"
        if not steamapps.is_dir():
            continue

        for acf_path in sorted(steamapps.glob("appmanifest_*.acf")):
            appid = acf_path.stem.replace("appmanifest_", "", 1)
            if not appid or appid in seen:
                continue
            seen.add(appid)

            try:
                content = acf_path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                failed.append(appid)
                if logger:
                    logger.warning("Falha ao ler %s: %s", acf_path, exc)
                continue

            installdir = _parse_acf_value(content, "installdir")
            if not installdir:
                skipped.append(appid)
                continue

            game_dir = common / installdir
            if not _is_lumatools_managed_game(game_dir):
                skipped.append(appid)
                continue

            if repair_installed_app_state(str(library), appid, logger=logger):
                repaired.append(appid)
                if detect_recent_decryption_key_issue(str(library), appid):
                    decryption_key_blocked.append(appid)
            else:
                failed.append(appid)

    if logger:
        logger.info(
            "Reparo global de manifests LumaTools: %s reparado(s), %s ignorado(s), %s falha(s), %s bloqueado(s) por chave de depot.",
            len(repaired),
            len(skipped),
            len(failed),
            len(decryption_key_blocked),
        )
    return {
        "repaired": repaired,
        "skipped": skipped,
        "failed": failed,
        "decryption_key_blocked": decryption_key_blocked,
    }
