import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


@dataclass
class ManifestCacheResult:
    expected: int = 0
    available: int = 0
    copied: int = 0
    recovered_from_zip: int = 0
    missing: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_extract(archive: zipfile.ZipFile, member: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with archive.open(member) as source, temp_path.open("wb") as output:
            shutil.copyfileobj(source, output)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def cache_depot_manifests(
    library_path: str,
    manifests: Dict[str, Any],
    *,
    selected_depots: Optional[Iterable[Any]] = None,
    source_dir: Optional[str] = None,
    source_zip: Optional[str] = None,
) -> ManifestCacheResult:
    result = ManifestCacheResult()
    selected = (
        [str(depot_id) for depot_id in selected_depots]
        if selected_depots is not None
        else [str(depot_id) for depot_id in manifests]
    )
    expected = {
        depot_id: str(manifests[depot_id])
        for depot_id in selected
        if depot_id in manifests
    }
    result.expected = len(expected)
    if not expected:
        return result

    cache_dir = Path(library_path) / "steamapps" / "depotcache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    source_root = Path(source_dir) if source_dir else None

    archive = None
    archive_members: dict[str, str] = {}
    archive_path = Path(source_zip) if source_zip else None
    if archive_path and archive_path.is_file():
        try:
            archive = zipfile.ZipFile(archive_path, "r")
            archive_members = {
                Path(member).name: member
                for member in archive.namelist()
                if member.lower().endswith(".manifest")
            }
        except (OSError, zipfile.BadZipFile):
            archive = None

    try:
        for depot_id, manifest_id in expected.items():
            if not depot_id.isdigit() or not manifest_id.isdigit():
                continue
            filename = f"{depot_id}_{manifest_id}.manifest"
            target = cache_dir / filename
            if target.is_file() and target.stat().st_size > 0:
                result.available += 1
                continue

            source = source_root / filename if source_root else None
            if source and source.is_file() and source.stat().st_size > 0:
                _atomic_copy(source, target)
                source.unlink(missing_ok=True)
                result.copied += 1
                continue

            member = archive_members.get(filename)
            if archive and member:
                _atomic_extract(archive, member, target)
                result.recovered_from_zip += 1
                continue

            result.missing.append(filename)
    finally:
        if archive is not None:
            archive.close()

    if source_root and source_root.is_dir():
        try:
            source_root.rmdir()
        except OSError:
            pass
    return result
