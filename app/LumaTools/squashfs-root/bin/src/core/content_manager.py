from __future__ import annotations

import json
import logging
import os
import re
import sys
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.tasks.process_zip_task import ProcessZipTask
from utils.helpers import get_base_path
from utils.wrapper_metadata import persist_selected_dlcs
from utils.yaml_config_manager import (
    add_additional_app,
    add_dlc_data,
    ensure_slssteam_config,
    get_user_config_path,
)

logger = logging.getLogger(__name__)


@dataclass
class ContentPackagePreview:
    zip_path: str
    filename: str
    appid: str
    game_name: str
    depots: list[str]
    dlcs: list[str]
    manifests: list[str]
    lua_files: list[str]
    source: str = "local_zip"

    @property
    def is_valid(self) -> bool:
        return bool(self.appid and self.lua_files and self.manifests)


class ContentManager:
    """Preview and registry helpers for Ryuu/ZIP content packages."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = Path(base_path or get_base_path())
        self.registry_path = self.base_path / "content_registry.json"

    def preview_zip(self, zip_path: str | os.PathLike[str]) -> ContentPackagePreview:
        path = Path(zip_path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"ZIP nao encontrado: {path}")

        game_data: dict[str, Any] = {"manifest_sizes": {}}
        with zipfile.ZipFile(path, "r") as zip_ref:
            names = zip_ref.namelist()
            lua_files = [name for name in names if name.lower().endswith(".lua")]
            manifest_files = [
                name for name in names if name.lower().endswith(".manifest")
            ]

            if not lua_files:
                raise ValueError("ZIP sem arquivo .lua.")

            lua_content = zip_ref.read(lua_files[0]).decode("utf-8", errors="replace")
            ProcessZipTask._parse_lua(lua_content, game_data)

        manifest_depots = []
        for manifest in manifest_files:
            stem = Path(manifest).name.replace(".manifest", "")
            match = re.match(r"(\d+)_", stem)
            if match:
                manifest_depots.append(match.group(1))

        depots = sorted(
            set(str(item) for item in (game_data.get("depots") or {}).keys())
            | set(manifest_depots)
        )
        dlcs = sorted(str(item) for item in (game_data.get("dlcs") or {}).keys())

        return ContentPackagePreview(
            zip_path=str(path),
            filename=path.name,
            appid=str(game_data.get("appid") or ""),
            game_name=str(game_data.get("game_name") or f"App_{game_data.get('appid', '')}"),
            depots=depots,
            dlcs=dlcs,
            manifests=sorted(Path(item).name for item in manifest_files),
            lua_files=sorted(Path(item).name for item in lua_files),
        )

    def build_dlc_preview(
        self,
        *,
        appid: str,
        game_name: str,
        dlcs: list[str],
        source: str,
        filename: str = "Steam DLC catalog",
        zip_path: str = "",
    ) -> ContentPackagePreview:
        cleaned: list[str] = []
        seen: set[str] = set()
        for dlc_id in dlcs:
            text = str(dlc_id).strip()
            if text and text.isdigit() and text not in seen and text != str(appid):
                seen.add(text)
                cleaned.append(text)
        return ContentPackagePreview(
            zip_path=zip_path,
            filename=filename,
            appid=str(appid),
            game_name=game_name or f"App_{appid}",
            depots=[],
            dlcs=cleaned,
            manifests=[],
            lua_files=[],
            source=source,
        )

    def fetch_store_dlc_catalog(self, appid: str) -> tuple[dict[str, str], str]:
        """Return DLC AppIDs exposed by Steam Store for the base app.

        This is a catalog lookup only. It does not download or modify files.
        Some games do not expose DLC in the public Store API; callers should
        treat an empty result as "no public DLC catalog found", not as failure.
        """
        appid = str(appid).strip()
        response = requests.get(
            "https://store.steampowered.com/api/appdetails",
            params={"appids": appid, "filters": "basic"},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 LumaTools"},
        )
        response.raise_for_status()
        payload = response.json().get(appid, {})
        if not payload.get("success"):
            return {}, ""

        data = payload.get("data") or {}
        game_name = str(data.get("name") or "")
        dlc_ids = [str(item) for item in (data.get("dlc") or []) if str(item).isdigit()]
        if not dlc_ids:
            dlc_ids = self._scrape_store_dlc_ids(appid)
        if not dlc_ids:
            return {}, game_name
        return self.fetch_app_names(dlc_ids), game_name

    def _scrape_store_dlc_ids(self, appid: str) -> list[str]:
        try:
            response = requests.get(
                f"https://store.steampowered.com/dlc/{appid}/",
                timeout=6,
                headers={"User-Agent": "Mozilla/5.0 LumaTools"},
            )
            response.raise_for_status()
        except Exception:
            logger.debug("Steam DLC page scrape failed for %s", appid, exc_info=True)
            return []

        found: list[str] = []
        seen: set[str] = {str(appid)}
        for match in re.finditer(r"/app/(\d+)", response.text):
            dlc_id = match.group(1)
            if dlc_id not in seen:
                seen.add(dlc_id)
                found.append(dlc_id)
        return found

    def fetch_app_names(self, appids: list[str], *, limit: int = 80) -> dict[str, str]:
        ids = []
        seen: set[str] = set()
        for appid in appids:
            text = str(appid).strip()
            if text.isdigit() and text not in seen:
                seen.add(text)
                ids.append(text)
            if len(ids) >= limit:
                break

        names: dict[str, str] = {}
        for index in range(0, len(ids), 20):
            batch = ids[index : index + 20]
            try:
                response = requests.get(
                    "https://store.steampowered.com/api/appdetails",
                    params={"appids": ",".join(batch), "filters": "basic"},
                    timeout=8,
                    headers={"User-Agent": "Mozilla/5.0 LumaTools"},
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Steam returned a non-object appdetails payload")
                for appid in batch:
                    data = payload.get(appid, {})
                    if data.get("success") and data.get("data", {}).get("name"):
                        names[appid] = str(data["data"]["name"])
            except Exception:
                logger.debug("Failed to fetch Steam app names for %s", batch, exc_info=True)
                for appid in batch:
                    try:
                        response = requests.get(
                            "https://store.steampowered.com/api/appdetails",
                            params={"appids": appid, "filters": "basic"},
                            timeout=2.5,
                            headers={"User-Agent": "Mozilla/5.0 LumaTools"},
                        )
                        response.raise_for_status()
                        data = response.json().get(appid, {})
                        if data.get("success") and data.get("data", {}).get("name"):
                            names[appid] = str(data["data"]["name"])
                    except Exception:
                        logger.debug("Failed to fetch Steam app name for %s", appid, exc_info=True)
        return names

    def load_registry(self) -> dict[str, Any]:
        if not self.registry_path.exists():
            return {"packages": [], "workshop": []}
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("packages", [])
                payload.setdefault("workshop", [])
                return payload
        except Exception:
            logger.warning("Failed to load content registry", exc_info=True)
        return {"packages": [], "workshop": []}

    def save_registry(self, payload: dict[str, Any]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def register_package(
        self,
        preview: ContentPackagePreview,
        source: str,
        status: str = "queued",
    ) -> None:
        payload = self.load_registry()
        packages = payload.setdefault("packages", [])
        record = asdict(preview)
        record["source"] = source
        record["status"] = status
        packages.append(record)
        self.save_registry(payload)

    def auto_unlock_all_dlcs(
        self,
        appid: str,
        game_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        """Automatically fetch and unlock all DLCs for a given AppID."""
        appid = str(appid).strip()
        logger.info(f"Starting automatic DLC unlock for AppID {appid}")
        
        # 1. Fetch catalog
        dlc_names, game_name = self.fetch_store_dlc_catalog(appid)
        dlcs = list(dlc_names.keys())
        
        if not dlcs:
            logger.warning(f"No DLCs found for AppID {appid} to auto-unlock.")
            return {"success": False, "message": "No DLCs found"}
            
        # 2. Build preview
        preview = self.build_dlc_preview(
            appid=appid,
            game_name=game_name,
            dlcs=dlcs,
            source="auto_unlock",
            filename=f"AutoUnlock_{appid}"
        )
        
        # 3. Activate DLCs
        info = self.activate_dlcs(
            preview=preview,
            game_dir=game_dir,
            selected_dlcs=dlcs,
            dlc_names=dlc_names,
            source="auto_unlock"
        )
        
        return {"success": True, "activated_count": len(dlcs), "info": info}

    def activate_dlcs(
        self,
        preview: ContentPackagePreview,
        game_dir: str | os.PathLike[str],
        selected_dlcs: list[str],
        dlc_names: dict[str, str] | None = None,
        source: str = "local_zip",
    ) -> dict[str, Any]:
        """Activate DLC IDs for an installed game without touching game files.

        This intentionally does not route through the normal ZIP job pipeline,
        because that pipeline may download/validate depots. DLC activation only
        needs to update integration metadata/config.
        """
        root = Path(game_dir).expanduser().resolve()
        if not root.exists():
            raise FileNotFoundError(f"Pasta do jogo nao encontrada: {root}")

        available = {str(dlc_id) for dlc_id in preview.dlcs}
        selected: list[str] = []
        seen: set[str] = set()
        for dlc_id in selected_dlcs:
            dlc_text = str(dlc_id).strip()
            if not dlc_text or dlc_text in seen:
                continue
            if available and dlc_text not in available:
                logger.warning("Skipping DLC %s because it is not in package %s", dlc_text, preview.filename)
                continue
            seen.add(dlc_text)
            selected.append(dlc_text)

        if not selected:
            raise ValueError("Nenhuma DLC valida selecionada.")

        names = dlc_names or {}
        config_path = get_user_config_path()
        slssteam_ok = ensure_slssteam_config(config_path)
        main_added = add_additional_app(config_path, str(preview.appid), preview.game_name)
        dlc_entries = []
        for dlc_id in selected:
            dlc_name = names.get(str(dlc_id), f"DLC {dlc_id}")
            add_additional_app(config_path, str(dlc_id), dlc_name)
            add_dlc_data(config_path, str(preview.appid), str(dlc_id), dlc_name)
            dlc_entries.append({"appid": str(dlc_id), "name": dlc_name})

        metadata_ok = persist_selected_dlcs(root, selected)
        info = {
            "game_name": preview.game_name,
            "appid": str(preview.appid),
            "game_dir": str(root),
            "source": source,
            "package": preview.filename,
            "package_path": preview.zip_path,
            "activated_dlcs": dlc_entries,
            "slssteam_config": str(config_path),
            "slssteam_config_ready": bool(slssteam_ok or config_path.exists()),
            "main_app_added": bool(main_added),
            "wrapper_metadata_written": bool(metadata_ok),
            "activated_at": datetime.now(timezone.utc).isoformat(),
        }
        info_path = root / "LUMA_DLC_CONTENT_INFO.json"
        info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        payload = self.load_registry()
        activations = payload.setdefault("dlc_activations", [])
        activations.append(info)
        self.save_registry(payload)
        logger.info(
            "Activated %s DLC(s) for %s without depot overwrite",
            len(selected),
            preview.game_name,
        )
        return info

    def deep_scan_dlcs(self, appid: str) -> dict[str, str]:
        """Varredura profunda por DLCs, cruzando API da loja e scraping direto."""
        api_dlcs, _ = self.fetch_store_dlc_catalog(appid)
        scraped_ids = self._scrape_store_dlc_ids(appid)
        
        # Merge de IDs scraped que nao vieram na API
        missing_ids = [did for did in scraped_ids if did not in api_dlcs]
        if missing_ids:
            missing_names = self.fetch_app_names(missing_ids)
            api_dlcs.update(missing_names)
            
        return api_dlcs

    def auto_detect_dlc_method(self, game_dir: str | os.PathLike[str]) -> str:
        """Determina o melhor método de unlock (slssteam, creamapi, goldberg)."""
        root = Path(game_dir).expanduser().resolve()
        if not root.exists():
            return "slssteam"
            
        has_steam_api = any(root.rglob("steam_api.dll")) or any(root.rglob("steam_api64.dll"))
        has_goldberg = (root / "steam_settings").exists()
        
        if has_goldberg:
            return "goldberg"
            
        # No Linux, se tem steam_api.dll, é jogo Windows via Proton.
        # CreamAPI/SmokeAPI funciona perfeitamente injetado.
        if has_steam_api and sys.platform == "linux":
            # Poderíamos também preferir slssteam, mas o plano pede creamapi fallback
            return "creamapi"
            
        return "slssteam"

    def generate_cream_api_config(self, game_dir: str | os.PathLike[str], appid: str, dlc_dict: dict[str, str]) -> str:
        """Gera um arquivo cream_api.ini para a lista de DLCs fornecida."""
        root = Path(game_dir).expanduser().resolve()
        
        ini_content = "[steam]\n"
        ini_content += f"appid = {appid}\n"
        ini_content += "unlockall = false\n"
        ini_content += "orgapi = steam_api_o.dll\n"
        ini_content += "orgapi64 = steam_api64_o.dll\n"
        ini_content += "extraprotection = false\n"
        ini_content += "forceappid = false\n\n"
        
        ini_content += "[steam_misc]\n"
        ini_content += "disableuserinterface = false\n\n"
        
        ini_content += "[dlc]\n"
        for did, dname in dlc_dict.items():
            ini_content += f"{did} = {dname}\n"
            
        ini_path = root / "cream_api.ini"
        ini_path.write_text(ini_content, encoding="utf-8")
        logger.info("Generated cream_api.ini at %s", ini_path)
        return str(ini_path)

    def generate_goldberg_dlc_txt(self, game_dir: str | os.PathLike[str], dlc_dict: dict[str, str]) -> str:
        """Gera DLC.txt para o Goldberg emulator."""
        root = Path(game_dir).expanduser().resolve()
        settings_dir = root / "steam_settings"
        settings_dir.mkdir(exist_ok=True)
        
        txt_content = ""
        for did, dname in dlc_dict.items():
            txt_content += f"{did}={dname}\n"
            
        txt_path = settings_dir / "DLC.txt"
        txt_path.write_text(txt_content, encoding="utf-8")
        logger.info("Generated Goldberg DLC.txt at %s", txt_path)
        return str(txt_path)

    def batch_activate_all_dlcs(self, appid: str, game_dir: str | os.PathLike[str]) -> dict[str, Any]:
        """Método de ativação definitivo: scaneia, detecta método e ativa."""
        appid = str(appid).strip()
        root = Path(game_dir).expanduser().resolve()
        
        dlc_dict = self.deep_scan_dlcs(appid)
        if not dlc_dict:
            return {"success": False, "message": "No DLCs found"}
            
        method = self.auto_detect_dlc_method(root)
        logger.info("Auto-detected DLC method '%s' for AppID %s", method, appid)
        
        result = {
            "success": True,
            "method": method,
            "activated_count": len(dlc_dict),
            "dlcs": dlc_dict,
            "paths": []
        }
        
        if method == "creamapi":
            ini_path = self.generate_cream_api_config(root, appid, dlc_dict)
            result["paths"].append(ini_path)
            # Para CreamAPI funcionar, online_fix_injector deveria trocar as DLLs,
            # mas assumimos que o config está pronto.
            
        elif method == "goldberg":
            txt_path = self.generate_goldberg_dlc_txt(root, dlc_dict)
            result["paths"].append(txt_path)
            
        elif method == "slssteam":
            # Usa o método padrão do LumaTools (config.yaml)
            self.auto_unlock_all_dlcs(appid, root)
            result["paths"].append(str(get_user_config_path()))
            
        return result

    def verify_dlc_files_exist(self, game_dir: str | os.PathLike[str]) -> bool:
        """Verifica heuristicamente se há arquivos extras que poderiam ser DLCs."""
        root = Path(game_dir).expanduser().resolve()
        if not root.exists():
            return False
            
        # Verifica diretórios comuns de DLC
        dlc_folders = ["DLC", "dlc", "Expansion", "addons", "Addons"]
        for folder in dlc_folders:
            if (root / folder).exists():
                return True
                
        # Verifica arquivos com dlc no nome (muito comum em Unity/Unreal)
        has_dlc_files = any(root.rglob("*dlc*.*")) or any(root.rglob("*DLC*.*"))
        return has_dlc_files
