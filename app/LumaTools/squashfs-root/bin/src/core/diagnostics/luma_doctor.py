from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MANAGED_MARKERS = {
    ".LumaTools",
    ".DepotDownloader",
    "LUMA_ONLINE_FIX_INFO.txt",
    "LUMA_FIX_STACK.json",
    "LUMA_RYUU_FIX_INFO.txt",
    "LUMA_DLC_CONTENT_INFO.json",
}


def _parse_acf_value(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*"([^"]*)"', content)
    return match.group(1) if match else ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _is_managed_game(game_dir: Path) -> bool:
    return game_dir.is_dir() and any((game_dir / marker).exists() for marker in MANAGED_MARKERS)


def inspect_appmanifest(acf_path: str | os.PathLike[str]) -> dict[str, Any]:
    acf = Path(acf_path)
    content = _read_text(acf)
    steamapps = acf.parent
    library = steamapps.parent
    installdir = _parse_acf_value(content, "installdir")
    appid = _parse_acf_value(content, "appid") or acf.stem.replace("appmanifest_", "", 1)
    game_dir = steamapps / "common" / installdir if installdir else Path("")

    fields = {
        key: _parse_acf_value(content, key)
        for key in (
            "appid",
            "name",
            "StateFlags",
            "installdir",
            "LastOwner",
            "buildid",
            "UpdateResult",
            "BytesToDownload",
            "BytesDownloaded",
            "BytesToStage",
            "BytesStaged",
            "TargetBuildID",
            "ScheduledAutoUpdate",
        )
    }

    issues: list[str] = []
    if fields["StateFlags"] != "4":
        issues.append("stateflags_not_installed")
    for key in ("BytesToDownload", "BytesToStage", "TargetBuildID", "ScheduledAutoUpdate"):
        if fields.get(key) not in ("", "0"):
            issues.append(f"{key.lower()}_nonzero")
    if installdir and not game_dir.exists():
        issues.append("installdir_missing")
    if not fields.get("LastOwner") or fields.get("LastOwner") == "0":
        issues.append("lastowner_missing_or_zero")
    decryption_key_log = ""
    try:
        from utils.steam_manifest import detect_recent_decryption_key_issue

        decryption_key_log = detect_recent_decryption_key_issue(library, appid)
    except Exception:
        decryption_key_log = ""
    if decryption_key_log:
        issues.append("missing_decryption_key")

    return {
        "appid": str(appid),
        "acf_path": str(acf),
        "library": str(library),
        "game_dir": str(game_dir) if installdir else "",
        "managed_by_lumatools": _is_managed_game(game_dir) if installdir else False,
        "online_fix_marker": bool(installdir and (game_dir / "LUMA_ONLINE_FIX_INFO.txt").exists()),
        "dlc_marker": bool(installdir and (game_dir / "LUMA_DLC_CONTENT_INFO.json").exists()),
        "fields": fields,
        "issues": issues,
        "decryption_key_log": decryption_key_log,
    }


def _iter_appmanifests(library_paths: Iterable[str | os.PathLike[str]]) -> list[Path]:
    manifests: list[Path] = []
    seen: set[str] = set()
    for library_path in library_paths:
        steamapps = Path(library_path).expanduser() / "steamapps"
        if not steamapps.is_dir():
            continue
        for acf in steamapps.glob("appmanifest_*.acf"):
            key = str(acf.resolve())
            if key not in seen:
                seen.add(key)
                manifests.append(acf)
    return sorted(manifests)


def _find_launch_options(steam_root: str | os.PathLike[str] | None, appid: str) -> dict[str, str]:
    if not steam_root:
        return {}
    root = Path(steam_root)
    found: dict[str, str] = {}
    pattern = re.compile(
        rf'"{re.escape(str(appid))}"\s*\{{(?P<body>.*?)\n\s*\}}',
        re.DOTALL,
    )
    launch_pattern = re.compile(r'"LaunchOptions"\s*"((?:\\.|[^"\\])*)"')
    for config in root.glob("userdata/*/config/localconfig.vdf"):
        text = _read_text(config)
        app_match = pattern.search(text)
        if not app_match:
            continue
        launch_match = launch_pattern.search(app_match.group("body"))
        if launch_match:
            found[config.parts[-3]] = launch_match.group(1)
    return found


def _running_steam_processes() -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    proc = Path("/proc")
    if not proc.is_dir():
        return processes
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit():
            continue
        cmdline = ""
        try:
            cmdline = (pid_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode(
                "utf-8", errors="ignore"
            )
        except OSError:
            continue
        if "steam" not in cmdline.lower():
            continue
        maps_text = _read_text(pid_dir / "maps")
        processes.append(
            {
                "pid": int(pid_dir.name),
                "cmdline": cmdline.strip(),
                "slssteam_loaded": "SLSsteam.so" in maps_text,
                "library_inject_loaded": "library-inject.so" in maps_text,
            }
        )
    return processes


def run_doctor(
    appid: str | int | None = None,
    *,
    steam_root: str | os.PathLike[str] | None = None,
    library_paths: Iterable[str | os.PathLike[str]] | None = None,
) -> dict[str, Any]:
    """Collect a non-mutating diagnostic report for Steam/Luma state."""
    report: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "steam_mode": "",
        "steam_root": str(steam_root or ""),
        "libraries": [str(path) for path in (library_paths or [])],
        "slssteam_config": "",
        "slssteam_paths": {},
        "running_steam_processes": [],
        "apps": [],
        "summary": {"ok": True, "issues": []},
    }

    try:
        from core import steam_helpers
        from core.linux_paths import detect_linux_steam_mode, find_slssteam_paths
        from utils.yaml_config_manager import get_user_config_path

        if sys.platform == "linux":
            mode = detect_linux_steam_mode()
            report["steam_mode"] = mode
            slssteam_path, inject_path = find_slssteam_paths(mode)
            report["slssteam_paths"] = {
                "SLSsteam.so": slssteam_path or "",
                "library-inject.so": inject_path or "",
            }
            report["slssteam_config"] = str(get_user_config_path())
            report["running_steam_processes"] = _running_steam_processes()

        if not steam_root:
            steam_root = steam_helpers.find_steam_install()
            report["steam_root"] = str(steam_root or "")
        if not library_paths:
            library_paths = steam_helpers.get_steam_libraries()
            report["libraries"] = [str(path) for path in (library_paths or [])]
    except Exception as exc:
        report["summary"]["ok"] = False
        report["summary"]["issues"].append(f"steam_detection_failed:{exc}")

    appid_text = str(appid).strip() if appid is not None else ""
    manifests = _iter_appmanifests(library_paths or [])
    for manifest in manifests:
        app_report = inspect_appmanifest(manifest)
        if appid_text and app_report["appid"] != appid_text:
            continue
        if steam_root:
            app_report["launch_options_by_user"] = _find_launch_options(
                steam_root, app_report["appid"]
            )
            if app_report["online_fix_marker"] and not app_report["launch_options_by_user"]:
                app_report["issues"].append("onlinefix_launch_options_missing")
        report["apps"].append(app_report)

    if appid_text and not report["apps"]:
        report["summary"]["ok"] = False
        report["summary"]["issues"].append(f"appmanifest_missing:{appid_text}")

    for app in report["apps"]:
        if app["managed_by_lumatools"] and app["issues"]:
            report["summary"]["ok"] = False
            report["summary"]["issues"].append(
                f"{app['appid']}:{','.join(app['issues'])}"
            )

    return report


def render_human_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Luma Doctor - {report.get('created_at', '')}",
        f"Steam mode: {report.get('steam_mode') or 'unknown'}",
        f"Steam root: {report.get('steam_root') or 'not found'}",
        f"Libraries: {len(report.get('libraries') or [])}",
        f"SLSsteam config: {report.get('slssteam_config') or 'unknown'}",
        "",
    ]
    apps = report.get("apps") or []
    if not apps:
        lines.append("No appmanifest inspected.")
    for app in apps:
        status = "OK" if not app.get("issues") else "ISSUES"
        lines.append(
            f"{status} {app.get('appid')} - {app.get('fields', {}).get('name') or app.get('game_dir')}"
        )
        for issue in app.get("issues") or []:
            lines.append(f"  - {issue}")
    summary = report.get("summary") or {}
    if not summary.get("ok"):
        lines.append("")
        lines.append("Summary issues:")
        for issue in summary.get("issues") or []:
            lines.append(f"  - {issue}")
    return "\n".join(lines)


def main() -> int:
    appid = sys.argv[1] if len(sys.argv) > 1 else None
    report = run_doctor(appid)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_human_summary(report))
    return 0 if report.get("summary", {}).get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
