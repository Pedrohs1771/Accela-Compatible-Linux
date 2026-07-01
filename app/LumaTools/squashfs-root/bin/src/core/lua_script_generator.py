"""
LumaTools — Gerador de Scripts Lua para OpenSteamTool / SLSsteam.

Gera scripts .lua compatíveis com ambos os ecossistemas, contendo:
- addappid() para jogo base, depots e DLCs
- addtoken() para access tokens de depots protegidos
- setManifestid() para pinning de manifestos
- setAppTicket() / setETicket() quando disponíveis
"""

import logging
import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LuaScriptGenerator:
    """Gera scripts Lua de manifesto compatíveis com OpenSteamTool e SLSsteam."""

    HEADER_TEMPLATE = textwrap.dedent("""\
        -- ============================================================
        -- LumaTools Auto-Generated Lua Script
        -- Game: {game_name}
        -- AppID: {appid}
        -- Generated: {timestamp}
        -- ============================================================
    """)

    def generate(self, game_data: Dict[str, Any]) -> str:
        """Gera o conteúdo completo do script Lua a partir de game_data.

        Parameters
        ----------
        game_data : dict
            Deve conter pelo menos ``appid`` e ``game_name``.  Campos
            opcionais: ``depots``, ``tokens``, ``dlcs``, ``manifests``,
            ``manifest_sizes``, ``depot_keys``, ``app_ticket``,
            ``e_ticket``.

        Returns
        -------
        str
            Conteúdo Lua pronto para escrita em disco.
        """
        appid = str(game_data.get("appid", ""))
        game_name = str(game_data.get("game_name", f"App_{appid}"))

        lines: list[str] = []

        # ── Header ────────────────────────────────────────────────────
        lines.append(self.HEADER_TEMPLATE.format(
            game_name=game_name,
            appid=appid,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        ))

        # ── Base app ──────────────────────────────────────────────────
        lines.append("-- Base game")
        depot_keys = game_data.get("depot_keys", {})
        base_key = depot_keys.get(appid, "")
        if base_key:
            lines.append(f'addappid({appid}, 0, "{base_key}")')
        else:
            lines.append(f"addappid({appid})")
        lines.append("")

        # ── Depots ────────────────────────────────────────────────────
        depots = game_data.get("depots", {})
        if depots:
            lines.append("-- Depots")
            for depot_id, depot_info in depots.items():
                depot_id_str = str(depot_id)
                if depot_id_str == appid:
                    continue  # already added above

                depot_key = ""
                if isinstance(depot_info, dict):
                    depot_key = depot_info.get("depot_key", "")
                if not depot_key:
                    depot_key = depot_keys.get(depot_id_str, "")

                name = ""
                if isinstance(depot_info, dict):
                    name = depot_info.get("name", "")

                comment = f"  -- {name}" if name else ""

                if depot_key:
                    lines.append(
                        f'addappid({depot_id_str}, 0, "{depot_key}"){comment}'
                    )
                else:
                    lines.append(f"addappid({depot_id_str}){comment}")
            lines.append("")

        # ── Access Tokens ─────────────────────────────────────────────
        tokens = game_data.get("tokens", {})
        if tokens:
            lines.append("-- Access Tokens")
            for token_appid, token_value in tokens.items():
                lines.append(f'addtoken({token_appid}, "{token_value}")')
            lines.append("")

        # ── DLCs ──────────────────────────────────────────────────────
        dlcs = game_data.get("dlcs", {})
        if dlcs:
            lines.append("-- DLCs")
            for dlc_id, dlc_name in dlcs.items():
                dlc_id_str = str(dlc_id)
                comment = f"  -- {dlc_name}" if dlc_name else ""
                dlc_key = depot_keys.get(dlc_id_str, "")
                if dlc_key:
                    lines.append(
                        f'addappid({dlc_id_str}, 0, "{dlc_key}"){comment}'
                    )
                else:
                    lines.append(f"addappid({dlc_id_str}){comment}")
            lines.append("")

        # ── Manifest Pinning ──────────────────────────────────────────
        manifests = game_data.get("manifests", {})
        if manifests:
            lines.append("-- Manifest Pinning")
            manifest_sizes = game_data.get("manifest_sizes", {})
            for depot_id, manifest_gid in manifests.items():
                if not manifest_gid:
                    continue
                size = manifest_sizes.get(str(depot_id), 0)
                try:
                    size = int(size)
                except (ValueError, TypeError):
                    size = 0
                if size > 0:
                    lines.append(
                        f'setManifestid({depot_id}, "{manifest_gid}", {size})'
                    )
                else:
                    lines.append(f'setManifestid({depot_id}, "{manifest_gid}")')
            lines.append("")

        # ── Tickets ───────────────────────────────────────────────────
        app_ticket = game_data.get("app_ticket", "")
        e_ticket = game_data.get("e_ticket", "")
        if app_ticket or e_ticket:
            lines.append("-- Tickets (Denuvo / SteamStub)")
            if app_ticket:
                lines.append(f'setAppTicket({appid}, "{app_ticket}")')
            if e_ticket:
                lines.append(f'setETicket({appid}, "{e_ticket}")')
            lines.append("")

        return "\n".join(lines)

    def generate_and_write(
        self,
        game_data: Dict[str, Any],
        output_dir: str | os.PathLike[str],
        filename: Optional[str] = None,
    ) -> Path:
        """Gera o script e salva em disco.

        Returns
        -------
        Path
            Caminho absoluto do arquivo gerado.
        """
        appid = str(game_data.get("appid", "unknown"))
        fname = filename or f"{appid}.lua"
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        target = output_path / fname

        content = self.generate(game_data)
        target.write_text(content, encoding="utf-8")
        logger.info("Generated Lua script for AppID %s at %s", appid, target)
        return target


def parse_lua_script(lua_content: str) -> Dict[str, Any]:
    """Parse an existing Lua script back into a game_data-like dict.

    This is a best-effort parser that extracts addappid, addtoken,
    setManifestid calls from the Lua content.
    """
    data: Dict[str, Any] = {
        "appids": [],
        "depot_keys": {},
        "tokens": {},
        "manifests": {},
        "manifest_sizes": {},
    }

    # addappid(appid) or addappid(appid, 0, "depotkey")
    for match in re.finditer(
        r'addappid\s*\(\s*(\d+)\s*(?:,\s*\d+\s*(?:,\s*"([^"]*)")?)?\s*\)',
        lua_content,
        re.IGNORECASE,
    ):
        appid = match.group(1)
        depot_key = match.group(2) or ""
        data["appids"].append(appid)
        if depot_key:
            data["depot_keys"][appid] = depot_key

    # addtoken(appid, "token")
    for match in re.finditer(
        r'addtoken\s*\(\s*(\d+)\s*,\s*"([^"]+)"\s*\)',
        lua_content,
        re.IGNORECASE,
    ):
        data["tokens"][match.group(1)] = match.group(2)

    # setManifestid(depotid, "gid") or setManifestid(depotid, "gid", size)
    for match in re.finditer(
        r'setManifestid\s*\(\s*(\d+)\s*,\s*"(\d+)"(?:\s*,\s*(\d+))?\s*\)',
        lua_content,
        re.IGNORECASE,
    ):
        depot_id = match.group(1)
        manifest_gid = match.group(2)
        size = match.group(3) or "0"
        data["manifests"][depot_id] = manifest_gid
        data["manifest_sizes"][depot_id] = int(size)

    # Determine base appid (first one)
    if data["appids"]:
        data["appid"] = data["appids"][0]

    return data


def generate_with_auto_tokens(game_data: Dict[str, Any], client: Any) -> str:
    """Busca tokens automaticamente usando um cliente steam e gera o script."""
    tokens = game_data.get("tokens", {})
    depots = game_data.get("depots", {})
    
    for depot_id in depots:
        if str(depot_id) not in tokens:
            try:
                # Simula a chamada ao steam.client
                # Em um cenário real, client.get_depot_key(...)
                # Vamos injetar um mock para testes
                if hasattr(client, "get_depot_key"):
                    key = client.get_depot_key(game_data.get("appid"), depot_id)
                    if key:
                        tokens[str(depot_id)] = key
            except Exception as e:
                logger.warning("Failed to auto-fetch token for depot %s: %s", depot_id, e)
                
    game_data["tokens"] = tokens
    generator = LuaScriptGenerator()
    return generator.generate(game_data)


def merge_lua_scripts(script1_content: str, script2_content: str) -> str:
    """Faz o merge de dois scripts Lua, combinando AppIDs, tokens e manifests."""
    data1 = parse_lua_script(script1_content)
    data2 = parse_lua_script(script2_content)
    
    # Merge AppIDs & Keys
    merged_appids = list(dict.fromkeys(data1.get("appids", []) + data2.get("appids", [])))
    merged_keys = {**data1.get("depot_keys", {}), **data2.get("depot_keys", {})}
    
    # Merge Tokens
    merged_tokens = {**data1.get("tokens", {}), **data2.get("tokens", {})}
    
    # Merge Manifests
    merged_manifests = {**data1.get("manifests", {}), **data2.get("manifests", {})}
    merged_manifest_sizes = {**data1.get("manifest_sizes", {}), **data2.get("manifest_sizes", {})}
    
    # Reconstroi game_data
    appid = data1.get("appid") or data2.get("appid") or "unknown"
    merged_data = {
        "appid": appid,
        "game_name": f"Merged_{appid}",
        "depots": {d: {} for d in merged_appids if d != appid},
        "depot_keys": merged_keys,
        "tokens": merged_tokens,
        "manifests": merged_manifests,
        "manifest_sizes": merged_manifest_sizes,
    }
    
    generator = LuaScriptGenerator()
    return generator.generate(merged_data)


def diff_and_update(existing_content: str, new_game_data: Dict[str, Any]) -> str:
    """Atualiza um script existente mantendo customizações, apenas adicionando novas entradas."""
    existing_data = parse_lua_script(existing_content)
    
    # Apenas adicione manifests que não existem no original
    for depot_id, manifest_gid in new_game_data.get("manifests", {}).items():
        if str(depot_id) not in existing_data.get("manifests", {}):
            existing_data.setdefault("manifests", {})[str(depot_id)] = manifest_gid
            
    # Mesma coisa para tokens
    for depot_id, token in new_game_data.get("tokens", {}).items():
        if str(depot_id) not in existing_data.get("tokens", {}):
            existing_data.setdefault("tokens", {})[str(depot_id)] = token
            
    # Adicionar appids faltantes nos depots do new_data
    existing_appids = set(existing_data.get("appids", []))
    new_appids = set(new_game_data.get("appids", []))
    
    # Reconstroi para geração
    appid = existing_data.get("appid", new_game_data.get("appid", "unknown"))
    
    # Adiciona depots baseados no new_game_data que não estão no original
    depots_to_add = new_appids - existing_appids
    merged_depots = {d: {} for d in existing_appids if d != appid}
    for d in depots_to_add:
        if d != appid:
            merged_depots[d] = {}
            
    # Merge keys
    merged_keys = {**new_game_data.get("depot_keys", {}), **existing_data.get("depot_keys", {})}
            
    merged_data = {
        "appid": appid,
        "game_name": new_game_data.get("game_name", f"Updated_{appid}"),
        "depots": merged_depots,
        "depot_keys": merged_keys,
        "tokens": existing_data.get("tokens", {}),
        "manifests": existing_data.get("manifests", {}),
        "manifest_sizes": existing_data.get("manifest_sizes", {}),
    }
    
    generator = LuaScriptGenerator()
    return generator.generate(merged_data)
