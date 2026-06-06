from __future__ import annotations

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from core.dlc_discovery import DlcCandidate, discover_dlc_package


class DlcCache:
    def __init__(self, root: str | Path | None = None):
        self.root = Path(
            root
            or (
                Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
                / "LumaTools"
                / "dlc_cache"
            )
        )

    def cache_package(
        self,
        package_path: str | Path,
        *,
        source: str,
        free_dlcs: Iterable[str] = (),
        owned_dlcs: Iterable[str] = (),
    ) -> dict[str, Any]:
        archive = Path(package_path).expanduser().resolve()
        base_appid, candidates = discover_dlc_package(
            archive,
            source=source,
            free_dlcs=free_dlcs,
            owned_dlcs=owned_dlcs,
        )
        report = {
            "base_appid": base_appid,
            "source": source,
            "package_path": str(archive),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
            "dlcs": [],
        }
        with zipfile.ZipFile(archive, "r") as zip_ref:
            for candidate in candidates:
                report["dlcs"].append(
                    self._cache_candidate(zip_ref, archive, candidate)
                )
        return report

    def _cache_candidate(
        self,
        zip_ref: zipfile.ZipFile,
        archive: Path,
        candidate: DlcCandidate,
    ) -> dict[str, Any]:
        target = self.root / candidate.base_appid / candidate.appid
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = Path(
            tempfile.mkdtemp(prefix=f".{candidate.appid}-", dir=str(target.parent))
        )
        try:
            manifests_dir = temp / "manifests"
            files_dir = temp / "files"
            manifests_dir.mkdir(parents=True)
            files_dir.mkdir(parents=True)
            copied_manifests: list[str] = []
            for depot_id, member in candidate.manifest_files.items():
                manifest_id = candidate.manifests.get(depot_id)
                if not manifest_id:
                    continue
                destination = manifests_dir / f"{depot_id}_{manifest_id}.manifest"
                destination.write_bytes(zip_ref.read(member))
                copied_manifests.append(destination.name)

            copied_files: list[str] = []
            if candidate.entitlement == "local_package_authorized":
                for member in zip_ref.namelist():
                    for content_root in candidate.content_roots:
                        prefix = content_root.rstrip("/") + "/"
                        if not member.startswith(prefix) or member.endswith("/"):
                            continue
                        relative = member[len(prefix) :]
                        if not relative or ".." in Path(relative).parts:
                            continue
                        destination = files_dir / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(zip_ref.read(member))
                        copied_files.append(relative)
                        break

            cache_status = (
                "cached_installable"
                if candidate.installable
                and bool(copied_manifests)
                and bool(copied_files)
                else candidate.status
            )
            if cache_status == "installable":
                cache_status = "metadata_only"
            payload = candidate.to_dict()
            payload.update(
                {
                    "status": cache_status,
                    "cache_path": str(target),
                    "cached_manifests": copied_manifests,
                    "cached_files": copied_files,
                    "source_package": str(archive),
                    "cached_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            (temp / "metadata.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (temp / "install_plan.json").write_text(
                json.dumps(
                    {
                        "base_appid": candidate.base_appid,
                        "dlc_appid": candidate.appid,
                        "depots": candidate.manifests,
                        "files": copied_files,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (temp / "status.json").write_text(
                json.dumps(
                    {
                        "status": cache_status,
                        "reason": candidate.failed_reason,
                        "missing_fields": candidate.missing_fields,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if target.exists():
                shutil.rmtree(target)
            os.replace(temp, target)
            return payload
        finally:
            if temp.exists():
                shutil.rmtree(temp, ignore_errors=True)

    def list_game(self, base_appid: str) -> list[dict[str, Any]]:
        game_root = self.root / str(base_appid)
        if not game_root.exists():
            return []
        results: list[dict[str, Any]] = []
        for metadata in sorted(game_root.glob("*/metadata.json")):
            try:
                payload = json.loads(metadata.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            if isinstance(payload, dict):
                results.append(payload)
        return results
