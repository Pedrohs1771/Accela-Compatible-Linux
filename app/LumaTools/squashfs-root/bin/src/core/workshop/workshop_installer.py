from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.workshop.workshop_profiles import WorkshopProfile, resolve_workshop_profile


INSTALL_MANIFEST = "install_manifest.json"


class WorkshopInstaller:
    def install(
        self,
        *,
        appid: str,
        workshop_id: str,
        source: str | Path,
        game_dir: str | Path,
        title: str = "",
    ) -> dict[str, Any]:
        source_path = Path(source).expanduser().resolve()
        if not source_path.is_dir():
            raise FileNotFoundError(f"Workshop item nao encontrado: {source_path}")
        profile = resolve_workshop_profile(game_dir)
        target_root = Path(profile.target_root)
        target = target_root / str(workshop_id)
        target_root.mkdir(parents=True, exist_ok=True)

        job_root = Path(tempfile.mkdtemp(prefix=f"lumatools-workshop-{workshop_id}-"))
        stage = job_root / "stage"
        backup = job_root / "backup"
        try:
            shutil.copytree(source_path, stage)
            files = sorted(
                item.relative_to(stage).as_posix()
                for item in stage.rglob("*")
                if item.is_file()
            )
            if not files:
                raise RuntimeError("workshop_item_empty")
            if target.exists():
                shutil.move(str(target), str(backup))
            try:
                shutil.move(str(stage), str(target))
                record = self._record(
                    appid=appid,
                    workshop_id=workshop_id,
                    title=title,
                    source_path=source_path,
                    target=target,
                    profile=profile,
                    files=files,
                    enabled=True,
                )
                self._write_manifest(target, record)
                return record
            except Exception:
                shutil.rmtree(target, ignore_errors=True)
                if backup.exists():
                    shutil.move(str(backup), str(target))
                raise
        finally:
            shutil.rmtree(job_root, ignore_errors=True)

    def set_enabled(self, record: dict[str, Any], enabled: bool) -> dict[str, Any]:
        active = Path(record["installed_path"]).expanduser().resolve()
        disabled = Path(
            record.get("disabled_path")
            or active.parent / ".lumatools-disabled" / active.name
        ).expanduser().resolve()
        if enabled:
            if not disabled.exists():
                if active.exists():
                    record["enabled"] = True
                    return record
                raise FileNotFoundError("workshop_disabled_content_missing")
            active.parent.mkdir(parents=True, exist_ok=True)
            if active.exists():
                raise FileExistsError("workshop_active_target_exists")
            shutil.move(str(disabled), str(active))
        else:
            if not active.exists():
                if disabled.exists():
                    record["enabled"] = False
                    return record
                raise FileNotFoundError("workshop_installed_content_missing")
            disabled.parent.mkdir(parents=True, exist_ok=True)
            if disabled.exists():
                shutil.rmtree(disabled)
            shutil.move(str(active), str(disabled))
        record["enabled"] = bool(enabled)
        record["disabled_path"] = str(disabled)
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        manifest_root = active if enabled else disabled
        self._write_manifest(manifest_root, record)
        return record

    def uninstall(self, record: dict[str, Any]) -> dict[str, Any]:
        root = self._current_root(record)
        if not root.exists():
            record["status"] = "removed"
            record["enabled"] = False
            return record
        manifest = self._load_manifest(root)
        registered_files = set(manifest.get("files") or [])
        for relative in registered_files | {INSTALL_MANIFEST}:
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                continue
            if target.is_file():
                target.unlink()
        for directory in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if directory.exists() and not any(directory.iterdir()):
                directory.rmdir()
        if root.exists() and not any(root.iterdir()):
            root.rmdir()
        record["status"] = "removed"
        record["enabled"] = False
        record["removed_at"] = datetime.now(timezone.utc).isoformat()
        return record

    def repair(self, record: dict[str, Any]) -> dict[str, Any]:
        root = self._current_root(record)
        if not root.is_dir():
            return {"ok": False, "issues": ["installed_path_missing"]}
        manifest = self._load_manifest(root)
        missing = [
            relative
            for relative in manifest.get("files") or []
            if not (root / relative).is_file()
        ]
        issues = [f"missing:{item}" for item in missing]
        if str(manifest.get("workshop_id")) != str(record.get("workshop_id")):
            issues.append("manifest_item_mismatch")
        return {"ok": not issues, "issues": issues}

    @staticmethod
    def _current_root(record: dict[str, Any]) -> Path:
        if record.get("enabled", True):
            return Path(record["installed_path"]).expanduser().resolve()
        return Path(record["disabled_path"]).expanduser().resolve()

    @staticmethod
    def _record(
        *,
        appid: str,
        workshop_id: str,
        title: str,
        source_path: Path,
        target: Path,
        profile: WorkshopProfile,
        files: list[str],
        enabled: bool,
    ) -> dict[str, Any]:
        return {
            "appid": str(appid),
            "workshop_id": str(workshop_id),
            "title": title or f"Workshop {workshop_id}",
            "source": "steamcmd",
            "download_path": str(source_path),
            "installed_path": str(target),
            "disabled_path": str(target.parent / ".lumatools-disabled" / target.name),
            "profile": profile.to_dict(),
            "files": files,
            "enabled": enabled,
            "status": "installed",
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _write_manifest(root: Path, record: dict[str, Any]) -> None:
        root.mkdir(parents=True, exist_ok=True)
        target = root / INSTALL_MANIFEST
        temp = target.with_suffix(".tmp")
        temp.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, target)

    @staticmethod
    def _load_manifest(root: Path) -> dict[str, Any]:
        path = root / INSTALL_MANIFEST
        if not path.is_file():
            raise FileNotFoundError("workshop_install_manifest_missing")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("workshop_install_manifest_invalid")
        return payload
