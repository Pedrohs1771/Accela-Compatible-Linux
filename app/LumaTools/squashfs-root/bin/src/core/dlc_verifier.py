from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

def _installed_depot_present(acf_text: str, depot_id: str, manifest_id: str) -> bool:
    pattern = (
        rf'"{re.escape(str(depot_id))}"\s*\{{'
        rf'.*?"manifest"\s*"{re.escape(str(manifest_id))}"'
    )
    return bool(re.search(pattern, acf_text, re.S))


def verify_dlc_install(
    *,
    base_appid: str,
    candidate: dict[str, Any],
    game_dir: str | Path,
    steam_root: str | Path,
) -> dict[str, Any]:
    root = Path(game_dir)
    steam = Path(steam_root)
    info_path = root / "LUMA_DLC_CONTENT_INFO.json"
    acf_path = steam / "steamapps" / f"appmanifest_{base_appid}.acf"
    acf_text = acf_path.read_text(encoding="utf-8", errors="ignore") if acf_path.exists() else ""

    content_files = candidate.get("installed_files") or []
    files_ok = bool(content_files) and all((root / item).exists() for item in content_files)
    manifests = candidate.get("manifests") or {}
    depotcache_ok = bool(manifests) and all(
        (steam / "depotcache" / f"{depot}_{manifest}.manifest").exists()
        for depot, manifest in manifests.items()
    )
    acf_ok = bool(manifests) and all(
        _installed_depot_present(acf_text, depot, manifest)
        for depot, manifest in manifests.items()
    )
    metadata_ok = False
    if info_path.exists():
        try:
            payload = json.loads(info_path.read_text(encoding="utf-8"))
            metadata_ok = any(
                str(item.get("appid")) == str(candidate.get("appid"))
                and item.get("status") in {"verifying", "installed"}
                for item in payload.get("dlcs", [])
            )
        except (OSError, ValueError, TypeError):
            metadata_ok = False
    slssteam_ok = True
    if candidate.get("slssteam_registered"):
        from utils.yaml_config_manager import get_user_config_path

        config_path = get_user_config_path()
        config_text = (
            config_path.read_text(encoding="utf-8", errors="ignore")
            if config_path.exists()
            else ""
        )
        slssteam_ok = (
            str(base_appid) in config_text
            and str(candidate.get("appid")) in config_text
        )

    checks = {
        "files": files_ok,
        "depotcache": depotcache_ok,
        "acf_installed_depots": acf_ok,
        "metadata": metadata_ok,
        "slssteam": slssteam_ok,
    }
    return {"ok": all(checks.values()), "checks": checks}


def diagnose_dlc_content(
    *,
    base_appid: str,
    game_dir: str | Path,
    steam_root: str | Path,
) -> dict[str, Any]:
    root = Path(game_dir)
    info_path = root / "LUMA_DLC_CONTENT_INFO.json"
    if not info_path.exists():
        return {"ok": True, "dlcs": [], "issues": []}
    try:
        payload = json.loads(info_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"ok": False, "dlcs": [], "issues": ["dlc_metadata_invalid"]}

    results: list[dict[str, Any]] = []
    issues: list[str] = []
    for candidate in payload.get("dlcs", []):
        status = str(candidate.get("status") or "detected")
        if status == "installed":
            verification = verify_dlc_install(
                base_appid=base_appid,
                candidate=candidate,
                game_dir=root,
                steam_root=steam_root,
            )
            result = {**candidate, "verification": verification}
            if not verification["ok"]:
                issues.append(f"{candidate.get('appid')}:installed_content_invalid")
        else:
            result = {
                **candidate,
                "verification": {
                    "ok": False,
                    "checks": {
                        "files": False,
                        "depotcache": False,
                        "acf_installed_depots": False,
                        "metadata": True,
                    },
                },
            }
            if status == "metadata_only":
                issues.append(f"{candidate.get('appid')}:metadata_only_no_files")
            elif status == "locked":
                issues.append(f"{candidate.get('appid')}:locked")
            elif status == "failed":
                issues.append(
                    f"{candidate.get('appid')}:failed:{candidate.get('failed_reason', '')}"
                )
        results.append(result)
    return {"ok": not issues, "dlcs": results, "issues": issues}
