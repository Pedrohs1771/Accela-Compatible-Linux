import json
import logging
import os
import shutil
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zipfile import ZipFile

logger = logging.getLogger(__name__)

FIX_STACK_FILE = "LUMA_FIX_STACK.json"
RYUU_INFO_FILE = "LUMA_RYUU_FIX_INFO.txt"

PROTECTED_ONLINE_FIX_FILES = {
    "steam_api.dll",
    "steam_api64.dll",
    "winmm.dll",
    "winhttp.dll",
    "onlinefix.dll",
    "onlinefix64.dll",
    "steamoverlay64.dll",
    "onlinefix.ini",
    "steamfix.ini",
    "steam_appid.txt",
}

ONLINE_FIX_MARKER_FILES = {
    "LUMA_ONLINE_FIX_INFO.txt",
    "OnlineFix.ini",
    "SteamFix.ini",
    "onlinefix.dll",
    "onlinefix64.dll",
    "OnlineFix64.dll",
    "SteamOverlay64.dll",
}


def has_online_fix(game_dir: str | Path) -> bool:
    root = Path(game_dir)
    if (root / "LUMA_ONLINE_FIX_INFO.txt").exists():
        return True

    for marker in ONLINE_FIX_MARKER_FILES:
        if (root / marker).exists():
            return True

    stack = _load_fix_stack(root)
    return any(
        str(layer.get("source", "")).lower() == "onlinefix"
        for layer in stack.get("layers", [])
    )


def plan_ryuu_fix(game_dir: str | Path, fix_path: str | Path) -> dict[str, Any]:
    root = Path(game_dir)
    source = Path(fix_path)
    online_fix_present = has_online_fix(root)
    safe_files = []
    conflicted_files = []

    for rel in _list_fix_files(source):
        rel_path = Path(rel)
        protected = (
            rel_path.name.lower() in PROTECTED_ONLINE_FIX_FILES
            or rel_path.as_posix().lower() in PROTECTED_ONLINE_FIX_FILES
        )
        item = {"path": rel, "protected": protected}
        if online_fix_present and protected:
            conflicted_files.append(item)
        else:
            safe_files.append(item)

    return {
        "game_dir": str(root),
        "fix_path": str(source),
        "online_fix_present": online_fix_present,
        "safe_files": safe_files,
        "conflicted_files": conflicted_files,
    }


def apply_ryuu_fix(
    game_dir: str | Path,
    fix_path: str | Path,
    *,
    appid: str,
    game_name: str,
    branch: str = "public",
    preserve_online_fix: bool = True,
) -> dict[str, Any]:
    root = Path(game_dir)
    source = Path(fix_path)
    if not root.exists():
        raise FileNotFoundError(f"Pasta do jogo nao encontrada: {root}")
    if not source.exists():
        raise FileNotFoundError(f"Fix Ryuu nao encontrado: {source}")

    plan = plan_ryuu_fix(root, source)
    if not preserve_online_fix:
        plan["safe_files"].extend(plan["conflicted_files"])
        plan["conflicted_files"] = []

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = root / ".LumaTools" / "backups" / f"ryuu-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)

    applied_files: list[str] = []
    backup_files: list[dict[str, Any]] = []
    skipped_conflicts = [item["path"] for item in plan["conflicted_files"]]

    with _prepared_source(source) as prepared:
        for item in plan["safe_files"]:
            rel = _safe_relative_path(item["path"])
            src = prepared / rel
            if not src.exists() or src.is_dir():
                continue

            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            backup_entry: dict[str, Any] = {
                "path": rel.as_posix(),
                "existed": dst.exists(),
            }

            if dst.exists():
                backup_dst = backup_root / rel
                backup_dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, backup_dst)
                backup_entry["backup"] = str(backup_dst.relative_to(backup_root))

            shutil.copy2(src, dst)
            applied_files.append(rel.as_posix())
            backup_files.append(backup_entry)

    layer = {
        "source": "Ryuu",
        "type": "compatibility",
        "safe": not skipped_conflicts,
        "branch": branch or "public",
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "fix_path": str(source),
        "backup_path": str(backup_root),
        "applied_files": applied_files,
        "skipped_conflicts": skipped_conflicts,
        "backup_files": backup_files,
    }
    _append_fix_layer(root, appid=appid, game_name=game_name, layer=layer)
    _write_ryuu_info(root, appid, game_name, branch or "public", layer)

    return {
        "applied_files": applied_files,
        "skipped_conflicts": skipped_conflicts,
        "backup_path": str(backup_root),
    }


def record_online_fix_layer(
    game_dir: str | Path,
    *,
    appid: str,
    game_name: str,
    found_dlls: list[str] | None = None,
    launch_options: str = "",
) -> None:
    layer = {
        "source": "OnlineFix",
        "type": "online",
        "applied_at": datetime.now().isoformat(timespec="seconds"),
        "protected_files": sorted(PROTECTED_ONLINE_FIX_FILES),
        "found_dlls": found_dlls or [],
        "launch_options": launch_options,
    }
    _append_fix_layer(Path(game_dir), appid=appid, game_name=game_name, layer=layer)


def undo_last_fix(game_dir: str | Path) -> dict[str, Any]:
    root = Path(game_dir)
    stack = _load_fix_stack(root)
    layers = stack.get("layers", [])
    layer_index = next(
        (idx for idx in range(len(layers) - 1, -1, -1) if layers[idx].get("backup_files")),
        None,
    )
    if layer_index is None:
        return {"restored_files": [], "removed_files": []}

    layer = layers.pop(layer_index)
    backup_root = Path(layer.get("backup_path", ""))
    restored_files: list[str] = []
    removed_files: list[str] = []

    for entry in reversed(layer.get("backup_files", [])):
        rel = _safe_relative_path(entry.get("path", ""))
        target = root / rel
        if entry.get("existed"):
            backup_rel = entry.get("backup")
            if backup_rel:
                backup_file = backup_root / _safe_relative_path(backup_rel)
                if backup_file.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup_file, target)
                    restored_files.append(rel.as_posix())
        elif target.exists():
            target.unlink()
            removed_files.append(rel.as_posix())

    stack["layers"] = layers
    _write_fix_stack(root, stack)
    return {"restored_files": restored_files, "removed_files": removed_files}


def _list_fix_files(source: Path) -> list[str]:
    if source.suffix.lower() == ".zip":
        with ZipFile(source) as archive:
            return [
                _safe_relative_path(name).as_posix()
                for name in archive.namelist()
                if name and not name.endswith("/")
            ]

    if tarfile.is_tarfile(source):
        with tarfile.open(source) as archive:
            return [
                _safe_relative_path(member.name).as_posix()
                for member in archive.getmembers()
                if member.isfile()
            ]

    return [source.name]


class _prepared_source:
    def __init__(self, source: Path):
        self.source = source
        self.temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.root: Path | None = None

    def __enter__(self) -> Path:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="lumatools-ryuu-")
        self.root = Path(self.temp_dir.name)
        if self.source.suffix.lower() == ".zip":
            with ZipFile(self.source) as archive:
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    rel = _safe_relative_path(name)
                    target = self.root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(name) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        elif tarfile.is_tarfile(self.source):
            with tarfile.open(self.source) as archive:
                for member in archive.getmembers():
                    if not member.isfile():
                        continue
                    rel = _safe_relative_path(member.name)
                    target = self.root / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = archive.extractfile(member)
                    if extracted:
                        with extracted, open(target, "wb") as dst:
                            shutil.copyfileobj(extracted, dst)
        else:
            shutil.copy2(self.source, self.root / self.source.name)
        return self.root

    def __exit__(self, *_args: object) -> None:
        if self.temp_dir:
            self.temp_dir.cleanup()


def _safe_relative_path(value: str | os.PathLike[str]) -> Path:
    rel = Path(str(value).replace("\\", "/"))
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"Caminho inseguro no fix: {value}")
    return rel


def _load_fix_stack(game_dir: Path) -> dict[str, Any]:
    path = game_dir / FIX_STACK_FILE
    if not path.exists():
        return {"game_dir": str(game_dir), "layers": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"game_dir": str(game_dir), "layers": []}
        data.setdefault("layers", [])
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Falha ao ler %s: %s", path, exc)
        return {"game_dir": str(game_dir), "layers": []}


def _write_fix_stack(game_dir: Path, data: dict[str, Any]) -> None:
    (game_dir / FIX_STACK_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _append_fix_layer(game_dir: Path, *, appid: str, game_name: str, layer: dict[str, Any]) -> None:
    stack = _load_fix_stack(game_dir)
    stack["appid"] = str(appid)
    stack["game_name"] = game_name
    stack["game_dir"] = str(game_dir)
    stack.setdefault("layers", []).append(layer)
    _write_fix_stack(game_dir, stack)


def _write_ryuu_info(
    game_dir: Path, appid: str, game_name: str, branch: str, layer: dict[str, Any]
) -> None:
    lines = [
        "Fonte: Ryuu Fixes",
        f"Jogo: {game_name}",
        f"AppID: {appid}",
        f"Branch: {branch}",
        f"Data: {layer['applied_at']}",
        f"Backup: {layer['backup_path']}",
        "",
        "Arquivos aplicados:",
        *[f"- {item}" for item in layer.get("applied_files", [])],
        "",
        "Arquivos ignorados por conflito:",
        *[f"- {item}" for item in layer.get("skipped_conflicts", [])],
        "",
    ]
    (game_dir / RYUU_INFO_FILE).write_text("\n".join(lines), encoding="utf-8")
