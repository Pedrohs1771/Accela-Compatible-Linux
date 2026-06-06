from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from core.dlc_discovery import DlcCandidate
from core.dlc_registry import DlcRegistry
from utils.wrapper_metadata import load_selected_dlcs, persist_selected_dlcs


class DlcInstallError(RuntimeError):
    pass


def _replace_acf_field(content: str, key: str, value: str) -> str:
    pattern = rf'("{re.escape(key)}"\s*)"[^"]*"'
    if re.search(pattern, content):
        return re.sub(pattern, rf'\g<1>"{value}"', content, count=1)
    position = content.rfind("}")
    if position < 0:
        raise DlcInstallError("appmanifest_invalid")
    return content[:position] + f'\t"{key}"\t\t"{value}"\n' + content[position:]


def _find_block(content: str, key: str) -> tuple[int, int]:
    match = re.search(rf'"{re.escape(key)}"\s*\{{', content)
    if not match:
        raise DlcInstallError(f"{key.lower()}_missing")
    open_brace = content.find("{", match.start())
    depth = 0
    for index in range(open_brace, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return open_brace, index
    raise DlcInstallError(f"{key.lower()}_invalid")


def register_installed_depots(
    acf_path: str | Path,
    depots: dict[str, dict[str, Any]],
    size_on_disk: int,
) -> None:
    path = Path(acf_path)
    content = path.read_text(encoding="utf-8", errors="ignore")
    block_start, block_end = _find_block(content, "InstalledDepots")
    body = content[block_start + 1 : block_end]

    for depot_id, data in depots.items():
        entry = (
            f'\n\t\t"{depot_id}"\n'
            "\t\t{\n"
            f'\t\t\t"manifest"\t\t"{data["manifest"]}"\n'
            f'\t\t\t"size"\t\t"{data.get("size", 0)}"\n'
            "\t\t}\n"
        )
        existing = re.search(
            rf'\s*"{re.escape(str(depot_id))}"\s*\{{.*?\n\s*\}}',
            body,
            re.S,
        )
        if existing:
            body = body[: existing.start()] + entry + body[existing.end() :]
        else:
            body += entry

    content = content[: block_start + 1] + body + content[block_end:]
    content = _replace_acf_field(content, "SizeOnDisk", str(size_on_disk))
    content = _replace_acf_field(content, "StateFlags", "4")
    content = _replace_acf_field(content, "BytesToDownload", "0")
    content = _replace_acf_field(content, "TargetBuildID", "0")

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def remove_installed_depots(
    acf_path: str | Path,
    depot_ids: list[str],
    size_on_disk: int,
) -> None:
    path = Path(acf_path)
    content = path.read_text(encoding="utf-8", errors="ignore")
    block_start, block_end = _find_block(content, "InstalledDepots")
    body = content[block_start + 1 : block_end]
    for depot_id in depot_ids:
        body = re.sub(
            rf'\s*"{re.escape(str(depot_id))}"\s*\{{.*?\n\s*\}}',
            "",
            body,
            flags=re.S,
        )
    content = content[: block_start + 1] + body + content[block_end:]
    content = _replace_acf_field(content, "SizeOnDisk", str(size_on_disk))

    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class DlcManifestInstaller:
    """Install authorized physical DLC content with rollback."""

    def __init__(self, registry: DlcRegistry | None = None):
        self.registry = registry or DlcRegistry()

    def install(
        self,
        candidate: DlcCandidate,
        *,
        package_path: str | Path,
        game_dir: str | Path,
        steam_root: str | Path,
        downloader: Callable[[DlcCandidate, Path], dict[str, Any]] | None = None,
        slssteam_enabled: bool = True,
    ) -> dict[str, Any]:
        if not candidate.installable:
            raise DlcInstallError(candidate.failed_reason or "dlc_not_installable")

        archive = Path(package_path).expanduser().resolve()
        root = Path(game_dir).expanduser().resolve()
        steam = Path(steam_root).expanduser().resolve()
        acf_path = steam / "steamapps" / f"appmanifest_{candidate.base_appid}.acf"
        if not root.exists() or not acf_path.exists():
            raise DlcInstallError("base_game_not_installed")

        job_root = Path(tempfile.mkdtemp(prefix=f"lumatools-dlc-{candidate.appid}-"))
        stage = job_root / "stage"
        backup = job_root / "backup"
        stage.mkdir()
        backup.mkdir()
        installed_files: list[str] = []
        created_files: list[Path] = []
        replaced_files: list[tuple[Path, Path]] = []
        persistent_replacements: list[dict[str, str]] = []
        created_manifests: list[Path] = []
        replaced_manifests: list[tuple[Path, Path]] = []
        downloader_manifests: dict[str, Path] = {}
        persistent_backup_root = (
            root
            / ".lumatools"
            / "dlc_backups"
            / candidate.appid
            / datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        )
        config_path: Path | None = None
        config_existed = False
        config_backup: bytes | None = None
        if slssteam_enabled:
            from utils.yaml_config_manager import get_user_config_path

            config_path = get_user_config_path()
            config_existed = config_path.exists()
            config_backup = config_path.read_bytes() if config_existed else None
        acf_backup = job_root / acf_path.name
        shutil.copy2(acf_path, acf_backup)

        try:
            if candidate.entitlement == "local_package_authorized":
                self._extract_local_content(archive, candidate, stage)
            elif downloader is not None:
                result = downloader(candidate, stage)
                if not result.get("ok"):
                    raise DlcInstallError(str(result.get("failed_reason") or "failed_download"))
                downloader_manifests = {
                    str(depot_id): Path(manifest_path)
                    for depot_id, manifest_path in (result.get("manifests") or {}).items()
                }
            else:
                raise DlcInstallError("entitled_download_provider_missing")

            for source in sorted(stage.rglob("*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(stage)
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    backup_path = backup / relative
                    backup_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, backup_path)
                    replaced_files.append((target, backup_path))
                    persistent_backup = persistent_backup_root / relative
                    persistent_backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(target, persistent_backup)
                    persistent_replacements.append(
                        {
                            "path": relative.as_posix(),
                            "backup_path": str(persistent_backup),
                        }
                    )
                else:
                    created_files.append(target)
                shutil.copy2(source, target)
                installed_files.append(relative.as_posix())

            depot_records: dict[str, dict[str, Any]] = {}
            with zipfile.ZipFile(archive, "r") as zip_ref:
                for depot_id, manifest_id in candidate.manifests.items():
                    manifest_name = candidate.manifest_files.get(depot_id)
                    target = steam / "depotcache" / f"{depot_id}_{manifest_id}.manifest"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists():
                        manifest_backup = backup / "depotcache" / target.name
                        manifest_backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, manifest_backup)
                        replaced_manifests.append((target, manifest_backup))
                    else:
                        created_manifests.append(target)
                    if manifest_name:
                        target.write_bytes(zip_ref.read(manifest_name))
                    else:
                        downloaded_manifest = downloader_manifests.get(depot_id)
                        if not downloaded_manifest or not downloaded_manifest.is_file():
                            raise DlcInstallError("missing_manifest")
                        shutil.copy2(downloaded_manifest, target)
                    depot_records[depot_id] = {
                        "manifest": manifest_id,
                        "size": sum(
                            (root / item).stat().st_size
                            for item in installed_files
                            if (root / item).exists()
                        ),
                    }

            total_size = sum(
                path.stat().st_size for path in root.rglob("*") if path.is_file()
            )
            register_installed_depots(acf_path, depot_records, total_size)

            slssteam_registered = False
            if slssteam_enabled:
                from utils.yaml_config_manager import (
                    add_additional_app,
                    add_dlc_data,
                    ensure_slssteam_config,
                )

                assert config_path is not None
                ensure_slssteam_config(config_path)
                add_additional_app(config_path, candidate.base_appid, "")
                add_additional_app(config_path, candidate.appid, candidate.name)
                add_dlc_data(
                    config_path,
                    candidate.base_appid,
                    candidate.appid,
                    candidate.name,
                )
                config_text = (
                    config_path.read_text(encoding="utf-8", errors="ignore")
                    if config_path.exists()
                    else ""
                )
                slssteam_registered = (
                    candidate.base_appid in config_text
                    and candidate.appid in config_text
                )

            selected_dlcs = load_selected_dlcs(root)
            if candidate.appid not in selected_dlcs:
                selected_dlcs.append(candidate.appid)
            persist_selected_dlcs(root, selected_dlcs)
            record = candidate.to_dict()
            record.update(
                {
                    "status": "verifying",
                    "installed_files": installed_files,
                    "replaced_files": persistent_replacements,
                    "files_installed": bool(installed_files),
                    "acf_registered": True,
                    "slssteam_registered": slssteam_registered,
                    "installed_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self.registry.update(candidate.base_appid, record)
            self.write_game_info(root, candidate.base_appid)
            from core.dlc_verifier import verify_dlc_install

            verification = verify_dlc_install(
                base_appid=candidate.base_appid,
                candidate=record,
                game_dir=root,
                steam_root=steam,
            )
            if not verification["ok"]:
                failed_checks = ",".join(
                    name for name, passed in verification["checks"].items() if not passed
                )
                raise DlcInstallError(f"verification_failed:{failed_checks}")
            record["status"] = "installed"
            record["verification"] = verification
            self.registry.update(candidate.base_appid, record)
            self.write_game_info(root, candidate.base_appid)
            final_verification = verify_dlc_install(
                base_appid=candidate.base_appid,
                candidate=record,
                game_dir=root,
                steam_root=steam,
            )
            if not final_verification["ok"]:
                raise DlcInstallError("final_verification_failed")
            record["verification"] = final_verification
            self.registry.update(candidate.base_appid, record)
            return record
        except Exception as exc:
            shutil.copy2(acf_backup, acf_path)
            for target in created_files:
                target.unlink(missing_ok=True)
            for target, backup_path in replaced_files:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
            for manifest in created_manifests:
                manifest.unlink(missing_ok=True)
            for target, manifest_backup in replaced_manifests:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_backup, target)
            if persistent_backup_root.exists():
                shutil.rmtree(persistent_backup_root, ignore_errors=True)
            selected = [
                item
                for item in load_selected_dlcs(root)
                if str(item) != str(candidate.appid)
            ]
            persist_selected_dlcs(root, selected)
            if config_path is not None and config_backup is not None:
                config_path.parent.mkdir(parents=True, exist_ok=True)
                config_path.write_bytes(config_backup)
            elif config_path is not None and not config_existed:
                config_path.unlink(missing_ok=True)
            failed = candidate.to_dict()
            failed.update(
                {
                    "status": "failed",
                    "failed_reason": str(exc),
                    "files_installed": False,
                    "acf_registered": False,
                    "slssteam_registered": False,
                }
            )
            self.registry.update(candidate.base_appid, failed)
            self.write_game_info(root, candidate.base_appid)
            raise
        finally:
            shutil.rmtree(job_root, ignore_errors=True)

    def install_cached(
        self,
        candidate: DlcCandidate,
        *,
        cache_path: str | Path,
        game_dir: str | Path,
        steam_root: str | Path,
        slssteam_enabled: bool = True,
    ) -> dict[str, Any]:
        cache = Path(cache_path).expanduser().resolve()
        files_dir = cache / "files"
        manifests_dir = cache / "manifests"
        if not files_dir.is_dir() or not manifests_dir.is_dir():
            raise DlcInstallError("dlc_cache_incomplete")
        temp_dir = Path(tempfile.mkdtemp(prefix=f"lumatools-cache-{candidate.appid}-"))
        package = temp_dir / "cached-dlc.zip"
        try:
            spec = {
                "schema": "lumatools.dlc.cache.v1",
                "base_appid": candidate.base_appid,
                "dlcs": [
                    {
                        "appid": candidate.appid,
                        "name": candidate.name,
                        "depots": candidate.depot_ids,
                        "manifests": candidate.manifests,
                        "content_roots": ["payload/dlc"],
                        "local_package_authorized": True,
                    }
                ],
            }
            with zipfile.ZipFile(package, "w") as zip_ref:
                zip_ref.writestr("lumatools_dlc.json", json.dumps(spec))
                for path in files_dir.rglob("*"):
                    if path.is_file():
                        zip_ref.write(path, f"payload/dlc/{path.relative_to(files_dir)}")
                for path in manifests_dir.glob("*.manifest"):
                    zip_ref.write(path, path.name)
            cached_candidate = DlcCandidate(
                **{
                    **{
                        field_name: getattr(candidate, field_name)
                        for field_name in DlcCandidate.__dataclass_fields__
                    },
                    "entitlement": "local_package_authorized",
                    "status": "installable",
                    "content_roots": ["payload/dlc"],
                    "manifest_files": {
                        depot_id: f"{depot_id}_{manifest_id}.manifest"
                        for depot_id, manifest_id in candidate.manifests.items()
                    },
                    "files_found": True,
                }
            )
            return self.install(
                cached_candidate,
                package_path=package,
                game_dir=game_dir,
                steam_root=steam_root,
                slssteam_enabled=slssteam_enabled,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _extract_local_content(
        archive: Path, candidate: DlcCandidate, stage: Path
    ) -> None:
        extracted = 0
        with zipfile.ZipFile(archive, "r") as zip_ref:
            for name in zip_ref.namelist():
                path = PurePosixPath(name)
                if path.is_absolute() or ".." in path.parts:
                    raise DlcInstallError("unsafe_package_path")
                for root in candidate.content_roots:
                    root_path = PurePosixPath(root)
                    try:
                        relative = path.relative_to(root_path)
                    except ValueError:
                        continue
                    if not relative.parts or name.endswith("/"):
                        break
                    target = stage.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(zip_ref.read(name))
                    extracted += 1
                    break
        if not extracted:
            raise DlcInstallError("package_content_missing")

    def repair(
        self,
        *,
        base_appid: str,
        dlc_appid: str,
        game_dir: str | Path,
        steam_root: str | Path,
    ) -> dict[str, Any]:
        root = Path(game_dir).expanduser().resolve()
        steam = Path(steam_root).expanduser().resolve()
        record = self.registry.get(base_appid, dlc_appid)
        if not record:
            raise DlcInstallError("dlc_not_registered")
        if not record.get("installed_files") or not all(
            (root / item).is_file() for item in record["installed_files"]
        ):
            raise DlcInstallError("registered_files_missing")

        archive = Path((record.get("provenance") or {}).get("archive", ""))
        manifests = record.get("manifests") or {}
        manifest_files = record.get("manifest_files") or {}
        if not manifests:
            raise DlcInstallError("missing_manifest")
        if not archive.is_file():
            raise DlcInstallError("package_backup_missing")

        restored: list[str] = []
        with zipfile.ZipFile(archive, "r") as zip_ref:
            for depot_id, manifest_id in manifests.items():
                target = steam / "depotcache" / f"{depot_id}_{manifest_id}.manifest"
                if target.exists():
                    continue
                source = manifest_files.get(depot_id)
                if not source:
                    raise DlcInstallError("manifest_not_recoverable")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zip_ref.read(source))
                restored.append(str(target))

        acf_path = steam / "steamapps" / f"appmanifest_{base_appid}.acf"
        total_size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        register_installed_depots(
            acf_path,
            {
                depot_id: {"manifest": manifest_id, "size": total_size}
                for depot_id, manifest_id in manifests.items()
            },
            total_size,
        )
        record["status"] = "installed"
        record["repaired_manifests"] = restored
        self.registry.update(base_appid, record)
        self.write_game_info(root, base_appid)
        from core.dlc_verifier import verify_dlc_install

        verification = verify_dlc_install(
            base_appid=base_appid,
            candidate=record,
            game_dir=root,
            steam_root=steam,
        )
        if not verification["ok"]:
            raise DlcInstallError("repair_verification_failed")
        record["verification"] = verification
        self.registry.update(base_appid, record)
        return record

    def uninstall(
        self,
        *,
        base_appid: str,
        dlc_appid: str,
        game_dir: str | Path,
        steam_root: str | Path,
    ) -> dict[str, Any]:
        root = Path(game_dir).expanduser().resolve()
        steam = Path(steam_root).expanduser().resolve()
        record = self.registry.get(base_appid, dlc_appid)
        if not record:
            raise DlcInstallError("dlc_not_registered")

        removed_files: list[str] = []
        restored_files: list[str] = []
        replacements = {
            str(item.get("path")): str(item.get("backup_path"))
            for item in (record.get("replaced_files") or [])
            if isinstance(item, dict)
        }
        for relative in record.get("installed_files") or []:
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise DlcInstallError("unsafe_registered_path") from exc
            backup_path = Path(replacements.get(str(relative), ""))
            if backup_path.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
                restored_files.append(relative)
            elif target.is_file():
                target.unlink()
                removed_files.append(relative)
                parent = target.parent
                while parent != root and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent

        removable_depots: list[str] = []
        for depot_id, manifest_id in (record.get("manifests") or {}).items():
            if self._manifest_used_elsewhere(
                base_appid, dlc_appid, depot_id, manifest_id
            ):
                continue
            removable_depots.append(str(depot_id))
            (steam / "depotcache" / f"{depot_id}_{manifest_id}.manifest").unlink(
                missing_ok=True
            )

        acf_path = steam / "steamapps" / f"appmanifest_{base_appid}.acf"
        total_size = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        remove_installed_depots(
            acf_path,
            removable_depots,
            total_size,
        )
        selected = [
            item for item in load_selected_dlcs(root) if str(item) != str(dlc_appid)
        ]
        persist_selected_dlcs(root, selected)
        record.update(
            {
                "status": "detected",
                "installed_files": [],
                "replaced_files": [],
                "files_installed": False,
                "acf_registered": False,
                "removed_files": removed_files,
                "restored_files": restored_files,
                "uninstalled_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        for backup in replacements.values():
            path = Path(backup)
            if not path.is_file():
                continue
            try:
                path.unlink()
                parent = path.parent
                while parent != root and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except OSError:
                pass
        self.registry.update(base_appid, record)
        self.write_game_info(root, base_appid)
        return record

    def _manifest_used_elsewhere(
        self,
        base_appid: str,
        dlc_appid: str,
        depot_id: str,
        manifest_id: str,
    ) -> bool:
        records = (
            self.registry.load()
            .get("games", {})
            .get(str(base_appid), {})
            .get("dlcs", {})
        )
        for other_appid, other in records.items():
            if str(other_appid) == str(dlc_appid):
                continue
            if other.get("status") != "installed":
                continue
            if str((other.get("manifests") or {}).get(str(depot_id))) == str(
                manifest_id
            ):
                return True
        return False

    def write_game_info(self, game_dir: Path, base_appid: str) -> None:
        records = (
            self.registry.load()
            .get("games", {})
            .get(str(base_appid), {})
            .get("dlcs", {})
        )
        payload = {
            "base_appid": str(base_appid),
            "dlcs": list(records.values()),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        (game_dir / "LUMA_DLC_CONTENT_INFO.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
