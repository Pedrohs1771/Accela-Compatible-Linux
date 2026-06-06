from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from core.dlc_cache import DlcCache
from core.dlc_verifier import diagnose_dlc_content
from core.workshop.workshop_installer import WorkshopInstaller


def run_content_doctor(
    *,
    appid: str,
    game_dir: str | Path,
    steam_root: str | Path,
    base_path: str | Path,
) -> dict[str, Any]:
    root = Path(game_dir).expanduser().resolve()
    base = Path(base_path).expanduser().resolve()
    cache = DlcCache(base / "dlc_cache")
    cached_dlcs = cache.list_game(str(appid))
    dlc_result = diagnose_dlc_content(
        base_appid=str(appid),
        game_dir=root,
        steam_root=steam_root,
    )

    workshop_results: list[dict[str, Any]] = []
    registry_path = base / "workshop_mods.json"
    try:
        records = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        records = []
    installer = WorkshopInstaller()
    for record in records if isinstance(records, list) else []:
        if str(record.get("appid")) != str(appid):
            continue
        try:
            verification = installer.repair(record)
        except Exception as exc:
            verification = {"ok": False, "issues": [str(exc)]}
        workshop_results.append(
            {
                "workshop_id": str(record.get("workshop_id", "")),
                "status": record.get("status", "unknown"),
                "enabled": bool(record.get("enabled")),
                "verification": verification,
            }
        )

    issues = list(dlc_result.get("issues", []))
    for record in cached_dlcs:
        if record.get("status") == "metadata_only":
            issues.append(
                f"{record.get('appid')}:cached_metadata_only:"
                f"{record.get('failed_reason', '')}"
            )
        elif record.get("status") == "locked":
            issues.append(f"{record.get('appid')}:cached_locked")
        elif record.get("status") == "failed":
            issues.append(f"{record.get('appid')}:cached_failed")
    for item in workshop_results:
        if not item["verification"].get("ok"):
            issues.append(f"workshop:{item['workshop_id']}:invalid")

    return {
        "appid": str(appid),
        "game_dir": str(root),
        "dlc": dlc_result,
        "dlc_cache": cached_dlcs,
        "workshop": workshop_results,
        "issues": issues,
        "ok": not issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("appid")
    parser.add_argument("--game-dir", required=True)
    parser.add_argument("--steam-root", required=True)
    parser.add_argument("--base-path", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_content_doctor(
        appid=args.appid,
        game_dir=args.game_dir,
        steam_root=args.steam_root,
        base_path=args.base_path,
    )
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("OK" if report["ok"] else "ISSUES")
        for issue in report["issues"]:
            print(f"- {issue}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
