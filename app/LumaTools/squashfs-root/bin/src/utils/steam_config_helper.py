import os
import re
import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger("LumaTools.SteamConfigHelper")


def _escape_vdf_value(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def _unescape_vdf_value(value):
    value = str(value)
    result = []
    escaped = False
    for char in value:
        if escaped:
            result.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(char)
    if escaped:
        result.append("\\")
    return "".join(result)


def _split_overrides(value):
    overrides = []
    for item in re.split(r";", value or ""):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            # Repair older malformed values like "onlinefix64=n;b" back into
            # "onlinefix64=n,b" instead of treating "b" as another override.
            if overrides and item.lower() in {"b", "n", "native", "builtin"}:
                overrides[-1] = f"{overrides[-1]},{item}"
            continue
        overrides.append(item)
    return overrides


def _merge_launch_options(existing, desired):
    existing = (existing or "").strip()
    desired = (desired or "").strip()
    if not existing:
        return desired
    if not desired:
        return existing

    wine_pattern = r'WINEDLLOVERRIDES="([^"]*)"'
    existing_match = re.search(wine_pattern, existing)
    desired_match = re.search(wine_pattern, desired)
    if not existing_match or not desired_match:
        return desired

    merged_overrides = []
    positions = {}
    for item in _split_overrides(existing_match.group(1)) + _split_overrides(desired_match.group(1)):
        key = item.split("=", 1)[0].lower()
        if key in positions:
            merged_overrides[positions[key]] = item
        else:
            positions[key] = len(merged_overrides)
            merged_overrides.append(item)

    merged = re.sub(
        wine_pattern,
        f'WINEDLLOVERRIDES="{";".join(merged_overrides)}"',
        desired,
        count=1,
    )

    existing_extra = re.sub(wine_pattern, "", existing, count=1).strip()
    existing_extra = existing_extra.replace("%command%", "").strip()
    if existing_extra and existing_extra not in merged:
        if "%command%" in merged:
            merged = merged.replace("%command%", f"{existing_extra} %command%", 1)
        else:
            merged = f"{merged} {existing_extra}".strip()

    return merged


def _find_matching_brace(content, open_brace_index):
    depth = 0
    in_string = False
    escaped = False

    for index in range(open_brace_index, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index

    return -1


def _find_vdf_block(content, key, start=0, end=None):
    search_area = content[start:end]
    match = re.search(rf'"{re.escape(str(key))}"\s*\{{', search_area)
    if not match:
        return None

    block_start = start + match.start()
    open_brace = start + match.group(0).rfind("{") + match.start()
    block_end = _find_matching_brace(content, open_brace)
    if block_end == -1 or (end is not None and block_end > end):
        return None
    return block_start, block_end


def _replace_or_insert_launch_options(content, appid, launch_options):
    apps_block = _find_vdf_block(content, "apps")
    if not apps_block:
        steam_block = _find_vdf_block(content, "Steam")
        if not steam_block:
            root_block = _find_vdf_block(content, "UserLocalConfigStore")
            stripped = content.strip()
            if root_block:
                _root_start, root_end = root_block
                steam_tree = (
                    '\n\t"Software"\n'
                    "\t{\n"
                    '\t\t"Valve"\n'
                    "\t\t{\n"
                    '\t\t\t"Steam"\n'
                    "\t\t\t{\n"
                    '\t\t\t\t"apps"\n'
                    "\t\t\t\t{\n"
                    "\t\t\t\t}\n"
                    "\t\t\t}\n"
                    "\t\t}\n"
                    "\t}\n"
                )
                content = content[:root_end] + steam_tree + content[root_end:]
            elif stripped:
                logger.warning("Blocos 'Steam/apps' não encontrados no localconfig.vdf")
                return content, False
            else:
                content = (
                '"UserLocalConfigStore"\n'
                "{\n"
                '\t"Software"\n'
                "\t{\n"
                '\t\t"Valve"\n'
                "\t\t{\n"
                '\t\t\t"Steam"\n'
                "\t\t\t{\n"
                '\t\t\t\t"apps"\n'
                "\t\t\t\t{\n"
                "\t\t\t\t}\n"
                "\t\t\t}\n"
                "\t\t}\n"
                "\t}\n"
                "}\n"
                )
        else:
            _steam_start, steam_end = steam_block
            apps_text = '\n\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t}\n'
            content = content[:steam_end] + apps_text + content[steam_end:]
        apps_block = _find_vdf_block(content, "apps")
        if not apps_block:
            logger.warning("Falha ao criar bloco 'apps' no localconfig.vdf")
            return content, False

    apps_start, apps_end = apps_block
    app_block = _find_vdf_block(content, appid, apps_start, apps_end)

    if not app_block:
        safe_launch_options = _escape_vdf_value(launch_options)
        insertion = (
            f'\n\t\t\t\t"{appid}"\n'
            "\t\t\t\t{\n"
            f'\t\t\t\t\t"LaunchOptions"\t\t"{safe_launch_options}"\n'
            "\t\t\t\t}\n"
        )
        return content[:apps_end] + insertion + content[apps_end:], True

    app_start, app_end = app_block
    app_content = content[app_start:app_end + 1]
    launch_pattern = r'("LaunchOptions"\s*)"((?:\\.|[^"\\])*)"'

    if re.search(launch_pattern, app_content):
        existing_match = re.search(launch_pattern, app_content)
        existing_launch_options = (
            _unescape_vdf_value(existing_match.group(2)) if existing_match else ""
        )
        merged_launch_options = _merge_launch_options(existing_launch_options, launch_options)
        safe_launch_options = _escape_vdf_value(merged_launch_options)
        new_app_content = re.sub(
            launch_pattern,
            lambda match: f'{match.group(1)}"{safe_launch_options}"',
            app_content,
            count=1,
        )
    else:
        safe_launch_options = _escape_vdf_value(launch_options)
        open_brace_offset = app_content.find("{")
        new_app_content = (
            app_content[:open_brace_offset + 1]
            + f'\n\t\t\t\t\t"LaunchOptions"\t\t"{safe_launch_options}"'
            + app_content[open_brace_offset + 1:]
        )

    if new_app_content == app_content:
        return content, False
    return content[:app_start] + new_app_content + content[app_end + 1:], True


def _launch_options_already_satisfied(content, appid, launch_options):
    apps_block = _find_vdf_block(content, "apps")
    if not apps_block:
        return False
    apps_start, apps_end = apps_block
    app_block = _find_vdf_block(content, appid, apps_start, apps_end)
    if not app_block:
        return False

    app_start, app_end = app_block
    app_content = content[app_start:app_end + 1]
    match = re.search(r'("LaunchOptions"\s*)"((?:\\.|[^"\\])*)"', app_content)
    if not match:
        return False

    existing = _unescape_vdf_value(match.group(2))
    return _merge_launch_options(existing, launch_options).strip() == existing.strip()


def set_steam_launch_options(steam_root, appid, launch_options):
    """
    Define as opções de inicialização no localconfig.vdf da Steam.
    Cria o bloco apps/AppID quando a Steam ainda não criou a entrada do jogo.
    """
    if not steam_root or not os.path.exists(steam_root):
        return False

    userdata_path = os.path.join(steam_root, "userdata")
    if not os.path.exists(userdata_path):
        return False

    success = False
    for user_id in os.listdir(userdata_path):
        user_config_path = os.path.join(userdata_path, user_id, "config", "localconfig.vdf")
        if os.path.exists(user_config_path):
            try:
                with open(user_config_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                new_content, changed = _replace_or_insert_launch_options(content, appid, launch_options)
                if changed:
                    backup_path = f"{user_config_path}.lumatools-{int(time.time())}.bak"
                    shutil.copy2(user_config_path, backup_path)
                    with open(user_config_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    success = True
                    logger.info(f"LaunchOptions atualizadas para AppID {appid} no usuário {user_id}")
                elif _launch_options_already_satisfied(content, appid, launch_options):
                    success = True

            except Exception as e:
                logger.error(f"Erro ao editar localconfig para usuário {user_id}: {e}")

    return success


def _remove_launch_options(content, appid):
    apps_block = _find_vdf_block(content, "apps")
    if not apps_block:
        return content, False

    apps_start, apps_end = apps_block
    app_block = _find_vdf_block(content, appid, apps_start, apps_end)
    if not app_block:
        return content, False

    app_start, app_end = app_block
    app_content = content[app_start:app_end + 1]
    launch_pattern = r'^\s*"LaunchOptions"\s*"((?:\\.|[^"\\])*)"\s*\n?'
    new_app_content = re.sub(
        launch_pattern, "", app_content, count=1, flags=re.MULTILINE
    )
    if new_app_content == app_content:
        return content, False
    return content[:app_start] + new_app_content + content[app_end + 1:], True


def clear_steam_launch_options(steam_root, appid):
    """Remove LaunchOptions for an AppID from every Steam user config."""
    if not steam_root or not os.path.exists(steam_root):
        return False

    userdata_path = os.path.join(steam_root, "userdata")
    if not os.path.exists(userdata_path):
        return False

    success = False
    for user_id in os.listdir(userdata_path):
        user_config_path = os.path.join(userdata_path, user_id, "config", "localconfig.vdf")
        if not os.path.exists(user_config_path):
            continue
        try:
            with open(user_config_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            new_content, changed = _remove_launch_options(content, appid)
            if not changed:
                continue
            backup_path = f"{user_config_path}.lumatools-{int(time.time())}.bak"
            shutil.copy2(user_config_path, backup_path)
            with open(user_config_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            success = True
            logger.info("LaunchOptions removidas para AppID %s no usuário %s", appid, user_id)
        except Exception as e:
            logger.error("Erro ao limpar LaunchOptions para usuário %s: %s", user_id, e)

    return success


def _extract_online_fix_launch_options(game_dir: Path) -> str:
    info_path = game_dir / "LUMA_ONLINE_FIX_INFO.txt"
    if not info_path.exists():
        return ""
    try:
        content = info_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    match = re.search(r"Launch Options:\s*\n([^\n]+)", content)
    return match.group(1).strip() if match else ""


def _parse_acf_value(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*"([^"]*)"', content)
    return match.group(1) if match else ""


def repair_online_fix_launch_options(steam_root, library_paths) -> dict:
    """Re-apply saved OnlineFix launch options for all managed games.

    This is intentionally idempotent and uses each game's
    LUMA_ONLINE_FIX_INFO.txt as the source of truth.
    """
    result = {"updated": [], "missing": [], "failed": []}
    if not steam_root or not os.path.exists(steam_root):
        return result

    seen = set()
    for library_path in library_paths or []:
        steamapps = Path(library_path).expanduser() / "steamapps"
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
            except OSError:
                result["failed"].append(appid)
                continue

            installdir = _parse_acf_value(content, "installdir")
            if not installdir:
                continue

            launch_options = _extract_online_fix_launch_options(common / installdir)
            if not launch_options:
                continue

            if set_steam_launch_options(steam_root, appid, launch_options):
                result["updated"].append(appid)
            else:
                result["missing"].append(appid)

    logger.info(
        "Reparo global de Launch Options OnlineFix: %s atualizado(s), %s sem alteração/usuário, %s falha(s).",
        len(result["updated"]),
        len(result["missing"]),
        len(result["failed"]),
    )
    return result
