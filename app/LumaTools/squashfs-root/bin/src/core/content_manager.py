from __future__ import annotations

import json
import logging
import os
import re
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from core.dlc_discovery import DlcCandidate, discover_dlc_package
from core.dlc_cache import DlcCache
from core.dlc_manifest_installer import DlcManifestInstaller
from core.dlc_registry import DlcRegistry
from core.tasks.process_zip_task import ProcessZipTask
from utils.helpers import get_base_path

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
    dlc_statuses: list[dict[str, Any]] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return bool(self.appid and self.lua_files and self.manifests)


class ContentManager:
    """Preview and registry helpers for Ryuu/ZIP content packages."""

    def __init__(self, base_path: Path | None = None):
        self.base_path = Path(base_path or get_base_path())
        self.registry_path = self.base_path / "content_registry.json"
        self.dlc_registry = DlcRegistry(self.base_path / "dlc_registry.json")
        self.dlc_installer = DlcManifestInstaller(self.dlc_registry)
        self.dlc_cache = DlcCache(self.base_path / "dlc_cache")

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
        discovered_base_appid, discovered_dlcs = discover_dlc_package(path)
        if discovered_base_appid:
            game_data["appid"] = game_data.get("appid") or discovered_base_appid
        if discovered_dlcs:
            dlcs = sorted(
                set(dlcs) | {candidate.appid for candidate in discovered_dlcs},
                key=int,
            )

        return ContentPackagePreview(
            zip_path=str(path),
            filename=path.name,
            appid=str(game_data.get("appid") or ""),
            game_name=str(game_data.get("game_name") or f"App_{game_data.get('appid', '')}"),
            depots=depots,
            dlcs=dlcs,
            manifests=sorted(Path(item).name for item in manifest_files),
            lua_files=sorted(Path(item).name for item in lua_files),
            dlc_statuses=[candidate.to_dict() for candidate in discovered_dlcs],
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
        dlc_statuses: list[dict[str, Any]] | None = None,
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
            dlc_statuses=dlc_statuses or [],
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

    def prefetch_package(
        self,
        package_path: str | os.PathLike[str],
        *,
        source: str,
        free_dlcs: list[str] | None = None,
        owned_dlcs: list[str] | None = None,
        game_dir: str | os.PathLike[str] | None = None,
    ) -> dict[str, Any]:
        report = self.dlc_cache.cache_package(
            package_path,
            source=source,
            free_dlcs=free_dlcs or [],
            owned_dlcs=owned_dlcs or [],
        )
        self.dlc_registry.sync_discovery(
            str(report.get("base_appid") or ""),
            list(report.get("dlcs") or []),
            str(report.get("package_path") or ""),
        )
        if game_dir and report.get("base_appid"):
            root = Path(game_dir).expanduser().resolve()
            if root.is_dir():
                self.dlc_installer.write_game_info(
                    root,
                    str(report["base_appid"]),
                )
        payload = self.load_registry()
        prefetches = payload.setdefault("dlc_prefetch", [])
        prefetches.append(report)
        self.save_registry(payload)
        return report

    def cached_dlc_preview(
        self,
        *,
        appid: str,
        game_name: str,
    ) -> ContentPackagePreview | None:
        records = self.dlc_cache.list_game(appid)
        if not records:
            return None
        return ContentPackagePreview(
            zip_path="",
            filename="LumaTools DLC cache",
            appid=str(appid),
            game_name=game_name,
            depots=sorted(
                {
                    depot
                    for record in records
                    for depot in (record.get("depot_ids") or [])
                }
            ),
            dlcs=[str(record["appid"]) for record in records],
            manifests=sorted(
                {
                    item
                    for record in records
                    for item in (record.get("cached_manifests") or [])
                }
            ),
            lua_files=[],
            source="dlc_cache",
            dlc_statuses=records,
        )

    def activate_dlcs(
        self,
        preview: ContentPackagePreview,
        game_dir: str | os.PathLike[str],
        selected_dlcs: list[str],
        dlc_names: dict[str, str] | None = None,
        source: str = "local_zip",
    ) -> dict[str, Any]:
        """Install physical DLCs or record non-installable discovery states.

        Metadata-only and locked candidates are never written to ACF, depotcache,
        SLSsteam or wrapper metadata.
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
        raw_statuses = {
            str(item.get("appid")): item
            for item in preview.dlc_statuses
            if isinstance(item, dict) and str(item.get("appid", "")).isdigit()
        }
        candidates = {
            appid: DlcCandidate(
                **{
                    key: value
                    for key, value in item.items()
                    if key in DlcCandidate.__dataclass_fields__
                }
            )
            for appid, item in raw_statuses.items()
        }
        if preview.zip_path and Path(preview.zip_path).is_file():
            _, discovered = discover_dlc_package(
                preview.zip_path,
                source=source,
            )
            candidates.update({candidate.appid: candidate for candidate in discovered})
        if not preview.zip_path:
            candidates.update(
                {
                    str(item["appid"]): DlcCandidate(
                        **{
                            key: value
                            for key, value in item.items()
                            if key in DlcCandidate.__dataclass_fields__
                        }
                    )
                    for item in self.dlc_cache.list_game(str(preview.appid))
                    if str(item.get("appid", "")).isdigit()
                }
            )

        steam_root = self._steam_library_for_game(root)
        results: list[dict[str, Any]] = []
        for dlc_id in selected:
            dlc_name = names.get(str(dlc_id), f"DLC {dlc_id}")
            candidate = candidates.get(dlc_id)
            if candidate is None:
                candidate = DlcCandidate(
                    appid=dlc_id,
                    name=dlc_name,
                    base_appid=str(preview.appid),
                    source=source,
                    status="metadata_only",
                    entitlement="metadata_only",
                    failed_reason="physical_content_not_available",
                )
            candidate.name = dlc_name or candidate.name
            candidate.base_appid = candidate.base_appid or str(preview.appid)
            if candidate.status == "cached_installable":
                try:
                    results.append(
                        self.dlc_installer.install_cached(
                            candidate,
                            cache_path=str(
                                raw_statuses.get(candidate.appid, {}).get("cache_path")
                                or candidate.provenance.get("cache_path")
                                or ""
                            ),
                            game_dir=root,
                            steam_root=steam_root,
                        )
                    )
                except Exception as exc:
                    failed = candidate.to_dict()
                    failed.update(status="failed", failed_reason=str(exc))
                    results.append(failed)
                continue
            if candidate.installable and preview.zip_path:
                try:
                    results.append(
                        self.dlc_installer.install(
                            candidate,
                            package_path=preview.zip_path,
                            game_dir=root,
                            steam_root=steam_root,
                        )
                    )
                except Exception as exc:
                    failed = candidate.to_dict()
                    failed.update(status="failed", failed_reason=str(exc))
                    results.append(failed)
                continue

            record = candidate.to_dict()
            if record["status"] not in {"locked", "failed"}:
                record["status"] = "metadata_only"
            reason = (
                candidate.failed_reason
                or (
                    "local_files_not_found"
                    if candidate.manifest_found and candidate.depot_key_found
                    else ""
                )
                or "package_not_downloaded"
            )
            record.update(
                {
                    "name": dlc_name,
                    "failed_reason": reason,
                    "reason": reason,
                    "files_installed": False,
                    "acf_registered": False,
                    "slssteam_registered": False,
                }
            )
            self.dlc_registry.update(str(preview.appid), record)
            results.append(record)

        self.dlc_installer.write_game_info(root, str(preview.appid))
        installed = [item for item in results if item.get("status") == "installed"]
        metadata_only = [
            item for item in results if item.get("status") == "metadata_only"
        ]
        locked = [item for item in results if item.get("status") == "locked"]
        failed = [item for item in results if item.get("status") == "failed"]
        info = {
            "game_name": preview.game_name,
            "appid": str(preview.appid),
            "game_dir": str(root),
            "source": source,
            "package": preview.filename,
            "package_path": preview.zip_path,
            "dlcs": results,
            "installed": len(installed),
            "metadata_only": len(metadata_only),
            "locked": len(locked),
            "failed": len(failed),
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

        payload = self.load_registry()
        activations = payload.setdefault("dlc_activations", [])
        activations.append(info)
        self.save_registry(payload)
        logger.info(
            "Processed %s DLC(s) for %s: installed=%s metadata_only=%s locked=%s failed=%s",
            len(results),
            preview.game_name,
            len(installed),
            len(metadata_only),
            len(locked),
            len(failed),
        )
        return info

    @staticmethod
    def _steam_library_for_game(game_dir: Path) -> Path:
        if (
            game_dir.parent.name == "common"
            and game_dir.parent.parent.name == "steamapps"
        ):
            return game_dir.parent.parent.parent
        raise ValueError("Pasta do jogo nao pertence a uma biblioteca Steam reconhecida.")

    def repair_dlc(
        self,
        *,
        base_appid: str,
        dlc_appid: str,
        game_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        root = Path(game_dir).expanduser().resolve()
        return self.dlc_installer.repair(
            base_appid=base_appid,
            dlc_appid=dlc_appid,
            game_dir=root,
            steam_root=self._steam_library_for_game(root),
        )

    def uninstall_dlc(
        self,
        *,
        base_appid: str,
        dlc_appid: str,
        game_dir: str | os.PathLike[str],
    ) -> dict[str, Any]:
        root = Path(game_dir).expanduser().resolve()
        return self.dlc_installer.uninstall(
            base_appid=base_appid,
            dlc_appid=dlc_appid,
            game_dir=root,
            steam_root=self._steam_library_for_game(root),
        )
