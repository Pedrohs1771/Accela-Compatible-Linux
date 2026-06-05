"""Online-Fix verification and auto-repair for installed games."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core import steam_helpers
from core.linux_paths import detect_linux_steam_mode
from utils.proton_tools import (
    apply_steam_compat_tool,
    choose_default_proton_tool,
    discover_proton_tools,
)
from utils.steam_config_helper import _replace_or_insert_launch_options, _unescape_vdf_value

logger = logging.getLogger(__name__)

PROFILE_DIR_NAME = ".LumaTools"
PROFILE_FILE_NAME = "online_fix_profile.json"
REPORTS_DIR = Path.home() / ".local" / "share" / "LumaTools" / "online_fix_reports"

RELEVANT_DLL_NAMES = {
    "steam_api.dll",
    "steam_api64.dll",
    "winmm.dll",
    "winhttp.dll",
    "onlinefix.dll",
    "onlinefix64.dll",
    "steamoverlay.dll",
    "steamoverlay64.dll",
    "version.dll",
    "wininet.dll",
}

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


@dataclass
class OnlineFixResult:
    ok: bool = False
    status: str = "error"
    actions: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    report_path: str = ""
    profile_path: str = ""
    restart_needed: bool = False
    steam_restarted: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = dict(self.payload)
        data.update(
            {
                "ok": self.ok,
                "status": self.status,
                "actions": list(self.actions),
                "errors": list(self.errors),
                "warnings": list(self.warnings),
                "report_path": self.report_path,
                "profile_path": self.profile_path,
                "restart_needed": self.restart_needed,
                "steam_restarted": self.steam_restarted,
            }
        )
        return data


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _write_json(path: Path, data: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
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


def _find_matching_brace(content: str, open_brace_index: int) -> int:
    depth = 0
    in_string = False
    escaped = False
    for index in range(open_brace_index, len(content)):
        char = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _find_vdf_block(content: str, key: Any, start: int = 0, end: Optional[int] = None):
    search_end = len(content) if end is None else end
    search_area = content[start:search_end]
    match = re.search(rf'"{re.escape(str(key))}"\s*\{{', search_area)
    if not match:
        return None
    block_start = start + match.start()
    open_brace = start + match.start() + match.group(0).rfind("{")
    block_end = _find_matching_brace(content, open_brace)
    if block_end == -1 or block_end > search_end:
        return None
    return block_start, block_end


def _profile_path(game_dir: Path) -> Path:
    return game_dir / PROFILE_DIR_NAME / PROFILE_FILE_NAME


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _walk_limited(root: Path, max_depth: int = 5):
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


def find_main_executable(
    game_dir: str | Path,
    game_name: str = "",
    *,
    max_depth: int = 5,
) -> Optional[str]:
    root = Path(game_dir)
    if not root.is_dir():
        return None

    normalized_game = _normalize_name(game_name or root.name)
    candidates: List[Tuple[int, str]] = []
    for current_path, depth, files in _walk_limited(root, max_depth=max_depth):
        for filename in files:
            if not filename.lower().endswith(".exe"):
                continue
            lowered = filename.lower()
            stem = lowered[:-4]
            if any(part in stem for part in IGNORED_EXE_PARTS):
                continue

            normalized_file = _normalize_name(Path(filename).stem)
            score = 1000
            if normalized_file == normalized_game:
                score -= 500
            elif normalized_game and (
                normalized_file.startswith(normalized_game)
                or normalized_game.startswith(normalized_file)
            ):
                score -= 350
            elif normalized_game and normalized_game in normalized_file:
                score -= 250
            if "launcher" in stem:
                score += 100
            if "loader" in stem:
                score -= 40
            score += depth * 40
            try:
                size = (current_path / filename).stat().st_size
            except OSError:
                size = 0
            score -= min(size // 1_000_000, 80)
            candidates.append((score, str(current_path / filename)))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].lower()))
    return candidates[0][1]


def _detect_relevant_dlls(game_dir: Path) -> List[str]:
    found: set[str] = set()
    if not game_dir.is_dir():
        return []
    for current_path, _depth, files in _walk_limited(game_dir, max_depth=5):
        for filename in files:
            lowered = filename.lower()
            if lowered in RELEVANT_DLL_NAMES or "onlinefix" in lowered:
                try:
                    rel = str((current_path / filename).relative_to(game_dir))
                except ValueError:
                    rel = str(current_path / filename)
                found.add(rel)
    return sorted(found, key=str.lower)


def _dll_basename_set(paths: Iterable[str]) -> set[str]:
    return {Path(path).name.lower() for path in paths}


def _missing_expected_dlls(expected_dlls: Iterable[str], dlls_found: Iterable[str]) -> List[str]:
    found_paths = {str(path).replace("\\", "/").lower() for path in dlls_found}
    found_names = _dll_basename_set(dlls_found)
    missing = []
    for expected in expected_dlls:
        expected_text = str(expected).strip()
        if not expected_text:
            continue
        normalized = expected_text.replace("\\", "/").lower()
        if "/" in normalized:
            if normalized not in found_paths:
                missing.append(expected_text)
        elif Path(expected_text).name.lower() not in found_names:
            missing.append(expected_text)
    return missing


def _load_profile(game_dir: Path) -> Dict[str, Any]:
    path = _profile_path(game_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _extract_launch_options_from_info(game_dir: Path) -> str:
    info_path = game_dir / "LUMA_ONLINE_FIX_INFO.txt"
    content = _read_text(info_path)
    match = re.search(r"Launch Options:\s*(.+?)(?:\n\s*\n|$)", content, re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).split())


def _infer_expected_dlls(existing_profile: Dict[str, Any], dlls_found: List[str]) -> List[str]:
    expected = existing_profile.get("dlls_expected") or existing_profile.get("dlls_found") or []
    if expected:
        return sorted({str(item) for item in expected}, key=str.lower)
    return list(dlls_found)


def _find_loginusers_path(steam_root: Optional[Path]) -> Optional[Path]:
    if not steam_root:
        return None
    candidate = steam_root / "config" / "loginusers.vdf"
    return candidate if candidate.is_file() else None


def _active_user_id(steam_root: Optional[Path]) -> Optional[str]:
    loginusers = _find_loginusers_path(steam_root)
    if not loginusers:
        return None
    content = _read_text(loginusers)
    fallback = None
    for match in re.finditer(r'"(?P<id>\d+)"\s*\{(?P<body>.*?)\}', content, re.DOTALL):
        user_id = match.group("id")
        fallback = fallback or user_id
        if re.search(r'"MostRecent"\s*"1"', match.group("body")):
            return user_id
    return fallback


def _localconfig_candidates(steam_root: Optional[Path]) -> List[Path]:
    if not steam_root:
        return []
    userdata = steam_root / "userdata"
    if not userdata.is_dir():
        return []
    active = _active_user_id(steam_root)
    candidates: List[Path] = []
    if active:
        candidates.append(userdata / active / "config" / "localconfig.vdf")
    try:
        for entry in sorted(userdata.iterdir(), key=lambda item: item.name):
            if not entry.is_dir():
                continue
            candidates.append(entry / "config" / "localconfig.vdf")
    except OSError:
        pass
    seen = set()
    unique = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _read_launch_options(localconfig: Path, appid: Any) -> str:
    content = _read_text(localconfig)
    apps_block = _find_vdf_block(content, "apps")
    if not apps_block:
        return ""
    app_block = _find_vdf_block(content, str(appid), apps_block[0], apps_block[1])
    if not app_block:
        return ""
    app_content = content[app_block[0] : app_block[1] + 1]
    match = re.search(r'"LaunchOptions"\s*"((?:\\.|[^"\\])*)"', app_content)
    if not match:
        return ""
    return _unescape_vdf_value(match.group(1))


def _write_launch_options(localconfig: Path, appid: Any, launch_options: str) -> Tuple[bool, str]:
    try:
        content = _read_text(localconfig)
        new_content, changed = _replace_or_insert_launch_options(
            content, str(appid), launch_options
        )
        if not changed:
            return True, ""
        backup = f"{localconfig}.lumatools-onlinefix-{int(time.time())}.bak"
        if localconfig.exists():
            shutil.copy2(localconfig, backup)
        localconfig.parent.mkdir(parents=True, exist_ok=True)
        localconfig.write_text(new_content, encoding="utf-8")
        return True, backup
    except OSError as exc:
        return False, str(exc)


def _launch_options_ok(current: str, expected: str) -> bool:
    if not expected:
        return True
    if current.strip() == expected.strip():
        return True
    expected_match = re.search(r'WINEDLLOVERRIDES="([^"]*)"', expected)
    current_match = re.search(r'WINEDLLOVERRIDES="([^"]*)"', current)
    if expected_match and current_match:
        expected_dlls = {
            item.split("=", 1)[0].strip().lower()
            for item in expected_match.group(1).split(";")
            if item.strip()
        }
        current_dlls = {
            item.split("=", 1)[0].strip().lower()
            for item in current_match.group(1).split(";")
            if item.strip()
        }
        if not expected_dlls.issubset(current_dlls):
            return False
    return "%command%" in current or "%command%" not in expected


def _read_proton_tool(steam_root: Optional[Path], appid: Any) -> str:
    if not steam_root:
        return ""
    config_path = steam_root / "config" / "config.vdf"
    content = _read_text(config_path)
    compat_block = _find_vdf_block(content, "CompatToolMapping")
    if not compat_block:
        return ""
    app_block = _find_vdf_block(content, str(appid), compat_block[0], compat_block[1])
    if not app_block:
        return ""
    app_content = content[app_block[0] : app_block[1] + 1]
    match = re.search(r'"name"\s*"([^"]*)"', app_content)
    return match.group(1).strip() if match else ""


def _find_installed_game(appid: Any, library_path: Optional[str] = None) -> Tuple[Optional[str], Dict[str, Any]]:
    appid = str(appid).strip()
    libraries = [library_path] if library_path else list(steam_helpers.get_steam_libraries())
    preferred = steam_helpers.get_preferred_steam_library()
    if preferred and preferred not in libraries:
        libraries.append(preferred)

    for library in libraries:
        if not library:
            continue
        manifest = Path(library) / "steamapps" / f"appmanifest_{appid}.acf"
        if not manifest.is_file():
            continue
        values = _parse_acf_values(_read_text(manifest))
        return library, {
            "appid": appid,
            "game_name": values.get("name", f"App {appid}"),
            "installdir": values.get("installdir", ""),
            "buildid": values.get("buildid", "0"),
            "appmanifest": str(manifest),
        }
    return None, {}


def _game_dir_from_data(library_path: str, data: Dict[str, Any]) -> Path:
    return Path(library_path) / "steamapps" / "common" / str(data.get("installdir") or "")


def _restart_steam() -> Tuple[bool, str]:
    steam_helpers.kill_steam_process()
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            import psutil

            if not any((proc.info.get("name") or "").lower() == "steam" for proc in psutil.process_iter(["name"])):
                break
        except Exception:
            break
        time.sleep(0.25)
    status = steam_helpers.start_steam()
    if status != "SUCCESS":
        return False, status
    time.sleep(2)
    return True, status


class OnlineFixDoctor:
    def __init__(
        self,
        appid: Any,
        *,
        library_path: Optional[str] = None,
        game_data: Optional[Dict[str, Any]] = None,
        logger_override=None,
    ) -> None:
        self.appid = str(appid).strip()
        self.library_path = library_path
        self.game_data = dict(game_data or {})
        self.log = logger_override or logger

    def repair(
        self,
        *,
        auto: bool = False,
        restart_steam: bool = True,
        launch_options_override: str = "",
        proton_tool_override: str = "",
    ) -> OnlineFixResult:
        result = OnlineFixResult()
        library_path = self.library_path
        detected_data = self.game_data
        if not library_path:
            library_path, detected_data = _find_installed_game(self.appid)
        elif not detected_data:
            found_library, detected_data = _find_installed_game(self.appid, library_path)
            library_path = found_library or library_path

        if not library_path or not detected_data:
            result.errors.append(f"AppID {self.appid} not found in Steam libraries.")
            self._save_report(result, {})
            return result

        game_dir = _game_dir_from_data(library_path, detected_data)
        game_name = str(detected_data.get("game_name") or self.game_data.get("game_name") or "")
        steam_root_str = steam_helpers.find_steam_install()
        steam_root = Path(steam_root_str).expanduser().resolve() if steam_root_str else None
        steam_mode = detect_linux_steam_mode() if sys.platform == "linux" else sys.platform

        existing_profile = _load_profile(game_dir)
        main_exe = find_main_executable(game_dir, game_name) or existing_profile.get("main_exe") or ""
        dlls_found = _detect_relevant_dlls(game_dir)
        expected_dlls = _infer_expected_dlls(existing_profile, dlls_found)
        dlls_missing = _missing_expected_dlls(expected_dlls, dlls_found)

        launch_expected = (
            launch_options_override
            or existing_profile.get("launch_options")
            or existing_profile.get("launch_options_expected")
            or _extract_launch_options_from_info(game_dir)
            or ""
        )
        localconfigs = _localconfig_candidates(steam_root)
        active_localconfig = localconfigs[0] if localconfigs else None
        launch_before = _read_launch_options(active_localconfig, self.appid) if active_localconfig else ""
        launch_after = launch_before

        proton_before = _read_proton_tool(steam_root, self.appid)
        proton_after = proton_before
        selected_tool = proton_tool_override or existing_profile.get("proton_tool") or self.game_data.get("proton_tool_name") or proton_before
        proton_changed = False
        launch_changed = False

        if not main_exe:
            result.errors.append("Main executable was not detected.")

        is_windows_build = bool(main_exe)
        if is_windows_build and not selected_tool:
            default_tool = choose_default_proton_tool(discover_proton_tools())
            selected_tool = default_tool.internal_name if default_tool else ""

        if is_windows_build and not proton_before:
            result.warnings.append("Proton mapping missing.")
            if not selected_tool:
                result.warnings.append("Windows executable detected, but no Proton tool is available.")
            elif auto:
                proton_changed = apply_steam_compat_tool(self.appid, selected_tool)
                proton_after = _read_proton_tool(steam_root, self.appid)
                result.actions.append(f"Applied Proton tool: {selected_tool}")
        elif is_windows_build:
            selected_tool = proton_before

        if launch_expected and not _launch_options_ok(launch_before, launch_expected):
            result.warnings.append("LaunchOptions missing or incomplete.")
            if auto:
                if active_localconfig is None:
                    result.errors.append("No active localconfig.vdf found for Steam user.")
                else:
                    ok, backup = _write_launch_options(active_localconfig, self.appid, launch_expected)
                    if ok:
                        launch_changed = True
                        launch_after = _read_launch_options(active_localconfig, self.appid)
                        result.actions.append(
                            f"Updated LaunchOptions in {active_localconfig}"
                            + (f" backup={backup}" if backup else "")
                        )
                    else:
                        result.errors.append(f"Failed to write LaunchOptions: {backup}")

        steam_appid_txt = False
        if main_exe:
            steam_appid_txt = (Path(main_exe).parent / "steam_appid.txt").is_file()
        if existing_profile.get("steam_appid_txt") and not steam_appid_txt:
            result.warnings.append("steam_appid.txt expected by profile but missing.")

        if dlls_missing:
            result.errors.append("Missing Online-Fix DLLs: " + ", ".join(dlls_missing))

        restart_needed = bool(proton_changed or launch_changed)
        result.restart_needed = restart_needed
        if auto and restart_needed and restart_steam:
            restarted, status = _restart_steam()
            result.steam_restarted = restarted
            result.actions.append(f"Restarted Steam: {status}")
            if not restarted:
                result.errors.append(f"Steam restart failed: {status}")

        status = "ok"
        if result.errors:
            status = "error"
        elif result.warnings:
            status = "warning"
        result.status = status
        result.ok = status in {"ok", "warning"}

        profile = {
            "appid": self.appid,
            "game_name": game_name,
            "game_dir": str(game_dir),
            "main_exe": main_exe,
            "proton_tool": proton_after or selected_tool or "",
            "dlls_expected": expected_dlls,
            "dlls_found": dlls_found,
            "dlls_missing": dlls_missing,
            "dll_overrides": _dll_overrides_from_launch_options(launch_after or launch_expected),
            "launch_options": launch_after or launch_expected,
            "launch_options_expected": launch_expected,
            "steam_appid_txt": steam_appid_txt,
            "steam_mode": steam_mode,
            "last_repair_at": _now_iso(),
            "status": status,
        }
        profile_path = _profile_path(game_dir)
        _write_json(profile_path, profile)
        result.profile_path = str(profile_path)

        report = {
            "appid": self.appid,
            "status": status,
            "actions": list(result.actions),
            "steam_restarted": result.steam_restarted,
            "restart_needed": restart_needed,
            "steam_mode": steam_mode,
            "steam_root": str(steam_root) if steam_root else "",
            "active_localconfig": str(active_localconfig) if active_localconfig else "",
            "main_exe": main_exe,
            "game_dir": str(game_dir),
            "dlls_missing": dlls_missing,
            "dlls_found": dlls_found,
            "steam_appid_txt": steam_appid_txt,
            "launch_options_before": launch_before,
            "launch_options_after": launch_after,
            "launch_options_expected": launch_expected,
            "proton_before": proton_before,
            "proton_after": proton_after or selected_tool or "",
            "errors": list(result.errors),
            "warnings": list(result.warnings),
            "next_action": _next_action(status, result.errors, result.warnings),
            "written_at": _now_iso(),
        }
        self._save_report(result, report)
        return result

    def _save_report(self, result: OnlineFixResult, report: Dict[str, Any]) -> None:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"{self.appid}.json"
        if not report:
            report = {
                "appid": self.appid,
                "status": result.status,
                "errors": list(result.errors),
                "warnings": list(result.warnings),
                "actions": list(result.actions),
                "written_at": _now_iso(),
            }
        _write_json(report_path, report)
        result.report_path = str(report_path)
        result.payload = report


def _dll_overrides_from_launch_options(launch_options: str) -> List[str]:
    match = re.search(r'WINEDLLOVERRIDES="([^"]*)"', launch_options or "")
    if not match:
        return []
    return [
        item.strip()
        for item in match.group(1).split(";")
        if item.strip()
    ]


def _next_action(status: str, errors: List[str], warnings: List[str]) -> str:
    if status == "ok":
        return "Abrir Steam e testar convite em tentativa limpa."
    if errors:
        return "Corrigir itens em errors antes de testar convite."
    if warnings:
        return "Testar convite; se falhar, revisar warnings e repetir repair_online --auto."
    return "Revisar relatório."


def repair_online_fix(
    appid: Any,
    *,
    library_path: Optional[str] = None,
    game_data: Optional[Dict[str, Any]] = None,
    auto: bool = True,
    restart_steam: bool = True,
    launch_options_override: str = "",
    proton_tool_override: str = "",
    logger_override=None,
) -> OnlineFixResult:
    doctor = OnlineFixDoctor(
        appid,
        library_path=library_path,
        game_data=game_data,
        logger_override=logger_override,
    )
    return doctor.repair(
        auto=auto,
        restart_steam=restart_steam,
        launch_options_override=launch_options_override,
        proton_tool_override=proton_tool_override,
    )
