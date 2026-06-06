from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path


APPID = "250900"
DLC_APPID = "3353470"
DLC_DEPOT = "3353471"
BASE_DEPOT = "250902"
INSTALL_DIR = "The Binding of Isaac Rebirth"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_lua(lua_text: str) -> tuple[dict[str, str], dict[str, str]]:
    keys: dict[str, str] = {}
    manifests: dict[str, str] = {}
    for match in re.finditer(
        r'addappid\s*\(\s*(\d+)\s*,\s*1\s*,\s*"([^"]+)"\s*\)',
        lua_text,
        re.I,
    ):
        keys[match.group(1)] = match.group(2)
    for match in re.finditer(
        r'setManifestid\s*\(\s*(\d+)\s*,\s*"(\d+)"',
        lua_text,
        re.I,
    ):
        manifests[match.group(1)] = match.group(2)
    return keys, manifests


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _write_keys(path: Path, keys: dict[str, str], depots: list[str]) -> None:
    path.write_text(
        "".join(f"{depot};{keys[depot]}\n" for depot in depots if depot in keys),
        encoding="utf-8",
    )


def _extract_manifest(zip_path: Path, depot: str, manifest: str, dest: Path) -> Path:
    member = f"{depot}_{manifest}.manifest"
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / member
    with zipfile.ZipFile(zip_path) as archive:
        out.write_bytes(archive.read(member))
    return out


def _run_depot_download(
    *,
    src: Path,
    appid: str,
    depot: str,
    manifest: str,
    manifest_file: Path,
    keys_file: Path,
    target_dir: Path,
) -> dict[str, object]:
    dotnet = shutil.which("dotnet") or "/usr/bin/dotnet"
    dll = src / "deps" / "DepotDownloader.dll"
    cmd = [
        dotnet,
        str(dll),
        "-app",
        appid,
        "-depot",
        depot,
        "-manifest",
        manifest,
        "-manifestfile",
        str(manifest_file),
        "-depotkeys",
        str(keys_file),
        "-max-downloads",
        "8",
        "-dir",
        str(target_dir),
        "-validate",
    ]
    started = time.time()
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        errors="replace",
        timeout=1800,
    )
    output = proc.stdout or ""
    return {
        "cmd": cmd,
        "return_code": proc.returncode,
        "elapsed_seconds": round(time.time() - started, 2),
        "output_tail": output.splitlines()[-80:],
        "total_downloaded_seen": "Total downloaded:" in output,
        "access_denied_seen": "Access denied" in output or "No subscription" in output,
    }


def main() -> int:
    src = Path("/home/pedrohs/.local/share/LumaTools/squashfs-root/bin/src")
    sys.path.insert(0, str(src))

    from core.dlc_discovery import DlcCandidate
    from core.dlc_discovery import discover_dlc_package
    from core.dlc_manifest_installer import DlcInstallError, DlcManifestInstaller
    from core.diagnostics.content_doctor import run_content_doctor
    from utils.steam_manifest import repair_installed_app_state, write_acf_file

    steam = Path("/home/pedrohs/.local/share/Steam")
    data_root = Path("/home/pedrohs/.local/share/LumaTools")
    zip_path = data_root / "hubcap_manifests" / "lumatools_fetch_250900.zip"
    qa_root = data_root / "qa" / "isaac-physical-dlc"
    if qa_root.exists():
        shutil.rmtree(qa_root)
    qa_root.mkdir(parents=True)

    report: dict[str, object] = {
        "status": "FAILED_BUG",
        "appid": APPID,
        "game": "The Binding of Isaac: Rebirth",
        "dlc_appid": DLC_APPID,
        "dlc_depot": DLC_DEPOT,
        "zip_path": str(zip_path),
        "zip_sha256": _sha256(zip_path),
        "steps": [],
    }

    lua_text = ""
    with zipfile.ZipFile(zip_path) as archive:
        lua_name = next(name for name in archive.namelist() if name.endswith(".lua"))
        lua_text = archive.read(lua_name).decode("utf-8", errors="replace")
    keys, manifests = _parse_lua(lua_text)
    report["manifest_ids"] = {
        "base": manifests.get(BASE_DEPOT),
        "dlc": manifests.get(DLC_DEPOT),
    }

    appmanifest = steam / "steamapps" / f"appmanifest_{APPID}.acf"
    game_dir = steam / "steamapps" / "common" / INSTALL_DIR
    existing = {
        "appmanifest_exists": appmanifest.exists(),
        "game_dir_exists": game_dir.exists(),
        "game_dir_size": _dir_size(game_dir),
    }
    report["existing_state"] = existing

    workspace = Path(tempfile.mkdtemp(prefix="luma-isaac-qa-", dir=str(qa_root)))
    manifest_dir = workspace / "manifests"
    keys_file = workspace / "keys.vdf"
    depotcache = steam / "depotcache"
    try:
        _write_keys(keys_file, keys, [BASE_DEPOT, DLC_DEPOT])
        base_manifest = _extract_manifest(
            zip_path, BASE_DEPOT, manifests[BASE_DEPOT], manifest_dir
        )
        dlc_manifest = _extract_manifest(
            zip_path, DLC_DEPOT, manifests[DLC_DEPOT], manifest_dir
        )

        base_result = _run_depot_download(
            src=src,
            appid=APPID,
            depot=BASE_DEPOT,
            manifest=manifests[BASE_DEPOT],
            manifest_file=base_manifest,
            keys_file=keys_file,
            target_dir=game_dir,
        )
        report["base_download"] = base_result
        if base_result["return_code"] != 0:
            report["status"] = "BLOCKED_NO_ENTITLEMENT"
            report["reason"] = "base_depot_download_failed"
            (qa_root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 2

        depotcache.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base_manifest, depotcache / base_manifest.name)
        game_data = {
            "appid": APPID,
            "game_name": "The Binding of Isaac: Rebirth",
            "installdir": INSTALL_DIR,
            "buildid": "0",
            "selected_depots_list": [BASE_DEPOT],
            "manifests": {BASE_DEPOT: manifests[BASE_DEPOT]},
            "depots": {BASE_DEPOT: {"size": str(_dir_size(game_dir)), "oslist": "windows"}},
        }
        write_acf_file(
            str(steam),
            game_data,
            _dir_size(game_dir),
            include_depots=True,
            log_proton=True,
        )
        repair_installed_app_state(str(steam), APPID)

        _, discovered = discover_dlc_package(
            zip_path,
            source="qa_isaac_physical_dlc",
            free_dlcs=[DLC_APPID],
        )
        dlc_payload = next(item.to_dict() for item in discovered if item.appid == DLC_APPID)
        report["dlc_preview"] = dlc_payload
        candidate = DlcCandidate(
            **{
                key: value
                for key, value in dlc_payload.items()
                if key in DlcCandidate.__dataclass_fields__
            }
        )

        def downloader(_candidate: DlcCandidate, stage: Path) -> dict[str, object]:
            attempts = []
            for owner_appid in (APPID, DLC_APPID):
                result = _run_depot_download(
                    src=src,
                    appid=owner_appid,
                    depot=DLC_DEPOT,
                    manifest=manifests[DLC_DEPOT],
                    manifest_file=dlc_manifest,
                    keys_file=keys_file,
                    target_dir=stage,
                )
                attempts.append({"owner_appid": owner_appid, **result})
                if result["return_code"] == 0 and _dir_size(stage) > 0:
                    report["dlc_download_attempts"] = attempts
                    return {
                        "ok": True,
                        "manifests": {DLC_DEPOT: str(dlc_manifest)},
                    }
            report["dlc_download_attempts"] = attempts
            return {"ok": False, "failed_reason": "dlc_depot_download_failed"}

        installer = DlcManifestInstaller()
        try:
            installed = installer.install(
                candidate,
                package_path=zip_path,
                game_dir=game_dir,
                steam_root=steam,
                downloader=downloader,
                slssteam_enabled=True,
            )
        except DlcInstallError as exc:
            report["status"] = "BLOCKED_NO_ENTITLEMENT"
            report["reason"] = str(exc)
            report["acf_after_failure_sha256"] = _sha256(appmanifest) if appmanifest.exists() else ""
            (qa_root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2))
            return 3

        report["installed_record"] = installed
        doctor = run_content_doctor(
            appid=APPID,
            game_dir=game_dir,
            steam_root=steam,
            base_path=data_root,
        )
        report["doctor_after_install"] = doctor
        repair = installer.repair(
            base_appid=APPID,
            dlc_appid=DLC_APPID,
            game_dir=game_dir,
            steam_root=steam,
        )
        report["repair"] = repair
        uninstall = installer.uninstall(
            base_appid=APPID,
            dlc_appid=DLC_APPID,
            game_dir=game_dir,
            steam_root=steam,
        )
        report["uninstall"] = uninstall
        report["doctor_after_uninstall"] = run_content_doctor(
            appid=APPID,
            game_dir=game_dir,
            steam_root=steam,
            base_path=data_root,
        )
        report["status"] = (
            "PASS_REAL_DLC"
            if doctor.get("ok") and repair.get("status") == "installed"
            else "FAILED_BUG"
        )
        (qa_root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS_REAL_DLC" else 4
    finally:
        (qa_root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
