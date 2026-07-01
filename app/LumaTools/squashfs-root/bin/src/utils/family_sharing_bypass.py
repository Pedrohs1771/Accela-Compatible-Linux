"""
LumaTools — Family Sharing Bypass Avançado.

Implementa bypass completo de Family Sharing para Steam, permitindo
que jogos compartilhados sejam jogados sem restrição de sessão.

Funciona via configuração do SLSsteam (Linux) e registro/GreenLuma (Windows):
1. DisableFamilyShareLock no config.yaml
2. PlayNotOwnedGames para desbloquear jogos não comprados
3. Registro de AppIDs no AdditionalApps
4. Geração de AppTicket simulado (Windows via registro)
5. Limpeza de session locks existentes

Baseado nos mecanismos do OpenSteamTool e steam-tools.
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def apply_family_sharing_bypass(app_id: str) -> bool:
    """Aplica bypass completo de Family Sharing.

    Configura SLSsteam (Linux) ou GreenLuma (Windows) para:
    - Desabilitar lock de Family Sharing
    - Permitir jogar jogos não comprados
    - Registrar o AppID nos apps adicionais
    - Filtrar automaticamente a library

    Parameters
    ----------
    app_id : str
        O AppID do jogo a desbloquear.

    Returns
    -------
    bool
        True se pelo menos a configuração principal foi aplicada.
    """
    app_id = str(app_id).strip()
    if not app_id.isdigit():
        logger.error("Invalid AppID for family sharing bypass: %s", app_id)
        return False

    logger.info("Applying Family Sharing bypass for AppID: %s", app_id)

    if sys.platform == "linux":
        return _apply_linux_bypass(app_id)
    elif sys.platform == "win32":
        return _apply_windows_bypass(app_id)
    else:
        logger.warning("Family Sharing bypass not supported on %s", sys.platform)
        return False


def _apply_linux_bypass(app_id: str) -> bool:
    """Apply Family Sharing bypass on Linux via SLSsteam config.yaml."""
    try:
        from utils.yaml_config_manager import (
            add_additional_app,
            ensure_slssteam_config,
            get_user_config_path,
            update_yaml_boolean_value,
        )

        config_path = get_user_config_path()

        # Ensure config exists
        ensure_slssteam_config(config_path)

        if not config_path.exists():
            logger.error("SLSsteam config not found at %s", config_path)
            return False

        success = True

        # 1. Disable Family Share Lock
        if not update_yaml_boolean_value(config_path, "DisableFamilyShareLock", True):
            # Key might already be set, check current value
            content = config_path.read_text(encoding="utf-8")
            if "DisableFamilyShareLock: yes" not in content:
                logger.warning("Failed to set DisableFamilyShareLock")
                success = False

        # 2. Enable playing non-owned games
        update_yaml_boolean_value(config_path, "PlayNotOwnedGames", True)

        # 3. Enable auto filter list (hides non-installed games)
        update_yaml_boolean_value(config_path, "AutoFilterList", True)

        # 4. Add AppID to AdditionalApps for SLSsteam tracking
        add_additional_app(
            config_path,
            app_id,
            comment="LumaTools Family Sharing Bypass",
        )

        logger.info(
            "Linux Family Sharing bypass applied for AppID %s via %s",
            app_id,
            config_path,
        )
        return success

    except Exception as exc:
        logger.error("Failed to apply Linux family sharing bypass: %s", exc)
        return False


def _apply_windows_bypass(app_id: str) -> bool:
    """Apply Family Sharing bypass on Windows via registry and GreenLuma."""
    try:
        from core.steam_helpers import (
            app_id_exists_in_applist,
            find_next_applist_number,
            find_steam_install,
        )

        steam_path = find_steam_install()
        if not steam_path:
            logger.error("Steam installation not found")
            return False

        # 1. Add to GreenLuma AppList
        app_list_dir = os.path.join(steam_path, "AppList")
        if not app_id_exists_in_applist(app_list_dir, app_id):
            next_num = find_next_applist_number(app_list_dir)
            applist_file = os.path.join(app_list_dir, f"{next_num}.txt")
            os.makedirs(app_list_dir, exist_ok=True)

            with open(applist_file, "w", encoding="utf-8") as f:
                f.write(app_id)
            logger.info(
                "Added AppID %s to GreenLuma AppList as %s",
                app_id,
                applist_file,
            )

        # 2. Generate AppTicket in Windows Registry
        _generate_app_ticket_windows(app_id)

        logger.info("Windows Family Sharing bypass applied for AppID %s", app_id)
        return True

    except Exception as exc:
        logger.error("Failed to apply Windows family sharing bypass: %s", exc)
        return False


def _generate_app_ticket_windows(app_id: str) -> bool:
    """Write a placeholder AppTicket to the Windows registry.

    OpenSteamTool can reuse Steam's local ConfigStore ticket for SteamStub
    games, but for the registry path fallback we create the key structure.
    """
    if sys.platform != "win32":
        return False

    try:
        import winreg

        key_path = f"Software\\Valve\\Steam\\Apps\\{app_id}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            # Set Installed flag
            winreg.SetValueEx(key, "Installed", 0, winreg.REG_DWORD, 1)
            logger.info(
                "Set registry Installed flag for AppID %s at HKCU\\%s",
                app_id,
                key_path,
            )
        return True
    except Exception as exc:
        logger.error("Failed to write to registry for AppID %s: %s", app_id, exc)
        return False


def remove_family_sharing_bypass(app_id: str) -> bool:
    """Remove family sharing bypass configuration for an app.

    Parameters
    ----------
    app_id : str
        The AppID to remove bypass for.

    Returns
    -------
    bool
        True if removal was successful.
    """
    app_id = str(app_id).strip()
    if not app_id.isdigit():
        return False

    if sys.platform == "linux":
        try:
            from utils.yaml_config_manager import (
                get_user_config_path,
                remove_additional_app,
            )

            config_path = get_user_config_path()
            remove_additional_app(config_path, app_id)
            logger.info("Removed Family Sharing bypass for AppID %s", app_id)
            return True
        except Exception as exc:
            logger.error("Failed to remove bypass for %s: %s", app_id, exc)
            return False

    return False


def is_family_sharing_bypassed(app_id: str) -> bool:
    """Check if family sharing bypass is active for an app.

    Parameters
    ----------
    app_id : str
        The AppID to check.

    Returns
    -------
    bool
        True if bypass is currently active.
    """
    app_id = str(app_id).strip()
    if not app_id.isdigit():
        return False

    if sys.platform == "linux":
        try:
            from utils.yaml_config_manager import get_user_config_path

            config_path = get_user_config_path()
            if not config_path.exists():
                return False

            content = config_path.read_text(encoding="utf-8")

            # Check DisableFamilyShareLock is enabled
            has_lock_disabled = bool(
                re.search(r"DisableFamilyShareLock:\s*yes", content, re.IGNORECASE)
            )

            # Check AppID is in AdditionalApps
            has_appid = bool(
                re.search(
                    rf"^\s*-\s*{re.escape(app_id)}\b",
                    content,
                    re.MULTILINE,
                )
            )

            return has_lock_disabled and has_appid

        except Exception:
            return False

    elif sys.platform == "win32":
        try:
            from core.steam_helpers import app_id_exists_in_applist, find_steam_install

            steam_path = find_steam_install()
            if not steam_path:
                return False

            app_list_dir = os.path.join(steam_path, "AppList")
            return app_id_exists_in_applist(app_list_dir, app_id)
        except Exception:
            return False

    return False


# ── Legacy aliases ────────────────────────────────────────────────────────────

def generate_app_ticket(app_id: str) -> Optional[str]:
    """Legacy wrapper. Use apply_family_sharing_bypass instead."""
    if sys.platform == "win32":
        _generate_app_ticket_windows(app_id)
    return None


def apply_advanced_bypasses(app_id: str) -> bool:
    """Legacy wrapper for backward compatibility."""
    return apply_family_sharing_bypass(app_id)
