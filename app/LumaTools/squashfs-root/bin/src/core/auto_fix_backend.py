import logging
import os
import re
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core import steam_helpers
from utils.steam_manifest import (
    get_game_directory,
    get_install_folder_name,
    repair_installed_app_state,
    write_acf_file,
)

logger = logging.getLogger(__name__)


REQUIRED_APPSTATE_ZEROES = {
    "BytesToDownload": "0",
    "BytesToStage": "0",
    "TargetBuildID": "0",
    "UpdateResult": "0",
}

ENCRYPTED_CONTENT_PATTERNS = (
    "content still encrypted",
    "still encrypted",
    "missing decryption key",
    "unable to get depot decryption key",
    "no decryption key",
    "depot encrypted",
)

IGNORED_EXE_PARTS = {
    "unitycrashhandler",
    "crashhandler",
    "crashreporter",
    "setup",
    "install",
    "uninstall",
    "unins",
    "redist",
    "vc_redist",
    "vcredist",
    "dxsetup",
    "dotnet",
}

METADATA_ONLY_FILENAMES = {
    "steam_appid.txt",
    "force_appid.txt",
    "luma_online_fix_info.txt",
    "online_fix_profile.json",
    "partial.json",
}

METADATA_ONLY_SUFFIXES = {
    ".acf",
    ".bak",
    ".cache",
    ".cfg",
    ".config",
    ".depot",
    ".ini",
    ".json",
    ".log",
    ".manifest",
    ".old",
    ".tmp",
    ".txt",
    ".vdf",
    ".yaml",
    ".yml",
}


@dataclass
class AutoFixAction:
    reason: str
    action_taken: str
    auto_fix_attempted: bool
    auto_fix_success: bool


@dataclass
class AutoFixResult:
    ok: bool = False
    status: str = "pending"
    actions: List[AutoFixAction] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    attempts: int = 0
    restarted_steam: bool = False

    def add(
        self,
        reason: str,
        action_taken: str,
        attempted: bool,
        success: bool,
    ) -> None:
        self.actions.append(
            AutoFixAction(
                reason=reason,
                action_taken=action_taken,
                auto_fix_attempted=attempted,
                auto_fix_success=success,
            )
        )
        if not success:
            self.issues.append(reason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "attempts": self.attempts,
            "restarted_steam": self.restarted_steam,
            "issues": list(self.issues),
            "actions": [action.__dict__.copy() for action in self.actions],
        }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _write_text(path: Path, content: str) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
        return True
    except OSError as exc:
        logger.warning("Failed to write %s: %s", path, exc)
        return False


def _parse_acf_values(content: str) -> Dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(r'"([^"]+)"\s*"([^"]*)"', content)
    }


def _parse_installed_depots(content: str) -> Dict[str, str]:
    section_match = re.search(r'"InstalledDepots"\s*\{', content)
    if not section_match:
        return {}

    start = content.find("{", section_match.end() - 1)
    if start == -1:
        return {}
    depth = 0
    end = -1
    for index in range(start, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end == -1:
        return {}

    body = content[start + 1:end]
    depots: Dict[str, str] = {}
    for depot_match in re.finditer(
        r'"(?P<depot>\d+)"\s*\{(?P<body>.*?)\}', body, re.DOTALL
    ):
        manifest_match = re.search(r'"manifest"\s*"(?P<manifest>[^"]+)"', depot_match.group("body"))
        if manifest_match:
            depots[depot_match.group("depot")] = manifest_match.group("manifest")
    return depots


def _directory_size(path: Path) -> int:
    total = 0
    if not path.is_dir():
        return 0
    for root, _, files in os.walk(path):
        for filename in files:
            try:
                total += (Path(root) / filename).stat().st_size
            except OSError:
                continue
    return total


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _walk_limited(root: Path, max_depth: int = 5):
    if not root.is_dir():
        return
    root = root.resolve()
    for current, dirs, files in os.walk(root):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            continue
        if depth >= max_depth:
            dirs[:] = []
        yield current_path, depth, files


def _find_main_executable(game_dir: Path, game_name: str = "") -> Optional[str]:
    normalized_game = _normalize_name(game_name or game_dir.name)
    candidates: List[Tuple[int, str]] = []
    for current_path, depth, files in _walk_limited(game_dir, max_depth=5) or []:
        for filename in files:
            if not filename.lower().endswith(".exe"):
                continue
            stem = filename[:-4].lower()
            if any(part in stem for part in IGNORED_EXE_PARTS):
                continue
            normalized_file = _normalize_name(Path(filename).stem)
            score = depth * 40
            if normalized_file == normalized_game:
                score -= 500
            elif normalized_game and normalized_game in normalized_file:
                score -= 250
            if "launcher" in stem:
                score += 100
            try:
                score -= min((current_path / filename).stat().st_size // 1_000_000, 80)
            except OSError:
                pass
            candidates.append((score, str(current_path / filename)))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].lower()))
    return candidates[0][1]


def _selected_depots_require_windows(game_data: Optional[Dict[str, Any]]) -> bool:
    if not game_data:
        return False
    if game_data.get("force_proton") or game_data.get("apply_online_fix"):
        return True
    selected = [str(item) for item in game_data.get("selected_depots_list") or []]
    depots = game_data.get("depots") or {}
    for depot_id in selected:
        platform = str((depots.get(depot_id) or {}).get("oslist") or "").lower()
        if platform == "windows":
            return True
    return False


def _is_metadata_only_file(path: Path) -> bool:
    name = path.name.lower()
    if name in METADATA_ONLY_FILENAMES:
        return True
    if name.endswith(".dll"):
        return True
    if path.suffix.lower() in METADATA_ONLY_SUFFIXES:
        return True
    lowered_parts = {part.lower() for part in path.parts}
    return any(
        marker in lowered_parts
        for marker in {".depotdownloader", "_commonredist", "redist", "redistributables"}
    )


def _has_launchable_base_content(game_dir: Path, game_data: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if not game_dir.is_dir():
        return False, "missing_base_game_content: game_dir missing"
    windows_build = _selected_depots_require_windows(game_data)
    main_exe = _find_main_executable(game_dir, (game_data or {}).get("game_name", ""))
    if windows_build and not main_exe:
        return False, "missing_base_game_content: Windows/Proton build has no main .exe"
    if main_exe:
        return True, f"main executable found: {main_exe}"

    meaningful_files = 0
    for root, _, files in os.walk(game_dir):
        for filename in files:
            file_path = Path(root) / filename
            if not _is_metadata_only_file(file_path):
                meaningful_files += 1
                if meaningful_files >= 2:
                    return True, "launchable non-Windows content found"
    return False, "only_dlc_or_runtime_downloaded: no launchable base content found"


def _detect_encrypted_content_in_text(content: str) -> bool:
    lowered = content.lower()
    return any(pattern in lowered for pattern in ENCRYPTED_CONTENT_PATTERNS)


def _detect_encrypted_content_logs(
    appid: Any,
    steam_root: Optional[str],
    library_path: str,
    depot_ids: Optional[Iterable[Any]] = None,
    since_timestamp: Optional[float] = None,
) -> Tuple[bool, str]:
    candidates: List[Path] = []
    if steam_root:
        candidates.extend((Path(steam_root) / "logs").glob("*.txt"))
    candidates.extend((Path(library_path) / "steamapps").glob("*.log"))
    match_tokens = {str(appid or "").strip()}
    match_tokens.update(str(item).strip() for item in (depot_ids or []) if str(item).strip())
    match_tokens = {token for token in match_tokens if token}
    for candidate in candidates:
        if not candidate.is_file():
            continue
        try:
            with open(candidate, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                handle.seek(max(0, size - 1_000_000))
                content = handle.read().decode("utf-8", errors="ignore")
        except OSError:
            continue
        if not _detect_encrypted_content_in_text(content):
            continue
        matching_lines = [
            line.strip()
            for line in content.splitlines()
            if _detect_encrypted_content_in_text(line)
        ]
        app_specific = [
            line
            for line in matching_lines
            if any(token in line for token in match_tokens)
            and _log_line_is_current(line, since_timestamp)
        ]
        if app_specific:
            return True, f"encrypted_content_or_unsupported_depot: {candidate}: {app_specific[-1]}"
    return False, ""


def _log_line_is_current(line: str, since_timestamp: Optional[float]) -> bool:
    if since_timestamp is None:
        return True
    match = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
    if not match:
        return True
    try:
        line_timestamp = time.mktime(time.strptime(match.group(1), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return True
    return line_timestamp >= since_timestamp


def _status_from_issues(issues: Iterable[str]) -> str:
    for issue in issues:
        issue_text = str(issue)
        if issue_text.startswith("encrypted_content_or_unsupported_depot"):
            return "encrypted_content_or_unsupported_depot"
        if issue_text.startswith("missing_base_game_content"):
            return "missing_base_game_content"
        if issue_text.startswith("only_dlc_or_runtime_downloaded"):
            return "only_dlc_or_runtime_downloaded"
    return "error"


def _manifest_path(library_path: str, appid: Any) -> Path:
    return Path(library_path) / "steamapps" / f"appmanifest_{appid}.acf"


def _depotcache_dirs(library_path: str) -> Tuple[Path, Path]:
    library = Path(library_path)
    return library / "steamapps" / "depotcache", library / "depotcache"


def _selected_depot_manifests(game_data: Optional[Dict[str, Any]], acf_content: str) -> Dict[str, str]:
    if game_data:
        selected = [str(item) for item in game_data.get("selected_depots_list") or []]
        manifests = {str(k): str(v) for k, v in (game_data.get("manifests") or {}).items()}
        if selected and manifests:
            return {depot: manifests[depot] for depot in selected if depot in manifests}
    return _parse_installed_depots(acf_content)


def _find_loginusers_candidates(steam_root: Optional[str]) -> List[Path]:
    candidates: List[Path] = []
    if steam_root:
        candidates.append(Path(steam_root) / "config" / "loginusers.vdf")
    home = Path.home()
    candidates.extend(
        [
            home / ".local" / "share" / "Steam" / "config" / "loginusers.vdf",
            home / ".steam" / "steam" / "config" / "loginusers.vdf",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam" / "config" / "loginusers.vdf",
            home / "snap" / "steam" / "common" / ".local" / "share" / "Steam" / "config" / "loginusers.vdf",
            home / "snap" / "steam" / "current" / ".local" / "share" / "Steam" / "config" / "loginusers.vdf",
        ]
    )
    seen = set()
    unique = []
    for path in candidates:
        normalized = str(path)
        if normalized not in seen:
            seen.add(normalized)
            unique.append(path)
    return unique


def _active_steam_user_id(loginusers_content: str) -> Optional[str]:
    blocks = re.finditer(r'"(?P<id>\d+)"\s*\{(?P<body>.*?)\}', loginusers_content, re.DOTALL)
    fallback = None
    for block in blocks:
        user_id = block.group("id")
        body = block.group("body")
        if fallback is None:
            fallback = user_id
        if re.search(r'"MostRecent"\s*"1"', body):
            return user_id
    return fallback


def _replace_or_insert_value(content: str, key: str, value: str) -> str:
    safe_value = str(value).replace("\\", "\\\\").replace('"', '\\"')
    pattern = re.compile(rf'^(\s*)"{re.escape(key)}"\s*"[^"]*"\s*$', re.MULTILINE)
    if pattern.search(content):
        return pattern.sub(lambda match: f'{match.group(1)}"{key}"\t\t"{safe_value}"', content, count=1)
    insert_at = content.find('"InstalledDepots"')
    insertion = f'\t"{key}"\t\t"{safe_value}"\n'
    if insert_at != -1:
        return content[:insert_at] + insertion + content[insert_at:]
    closing = content.rfind("\n}")
    if closing != -1:
        return content[:closing] + "\n" + insertion + content[closing:]
    return content + "\n" + insertion


def _fix_last_owner(appmanifest: Path, steam_root: Optional[str]) -> Tuple[bool, str]:
    content = _read_text(appmanifest)
    values = _parse_acf_values(content)
    if values.get("LastOwner", "").strip() not in {"", "0"}:
        return True, "LastOwner already set."

    for candidate in _find_loginusers_candidates(steam_root):
        if not candidate.is_file():
            continue
        user_id = _active_steam_user_id(_read_text(candidate))
        if not user_id:
            continue
        updated = _replace_or_insert_value(content, "LastOwner", user_id)
        if _write_text(appmanifest, updated):
            return True, f"LastOwner set from {candidate}"
        return False, f"Failed to write LastOwner from {candidate}"
    return False, "No active Steam user found in loginusers.vdf candidates."


def _clean_steam_queue_state(library_path: str, appid: Any) -> bool:
    steamapps = Path(library_path) / "steamapps"
    for queue_name in ("downloading", "temp", "shadercache"):
        for candidate in (
            steamapps / queue_name / str(appid),
            steamapps / queue_name / f"appmanifest_{appid}.acf",
        ):
            if not candidate.exists():
                continue
            try:
                if candidate.is_dir():
                    shutil.rmtree(candidate)
                else:
                    candidate.unlink()
            except OSError as exc:
                logger.warning("Failed to remove stale Steam state %s: %s", candidate, exc)
                return False
    return True


def _ensure_depotcache(library_path: str, depot_manifests: Dict[str, str]) -> Tuple[bool, str]:
    if not depot_manifests:
        return True, "No selected depot manifests to verify."

    steamapps_cache, legacy_cache = _depotcache_dirs(library_path)
    steamapps_cache.mkdir(parents=True, exist_ok=True)
    missing = []
    copied = 0
    for depot_id, manifest_id in depot_manifests.items():
        filename = f"{depot_id}_{manifest_id}.manifest"
        target = steamapps_cache / filename
        if target.is_file():
            continue
        legacy = legacy_cache / filename
        if legacy.is_file():
            try:
                shutil.copy2(legacy, target)
                copied += 1
                continue
            except OSError as exc:
                logger.warning("Failed to copy depot manifest %s: %s", legacy, exc)
        missing.append(filename)

    if missing:
        return False, "Missing depotcache manifests: " + ", ".join(missing)
    return True, f"Depotcache OK; copied {copied} manifest(s) from legacy cache."


def _check_depotcache(library_path: str, depot_manifests: Dict[str, str]) -> Tuple[bool, str]:
    if not depot_manifests:
        return True, "No selected depot manifests to verify."

    steamapps_cache, legacy_cache = _depotcache_dirs(library_path)
    missing = []
    for depot_id, manifest_id in depot_manifests.items():
        filename = f"{depot_id}_{manifest_id}.manifest"
        if (steamapps_cache / filename).is_file():
            continue
        if (legacy_cache / filename).is_file():
            missing.append(f"{filename} in legacy depotcache only")
            continue
        missing.append(filename)

    if missing:
        return False, "Missing depotcache manifests: " + ", ".join(missing)
    return True, "Depotcache OK."


def _ensure_slssteam_entries(game_data: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if sys.platform != "linux":
        return True, "SLSsteam config not required on this platform."
    try:
        from utils.yaml_config_manager import (
            add_additional_app,
            add_dlc_data,
            ensure_slssteam_config,
            get_user_config_path,
            is_slssteam_config_management_enabled,
            is_slssteam_mode_enabled,
        )
    except ImportError as exc:
        return True, f"SLSsteam config helpers unavailable in CLI runtime; skipped: {exc}"

    if not is_slssteam_mode_enabled() or not is_slssteam_config_management_enabled():
        return True, "SLSsteam config management inactive."
    if not game_data:
        return False, "Game metadata unavailable for SLSsteam config."

    config_path = get_user_config_path()
    if not ensure_slssteam_config(config_path):
        return False, f"Could not create SLSsteam config at {config_path}"

    main_appid = str(game_data.get("appid") or "").strip()
    game_name = game_data.get("game_name", "")
    if main_appid:
        add_additional_app(config_path, main_appid, game_name)

    selected_dlcs = [str(item) for item in (game_data.get("selected_dlcs") or [])]
    dlcs = game_data.get("dlcs") or {}
    for dlc_id in selected_dlcs:
        add_dlc_data(config_path, main_appid, dlc_id, str(dlcs.get(dlc_id, "")))

    content = _read_text(config_path)
    if main_appid and not re.search(rf"^\s*-\s*{re.escape(main_appid)}\b", content, re.MULTILINE):
        return False, f"AppID {main_appid} was not written to SLSsteam config."
    return True, f"SLSsteam config OK at {config_path}"


def _check_slssteam_entries(game_data: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    if sys.platform != "linux":
        return True, "SLSsteam config not required on this platform."
    try:
        from utils.yaml_config_manager import (
            get_user_config_path,
            is_slssteam_config_management_enabled,
            is_slssteam_mode_enabled,
        )
    except ImportError as exc:
        return True, f"SLSsteam config helpers unavailable in CLI runtime; skipped: {exc}"

    if not is_slssteam_mode_enabled() or not is_slssteam_config_management_enabled():
        return True, "SLSsteam config management inactive."
    if not game_data:
        return False, "Game metadata unavailable for SLSsteam config."

    config_path = get_user_config_path()
    if not config_path.is_file():
        return False, f"SLSsteam config missing: {config_path}"

    main_appid = str(game_data.get("appid") or "").strip()
    content = _read_text(config_path)
    if main_appid and not re.search(rf"^\s*-\s*{re.escape(main_appid)}\b", content, re.MULTILINE):
        return False, f"AppID {main_appid} missing from SLSsteam config."
    return True, f"SLSsteam config OK at {config_path}"


def _ensure_library_writable(library_path: str) -> Tuple[bool, str]:
    library = Path(library_path)
    test_dir = library / "steamapps"
    try:
        test_dir.mkdir(parents=True, exist_ok=True)
        probe = test_dir / ".lumatools-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, "Library is writable."
    except OSError:
        pass

    try:
        for path in (library, library / "steamapps", library / "steamapps" / "common"):
            if not path.exists():
                continue
            mode = path.stat().st_mode
            os.chmod(path, mode | stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
        probe = test_dir / ".lumatools-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, "Library permissions fixed with chmod u+rwX."
    except OSError as exc:
        return False, f"Library is not writable and chmod failed: {exc}"


def _restart_steam_if_needed(result: AutoFixResult, restart: bool) -> None:
    if not restart:
        return
    try:
        steam_helpers.kill_steam_process()
        status = steam_helpers.start_steam()
        ok = status == "SUCCESS"
        result.restarted_steam = ok
        result.add(
            "Steam restart required after backend repair.",
            f"restart_steam status={status}",
            True,
            ok,
        )
    except Exception as exc:
        result.add(
            "Steam restart required after backend repair.",
            f"restart_steam failed: {exc}",
            True,
            False,
        )


def verify_install_state(
    appid: Any,
    library_path: str,
    game_data: Optional[Dict[str, Any]] = None,
    *,
    logger_override=None,
) -> List[str]:
    log = logger_override or logger
    issues: List[str] = []
    appmanifest = _manifest_path(library_path, appid)
    steam_root = steam_helpers.find_steam_install()
    depot_ids = []
    if game_data:
        depot_ids = list((game_data.get("manifests") or {}).keys())
    since_timestamp = None
    if appmanifest.is_file():
        try:
            since_timestamp = appmanifest.stat().st_mtime - 60
        except OSError:
            since_timestamp = None
    encrypted, encrypted_msg = _detect_encrypted_content_logs(
        appid, steam_root, library_path, depot_ids=depot_ids, since_timestamp=since_timestamp
    )
    if encrypted:
        return [encrypted_msg]

    if not appmanifest.is_file():
        return [f"appmanifest missing: {appmanifest}"]

    content = _read_text(appmanifest)
    values = _parse_acf_values(content)
    if values.get("StateFlags") != "4":
        issues.append(f"StateFlags={values.get('StateFlags', '<missing>')}")
    for key, expected in REQUIRED_APPSTATE_ZEROES.items():
        if values.get(key, "0") != expected:
            issues.append(f"{key}={values.get(key, '<missing>')}")
    if values.get("LastOwner", "0") in {"", "0"}:
        issues.append("LastOwner=0")

    if game_data:
        game_dir = Path(get_game_directory(library_path, game_data))
    else:
        installdir = values.get("installdir", "")
        game_dir = Path(library_path) / "steamapps" / "common" / installdir
    if not game_dir.is_dir():
        issues.append(f"game_dir missing: {game_dir}")
    elif _directory_size(game_dir) <= 0:
        issues.append(f"game_dir empty: {game_dir}")
    else:
        content_ok, content_msg = _has_launchable_base_content(game_dir, game_data)
        if not content_ok:
            issues.append(content_msg)
        else:
            log.debug(content_msg)

    depot_ok, depot_msg = _check_depotcache(
        library_path, _selected_depot_manifests(game_data, content)
    )
    if not depot_ok:
        issues.append(depot_msg)
    else:
        log.debug(depot_msg)

    sls_ok, sls_msg = _check_slssteam_entries(game_data)
    if not sls_ok:
        issues.append(sls_msg)
    else:
        log.debug(sls_msg)
    return issues


def auto_fix_install_state(
    game_data: Dict[str, Any],
    library_path: str,
    *,
    size_on_disk: Optional[int] = None,
    auto_restart_steam: bool = True,
    max_attempts: int = 2,
    logger_override=None,
) -> AutoFixResult:
    log = logger_override or logger
    result = AutoFixResult()
    appid = game_data.get("appid")
    if not appid or not library_path:
        result.add("Missing AppID or library path.", "abort", False, False)
        return result

    steam_root = steam_helpers.find_steam_install()
    appmanifest = _manifest_path(library_path, appid)
    changed = False

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        issues = verify_install_state(appid, library_path, game_data, logger_override=log)
        if any(str(issue).startswith("encrypted_content_or_unsupported_depot") for issue in issues):
            result.status = "encrypted_content_or_unsupported_depot"
            result.issues = issues
            result.add(
                "encrypted_content_or_unsupported_depot",
                "abort: depot/manifest/content is not launchable",
                False,
                False,
            )
            return result
        if not issues:
            result.ok = True
            result.status = "ok"
            break

        log.info("Auto-Fix attempt %s for AppID %s: %s", attempt, appid, "; ".join(issues))

        writable_ok, writable_msg = _ensure_library_writable(library_path)
        result.add("Library write permission check.", writable_msg, True, writable_ok)
        if not writable_ok:
            break

        if not appmanifest.is_file() and size_on_disk is not None:
            try:
                write_acf_file(library_path, game_data, size_on_disk, include_depots=True)
                changed = True
                result.add("appmanifest missing.", "write_acf_file", True, True)
            except OSError as exc:
                result.add("appmanifest missing.", f"write_acf_file failed: {exc}", True, False)

        repaired = repair_installed_app_state(library_path, appid, logger=log)
        changed = changed or repaired
        result.add("Steam appmanifest update state.", "repair_installed_app_state", True, repaired)

        queue_ok = _clean_steam_queue_state(library_path, appid)
        changed = changed or queue_ok
        result.add("Stale Steam downloading/temp/shadercache state.", "clean_steam_queue_state", True, queue_ok)

        if appmanifest.is_file():
            owner_ok, owner_msg = _fix_last_owner(appmanifest, steam_root)
            changed = changed or owner_ok
            result.add("LastOwner missing or zero.", owner_msg, True, owner_ok)

            content = _read_text(appmanifest)
            depot_ok, depot_msg = _ensure_depotcache(
                library_path, _selected_depot_manifests(game_data, content)
            )
            changed = changed or depot_ok
            result.add("Depotcache selected manifests.", depot_msg, True, depot_ok)

        sls_ok, sls_msg = _ensure_slssteam_entries(game_data)
        changed = changed or sls_ok
        result.add("SLSsteam config/AppID/DLC entries.", sls_msg, True, sls_ok)

        if not verify_install_state(appid, library_path, game_data, logger_override=log):
            result.ok = True
            result.status = "ok"
            result.issues = []
            break

    if result.ok and changed and auto_restart_steam:
        _restart_steam_if_needed(result, True)
    elif not result.ok:
        result.issues = verify_install_state(appid, library_path, game_data, logger_override=log)
        result.status = _status_from_issues(result.issues)

    return result


def repair_existing_game(
    appid: Any,
    *,
    library_path: Optional[str] = None,
    auto_restart_steam: bool = True,
    logger_override=None,
) -> AutoFixResult:
    log = logger_override or logger
    appid = str(appid).strip()
    libraries = [library_path] if library_path else list(steam_helpers.get_steam_libraries())
    if not libraries:
        preferred = steam_helpers.get_preferred_steam_library()
        if preferred:
            libraries = [preferred]

    for candidate in libraries:
        if not candidate:
            continue
        appmanifest = _manifest_path(candidate, appid)
        if not appmanifest.is_file():
            continue
        content = _read_text(appmanifest)
        values = _parse_acf_values(content)
        game_data = {
            "appid": appid,
            "game_name": values.get("name", f"App {appid}"),
            "installdir": values.get("installdir", ""),
            "selected_depots_list": list(_parse_installed_depots(content).keys()),
            "manifests": _parse_installed_depots(content),
            "depots": {},
        }
        return auto_fix_install_state(
            game_data,
            candidate,
            auto_restart_steam=auto_restart_steam,
            logger_override=log,
        )

    result = AutoFixResult()
    result.add(
        f"AppID {appid} appmanifest was not found in detected Steam libraries.",
        "search_libraries",
        True,
        False,
    )
    return result
