import os
import re
import shutil
import sys
import time
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

    platform_config = _build_platform_config(
        selected_depots, all_depots, log_proton, logger
    )
    depots_content = _build_depots_content(selected_depots, all_manifests, all_depots)

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
        f'\t"LastOwner"\t\t"0"\n'
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

        for folder in ("downloading", "temp"):
            path = os.path.join(steamapps_dir, folder, str(appid))
            if os.path.exists(path):
                shutil.rmtree(path, ignore_errors=True)

        if logger:
            logger.info("Steam appmanifest reparado para AppID %s", appid)
        return True
    except OSError as exc:
        if logger:
            logger.warning("Falha ao reparar appmanifest %s: %s", acf_path, exc)
        return False
