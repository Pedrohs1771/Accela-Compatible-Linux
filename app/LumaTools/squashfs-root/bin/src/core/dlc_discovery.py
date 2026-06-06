from __future__ import annotations

import json
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


INSTALLABLE_SOURCES = {
    "free_dlc",
    "owned_by_account",
    "local_package_authorized",
}


@dataclass
class DlcCandidate:
    appid: str
    name: str = ""
    base_appid: str = ""
    depot_ids: list[str] = field(default_factory=list)
    manifests: dict[str, str] = field(default_factory=dict)
    manifest_files: dict[str, str] = field(default_factory=dict)
    content_roots: list[str] = field(default_factory=list)
    source: str = "package"
    provenance: dict[str, Any] = field(default_factory=dict)
    entitlement: str = "metadata_only"
    status: str = "metadata_only"
    failed_reason: str = ""
    depot_key_found: bool = False
    manifest_found: bool = False
    files_found: bool = False
    token_found: bool = False
    missing_fields: list[str] = field(default_factory=list)

    @property
    def installable(self) -> bool:
        return (
            self.entitlement in INSTALLABLE_SOURCES
            and self.status in {"installable", "cached_installable"}
            and bool(self.manifests)
            and (self.files_found or self.entitlement in {"free_dlc", "owned_by_account"})
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["installable"] = self.installable
        payload["dlc_appid"] = self.appid
        payload["reason"] = self.failed_reason
        payload["manifest_file_found"] = bool(self.manifest_files)
        payload["depot_id_found"] = bool(self.depot_ids)
        payload["local_content_found"] = self.files_found
        return payload


def _safe_archive_path(value: str) -> bool:
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts


def _load_package_manifest(zip_ref: zipfile.ZipFile) -> dict[str, Any]:
    accepted = {
        "lumatools_dlc.json",
        "dlc_manifest.json",
        "luma_dlc_manifest.json",
    }
    for name in zip_ref.namelist():
        if PurePosixPath(name).name.lower() not in accepted:
            continue
        try:
            payload = json.loads(zip_ref.read(name).decode("utf-8"))
        except (ValueError, UnicodeError):
            return {}
        return payload if isinstance(payload, dict) else {}
    return {}


def _parse_lua(lua_content: str) -> dict[str, Any]:
    apps: dict[str, dict[str, Any]] = {}
    declarations: list[dict[str, Any]] = []
    tokens: dict[str, str] = {}
    manifests: dict[str, str] = {}

    for raw_line in lua_content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("--"):
            continue
        match = re.search(r"addappid\s*\((.*?)\)(.*)", raw_line, re.I)
        if not match:
            continue
        args = [item.strip() for item in match.group(1).split(",")]
        appid = args[0].strip("\"' ") if args else ""
        if not appid.isdigit():
            continue
        comment = re.search(r"--\s*(.*)", match.group(2))
        entry = apps.setdefault(appid, {})
        name = comment.group(1).strip() if comment else entry.get("name", f"App {appid}")
        entry["name"] = name
        depot_key = ""
        if len(args) > 2 and args[2].strip("\"' "):
            depot_key = args[2].strip("\"' ")
            entry["depot_key"] = depot_key
        declarations.append(
            {
                "appid": appid,
                "name": name,
                "depot_key": depot_key,
            }
        )

    for match in re.finditer(
        r'addtoken\s*\(\s*(\d+)\s*,\s*"([^"]+)"\s*\)', lua_content, re.I
    ):
        tokens[match.group(1)] = match.group(2)

    for match in re.finditer(
        r"setManifestid\s*\(\s*(\d+)\s*,\s*[\"']?(\d+)[\"']?", lua_content, re.I
    ):
        manifests[match.group(1)] = match.group(2)

    return {
        "apps": apps,
        "declarations": declarations,
        "tokens": tokens,
        "manifests": manifests,
    }


def _missing_fields(candidate: DlcCandidate) -> list[str]:
    missing: list[str] = []
    if not candidate.depot_ids:
        missing.append("depot_id")
    if not candidate.manifests:
        missing.append("manifest_id")
    if not candidate.manifest_files:
        missing.append("manifest_file")
    if (
        not candidate.files_found
        and (
            candidate.entitlement == "local_package_authorized"
            or candidate.failed_reason == "local_files_not_found"
        )
    ):
        missing.append("local_content")
    if candidate.entitlement == "metadata_only":
        missing.append("entitlement_or_local_content")
    return missing


def _group_dedicated_depots(parsed: dict[str, Any], base_appid: str) -> dict[str, list[str]]:
    """Map unkeyed DLC declarations to following keyed dedicated depots.

    HubCap-style Lua files commonly declare a DLC AppID without a depot key and
    then list that DLC's platform depots immediately after it. Keep assigning
    keyed depots to the current DLC until another unkeyed AppID starts a new
    group.
    """
    grouped: dict[str, list[str]] = {}
    current_dlc = ""
    for item in parsed.get("declarations", []):
        appid = str(item.get("appid", ""))
        if not appid or appid == str(base_appid):
            continue
        depot_key = str(item.get("depot_key", ""))
        if not depot_key:
            current_dlc = appid
            grouped.setdefault(current_dlc, [])
            continue
        if current_dlc and appid in parsed.get("manifests", {}):
            grouped.setdefault(current_dlc, []).append(appid)
    return grouped


def discover_dlc_package(
    zip_path: str | Path,
    *,
    free_dlcs: Iterable[str] = (),
    owned_dlcs: Iterable[str] = (),
    source: str = "local_zip",
) -> tuple[str, list[DlcCandidate]]:
    """Discover DLC without treating keys/tokens as proof of ownership.

    Physical local payloads require an explicit DLC manifest that maps the DLC
    AppID to depots and content roots. Steam downloads require a caller-provided
    free/owned entitlement result.
    """
    archive = Path(zip_path).expanduser().resolve()
    free = {str(item) for item in free_dlcs}
    owned = {str(item) for item in owned_dlcs}

    with zipfile.ZipFile(archive, "r") as zip_ref:
        names = [name for name in zip_ref.namelist() if _safe_archive_path(name)]
        lua_names = [name for name in names if name.lower().endswith(".lua")]
        lua_content = (
            zip_ref.read(lua_names[0]).decode("utf-8", errors="replace")
            if lua_names
            else ""
        )
        parsed = _parse_lua(lua_content)
        explicit = _load_package_manifest(zip_ref)

        base_appid = str(
            explicit.get("base_appid")
            or next(iter(parsed["apps"].keys()), "")
        )
        explicit_dlcs = explicit.get("dlcs") if isinstance(explicit.get("dlcs"), list) else []
        explicit_by_id = {
            str(item.get("appid")): item
            for item in explicit_dlcs
            if isinstance(item, dict) and str(item.get("appid", "")).isdigit()
        }

        unkeyed_appids = {
            item["appid"]
            for item in parsed["declarations"]
            if item["appid"] != base_appid and not item["depot_key"]
        }
        keyed_appids = {
            item["appid"]
            for item in parsed["declarations"]
            if item["depot_key"]
        }
        grouped_depots = _group_dedicated_depots(parsed, base_appid)
        candidate_ids = set(explicit_by_id) | unkeyed_appids

        archive_manifests: dict[str, tuple[str, str]] = {}
        for name in names:
            match = re.search(r"(?:^|/)(\d+)_(\d+)\.manifest$", name, re.I)
            if match:
                archive_manifests[match.group(1)] = (match.group(2), name)

        candidates: list[DlcCandidate] = []
        for appid in sorted(candidate_ids, key=int):
            spec = explicit_by_id.get(appid, {})
            depot_ids = [
                str(item)
                for item in spec.get("depots", [])
                if str(item).isdigit()
            ]
            if not depot_ids and appid in keyed_appids and appid in parsed["manifests"]:
                depot_ids = [appid]
            if not depot_ids:
                depot_ids = grouped_depots.get(appid, [])
            manifests: dict[str, str] = {}
            manifest_files: dict[str, str] = {}
            depot_key_found = False
            for depot_id in depot_ids:
                parsed_manifest = parsed["manifests"].get(depot_id)
                archive_manifest = archive_manifests.get(depot_id)
                manifest_id = str(
                    (spec.get("manifests") or {}).get(depot_id)
                    or parsed_manifest
                    or (archive_manifest[0] if archive_manifest else "")
                )
                if manifest_id:
                    manifests[depot_id] = manifest_id
                if archive_manifest and archive_manifest[0] == manifest_id:
                    manifest_files[depot_id] = archive_manifest[1]
                depot_key_found = depot_key_found or bool(
                    parsed["apps"].get(depot_id, {}).get("depot_key")
                )

            roots = [
                str(root).strip("/")
                for root in spec.get("content_roots", [])
                if str(root).strip("/") and _safe_archive_path(str(root))
            ]
            files_found = any(
                any(name == root or name.startswith(f"{root}/") for name in names)
                for root in roots
            )

            if bool(spec.get("encrypted")):
                entitlement = "locked_or_encrypted"
                status = "locked"
                reason = "content_encrypted"
            elif appid in free:
                entitlement = "free_dlc"
                status = "installable" if manifests and manifest_files else "metadata_only"
                reason = "" if manifests else "missing_manifest"
            elif appid in owned:
                entitlement = "owned_by_account"
                status = "installable" if manifests and manifest_files else "metadata_only"
                reason = "" if manifests else "missing_manifest"
            elif bool(spec.get("local_package_authorized")) and files_found:
                entitlement = "local_package_authorized"
                status = "installable" if manifests and manifest_files else "metadata_only"
                reason = "" if status == "installable" else "missing_manifest"
            else:
                entitlement = "metadata_only"
                status = "metadata_only"
                if bool(spec.get("local_package_authorized")) and not files_found:
                    reason = "local_files_not_found"
                elif not depot_ids:
                    reason = "parser_failed_to_map_dlc_to_depot"
                elif not manifests or not manifest_files:
                    reason = "manifest_not_found"
                else:
                    reason = "entitlement_not_confirmed"

            candidate = DlcCandidate(
                    appid=appid,
                    name=str(spec.get("name") or parsed["apps"].get(appid, {}).get("name") or f"DLC {appid}"),
                    base_appid=base_appid,
                    depot_ids=depot_ids,
                    manifests=manifests,
                    manifest_files=manifest_files,
                    content_roots=roots,
                    source=source,
                    provenance={
                        "archive": str(archive),
                        "manifest_schema": str(explicit.get("schema") or ""),
                    },
                    entitlement=entitlement,
                    status=status,
                    failed_reason=reason,
                    depot_key_found=depot_key_found,
                    manifest_found=bool(manifests),
                    files_found=files_found,
                    token_found=appid in parsed["tokens"],
                )
            candidate.missing_fields = _missing_fields(candidate)
            if candidate.status == "metadata_only":
                if candidate.failed_reason in {
                    "local_files_not_found",
                    "parser_failed_to_map_dlc_to_depot",
                    "manifest_not_found",
                }:
                    pass
                elif not candidate.depot_ids:
                    candidate.failed_reason = "no_dlc_depot_mapping"
                elif not candidate.manifest_files:
                    candidate.failed_reason = "manifest_without_local_content_or_entitlement"
                elif candidate.entitlement == "metadata_only":
                    candidate.failed_reason = (
                        "manifest_present_but_entitlement_or_local_content_missing"
                    )
            candidates.append(candidate)

    return base_appid, candidates
