import os
import re
import logging
import shutil
import time

logger = logging.getLogger("LumaTools.SteamConfigHelper")


def _escape_vdf_value(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


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


def _replace_or_insert_launch_options(content, appid, safe_launch_options):
    apps_block = _find_vdf_block(content, "apps")
    if not apps_block:
        steam_block = _find_vdf_block(content, "Steam")
        if not steam_block:
            stripped = content.strip()
            if stripped:
                logger.warning("Blocos 'Steam/apps' não encontrados no localconfig.vdf")
                return content, False
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
        new_app_content = re.sub(
            launch_pattern,
            rf'\1"{safe_launch_options}"',
            app_content,
            count=1,
        )
    else:
        open_brace_offset = app_content.find("{")
        new_app_content = (
            app_content[:open_brace_offset + 1]
            + f'\n\t\t\t\t\t"LaunchOptions"\t\t"{safe_launch_options}"'
            + app_content[open_brace_offset + 1:]
        )

    if new_app_content == app_content:
        return content, False
    return content[:app_start] + new_app_content + content[app_end + 1:], True


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

    safe_launch_options = _escape_vdf_value(launch_options)

    success = False
    for user_id in os.listdir(userdata_path):
        user_config_path = os.path.join(userdata_path, user_id, "config", "localconfig.vdf")
        if os.path.exists(user_config_path):
            try:
                with open(user_config_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                new_content, changed = _replace_or_insert_launch_options(content, appid, safe_launch_options)
                if changed:
                    backup_path = f"{user_config_path}.lumatools-{int(time.time())}.bak"
                    shutil.copy2(user_config_path, backup_path)
                    with open(user_config_path, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    success = True
                    logger.info(f"LaunchOptions atualizadas para AppID {appid} no usuário {user_id}")

            except Exception as e:
                logger.error(f"Erro ao editar localconfig para usuário {user_id}: {e}")

    return success
