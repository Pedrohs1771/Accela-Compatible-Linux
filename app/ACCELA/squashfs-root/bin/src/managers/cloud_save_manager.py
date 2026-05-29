import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from core.steam_helpers import find_steam_install
from utils.helpers import get_base_path

logger = logging.getLogger(__name__)


class CloudSaveManager(QObject):
    """Alternative cloud save syncing backed by rclone."""

    sync_started = pyqtSignal(str, str)
    sync_finished = pyqtSignal(str, bool, str)

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.data_path = get_base_path() / "opencloudsave_games.json"
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(30000)
        self.watch_timer.timeout.connect(self._poll_save_changes)
        self._data = self._load_data()
        self._watch_state: Dict[str, dict] = {}
        self._active_syncs = set()
        self._batch_lock = threading.Lock()
        self._batch_state: Dict[str, dict] = {}
        self.reload_settings()

    def reload_settings(self) -> None:
        self._data = self._load_data()
        enabled = self.settings.value("opencloudsave_enabled", False, type=bool)
        auto_upload = self.settings.value(
            "opencloudsave_auto_upload", True, type=bool
        )

        if enabled and auto_upload:
            self.watch_timer.start()
            logger.info("OpenCloudSave automatic monitoring enabled.")
        else:
            self.watch_timer.stop()
            self._watch_state.clear()

    def get_rclone_binary(self) -> str:
        configured = self.settings.value(
            "opencloudsave_rclone_binary", "", type=str
        ).strip()
        if configured and os.path.exists(configured):
            return configured

        bundled = get_base_path() / "tools" / "rclone" / "rclone"
        if bundled.exists():
            return str(bundled)

        detected = shutil.which("rclone")
        return detected or ""

    def get_remote_base(self) -> str:
        return self.settings.value(
            "opencloudsave_remote", "", type=str
        ).strip().rstrip("/")

    def is_ready(self) -> Tuple[bool, str]:
        if not self.settings.value("opencloudsave_enabled", False, type=bool):
            return False, "OpenCloudSave está desativado."

        rclone_binary = self.get_rclone_binary()
        if not rclone_binary:
            return False, "rclone não encontrado. Defina o binário ou instale-o."

        remote_base = self.get_remote_base()
        if not remote_base:
            return False, "Defina um remoto rclone, por exemplo: meudrive:ACCELA-Saves"

        return True, ""

    def get_game_config(self, appid: str, game_name: str = "") -> dict:
        games = self._data.setdefault("games", {})
        entry = games.setdefault(
            str(appid),
            {
                "name": game_name or f"App {appid}",
                "enabled": False,
                "save_paths": [],
                "remote_subdir": self._default_remote_subdir(appid, game_name),
                "last_sync": "",
                "last_error": "",
            },
        )
        if game_name:
            entry["name"] = game_name
        if not entry.get("remote_subdir"):
            entry["remote_subdir"] = self._default_remote_subdir(appid, game_name)
        return entry

    def update_game_config(
        self,
        appid: str,
        game_name: str,
        enabled: bool,
        save_paths: List[str],
        remote_subdir: str,
    ) -> None:
        entry = self.get_game_config(appid, game_name)
        entry["enabled"] = enabled
        entry["save_paths"] = self._normalize_paths(save_paths)
        entry["remote_subdir"] = remote_subdir.strip() or self._default_remote_subdir(
            appid, game_name
        )
        entry["name"] = game_name or entry.get("name", f"App {appid}")
        self._save_data()

    def get_status_text(self, appid: str) -> str:
        entry = self.get_game_config(appid)
        if entry.get("last_error"):
            return f"Último erro: {entry['last_error']}"
        if entry.get("last_sync"):
            return f"Última sync: {entry['last_sync']}"
        return "Sem sincronizações ainda."

    def discover_save_paths(self, game_data: dict) -> List[str]:
        appid = str(game_data.get("appid", "")).strip()
        if not appid or appid in {"0", "N/A", "unknown"}:
            return []

        candidates = []
        steam_root = find_steam_install()
        library_path = game_data.get("library_path") or steam_root
        install_path = game_data.get("install_path")

        if steam_root:
            userdata_root = Path(steam_root) / "userdata"
            if userdata_root.exists():
                for user_dir in userdata_root.iterdir():
                    remote_path = user_dir / appid / "remote"
                    if remote_path.exists():
                        candidates.append(str(remote_path))

        if library_path:
            compat_users = (
                Path(library_path)
                / "steamapps"
                / "compatdata"
                / appid
                / "pfx"
                / "drive_c"
                / "users"
            )
            if compat_users.exists():
                for user_dir in compat_users.iterdir():
                    if not user_dir.is_dir():
                        continue
                    for relative in (
                        ("AppData", "Roaming"),
                        ("AppData", "Local"),
                        ("Documents",),
                        ("Saved Games",),
                        ("My Documents",),
                    ):
                        candidate = user_dir.joinpath(*relative)
                        if candidate.exists():
                            candidates.append(str(candidate))

        if install_path:
            install_dir = Path(install_path)
            for name in ("save", "saves", "savedata", "profiles", "userdata"):
                candidate = install_dir / name
                if candidate.exists():
                    candidates.append(str(candidate))

        unique_paths = []
        seen = set()
        for path in candidates:
            normalized = str(Path(path).expanduser().resolve())
            if normalized not in seen:
                seen.add(normalized)
                unique_paths.append(normalized)
        return unique_paths

    def sync_game_upload(
        self,
        appid: str,
        game_name: str,
        game_data: Optional[dict] = None,
        save_paths: Optional[List[str]] = None,
        remote_subdir: str = "",
        batch_id: str = "",
    ) -> None:
        self._start_sync(
            "upload",
            appid,
            game_name,
            game_data=game_data,
            save_paths=save_paths,
            remote_subdir=remote_subdir,
            batch_id=batch_id,
        )

    def sync_game_download(
        self,
        appid: str,
        game_name: str,
        game_data: Optional[dict] = None,
        save_paths: Optional[List[str]] = None,
        remote_subdir: str = "",
        batch_id: str = "",
    ) -> None:
        self._start_sync(
            "download",
            appid,
            game_name,
            game_data=game_data,
            save_paths=save_paths,
            remote_subdir=remote_subdir,
            batch_id=batch_id,
        )

    def sync_all_configured_games(self, on_complete=None) -> None:
        ready, reason = self.is_ready()
        if not ready:
            logger.info("OpenCloudSave batch skipped: %s", reason)
            if on_complete:
                QTimer.singleShot(0, on_complete)
            return

        items = []
        current_games = {
            str(game.get("appid")): game for game in self.main_window.game_manager.games
        }
        for appid, entry in self._data.get("games", {}).items():
            if not entry.get("enabled"):
                continue
            items.append((appid, entry, current_games.get(appid)))

        if not items:
            if on_complete:
                QTimer.singleShot(0, on_complete)
            return

        batch_id = f"batch-{int(time.time() * 1000)}"
        with self._batch_lock:
            self._batch_state[batch_id] = {
                "remaining": len(items),
                "callback": on_complete,
            }

        for appid, entry, game_data in items:
            self.sync_game_upload(
                appid=appid,
                game_name=entry.get("name", f"App {appid}"),
                game_data=game_data,
                save_paths=entry.get("save_paths", []),
                remote_subdir=entry.get("remote_subdir", ""),
                batch_id=batch_id,
            )

    def _start_sync(
        self,
        direction: str,
        appid: str,
        game_name: str,
        game_data: Optional[dict] = None,
        save_paths: Optional[List[str]] = None,
        remote_subdir: str = "",
        batch_id: str = "",
    ) -> None:
        ready, reason = self.is_ready()
        if not ready:
            self.sync_finished.emit(appid, False, reason)
            self._finish_batch_item(batch_id)
            return

        sync_key = (direction, str(appid))
        if sync_key in self._active_syncs:
            logger.info("Sync %s for app %s skipped because it is already running.", direction, appid)
            self._finish_batch_item(batch_id)
            return

        self._active_syncs.add(sync_key)
        self.sync_started.emit(appid, direction)
        thread = threading.Thread(
            target=self._run_sync,
            args=(direction, str(appid), game_name, game_data, save_paths, remote_subdir, batch_id, sync_key),
            daemon=True,
        )
        thread.start()

    def _run_sync(
        self,
        direction: str,
        appid: str,
        game_name: str,
        game_data: Optional[dict],
        save_paths: Optional[List[str]],
        remote_subdir: str,
        batch_id: str,
        sync_key,
    ) -> None:
        success = False
        message = ""

        try:
            entry = self.get_game_config(appid, game_name)
            remote_name = remote_subdir.strip() or entry.get("remote_subdir") or self._default_remote_subdir(appid, game_name)
            paths = self._normalize_paths(save_paths or entry.get("save_paths") or [])

            if not paths and game_data:
                paths = self.discover_save_paths(game_data)
                entry["save_paths"] = paths
                self._save_data()

            if not paths:
                raise RuntimeError("Nenhum caminho de save foi configurado para este jogo.")

            rclone_binary = self.get_rclone_binary()
            remote_base = self.get_remote_base()

            for index, local_path in enumerate(paths, start=1):
                self._sync_single_path(
                    direction=direction,
                    rclone_binary=rclone_binary,
                    local_path=local_path,
                    remote_base=remote_base,
                    remote_subdir=remote_name,
                    source_index=index,
                )

            timestamp = time.strftime("%d/%m/%Y %H:%M:%S")
            entry["last_sync"] = timestamp
            entry["last_error"] = ""
            self._save_data()
            success = True
            message = f"Sincronização {direction} concluída."
            logger.info("OpenCloudSave %s concluído para %s (%s).", direction, game_name, appid)
        except Exception as exc:
            entry = self.get_game_config(appid, game_name)
            entry["last_error"] = str(exc)
            self._save_data()
            message = str(exc)
            logger.warning("OpenCloudSave %s falhou para %s (%s): %s", direction, game_name, appid, exc)
        finally:
            self._active_syncs.discard(sync_key)
            self.sync_finished.emit(appid, success, message)
            self._finish_batch_item(batch_id)

    def _sync_single_path(
        self,
        direction: str,
        rclone_binary: str,
        local_path: str,
        remote_base: str,
        remote_subdir: str,
        source_index: int,
    ) -> None:
        source_path = Path(local_path).expanduser()
        if not source_path.exists():
            raise RuntimeError(f"Caminho de save não existe: {source_path}")

        remote_slug = self._source_slug(source_path, source_index)
        remote_target = f"{remote_base}/{remote_subdir}/{remote_slug}"

        if source_path.is_dir():
            if direction == "upload":
                cmd = [
                    rclone_binary,
                    "sync",
                    f"{source_path}/",
                    f"{remote_target}/",
                    "--create-empty-src-dirs",
                ]
            else:
                source_path.mkdir(parents=True, exist_ok=True)
                cmd = [
                    rclone_binary,
                    "sync",
                    f"{remote_target}/",
                    f"{source_path}/",
                    "--create-empty-src-dirs",
                ]
        else:
            remote_file = f"{remote_target}/{source_path.name}"
            if direction == "upload":
                cmd = [rclone_binary, "copyto", str(source_path), remote_file]
            else:
                source_path.parent.mkdir(parents=True, exist_ok=True)
                cmd = [rclone_binary, "copyto", remote_file, str(source_path)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(stderr or "rclone retornou erro durante a sincronização.")

    def _poll_save_changes(self) -> None:
        ready, _ = self.is_ready()
        if not ready:
            return

        current_games = {
            str(game.get("appid")): game for game in self.main_window.game_manager.games
        }
        settle_seconds = 20

        for appid, entry in self._data.get("games", {}).items():
            if not entry.get("enabled"):
                continue

            paths = self._normalize_paths(entry.get("save_paths", []))
            if not paths:
                game_data = current_games.get(appid)
                if not game_data:
                    continue
                paths = self.discover_save_paths(game_data)
                if not paths:
                    continue
                entry["save_paths"] = paths
                self._save_data()

            fingerprint = self._build_fingerprint(paths)
            if fingerprint is None:
                continue

            state = self._watch_state.setdefault(appid, {})
            previous = state.get("fingerprint")
            now = time.time()

            if previous is None:
                state["fingerprint"] = fingerprint
                state["last_uploaded"] = fingerprint
                continue

            if fingerprint != previous:
                state["fingerprint"] = fingerprint
                state["pending_since"] = now
                continue

            pending_since = state.get("pending_since")
            last_uploaded = state.get("last_uploaded")
            if pending_since and now - pending_since >= settle_seconds and fingerprint != last_uploaded:
                state["pending_since"] = None
                state["last_uploaded"] = fingerprint
                self.sync_game_upload(
                    appid=appid,
                    game_name=entry.get("name", f"App {appid}"),
                    game_data=current_games.get(appid),
                    save_paths=paths,
                    remote_subdir=entry.get("remote_subdir", ""),
                )

    def _build_fingerprint(self, paths: List[str]) -> Optional[Tuple[Tuple[str, int, int], ...]]:
        items = []
        for path_str in self._normalize_paths(paths):
            path = Path(path_str).expanduser()
            if not path.exists():
                continue
            latest_mtime = 0
            file_count = 0
            if path.is_dir():
                for root, _, files in os.walk(path):
                    for fname in files:
                        file_count += 1
                        try:
                            mtime = int(Path(root, fname).stat().st_mtime)
                            latest_mtime = max(latest_mtime, mtime)
                        except OSError:
                            continue
            else:
                try:
                    latest_mtime = int(path.stat().st_mtime)
                    file_count = 1
                except OSError:
                    continue
            items.append((str(path), file_count, latest_mtime))

        return tuple(items) if items else None

    def _load_data(self) -> dict:
        if not self.data_path.exists():
            return {"games": {}}

        try:
            return json.loads(self.data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load OpenCloudSave metadata: %s", exc)
            return {"games": {}}

    def _save_data(self) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        self.data_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _normalize_paths(paths: List[str]) -> List[str]:
        unique = []
        seen = set()
        for raw_path in paths:
            cleaned = str(raw_path).strip()
            if not cleaned:
                continue
            resolved = str(Path(cleaned).expanduser())
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        return unique

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
        slug = slug.strip("-._")
        return slug or "save"

    def _default_remote_subdir(self, appid: str, game_name: str) -> str:
        return f"{appid}_{self._slugify(game_name or f'app-{appid}')}"

    def _source_slug(self, source_path: Path, source_index: int) -> str:
        tail = source_path.name or source_path.parent.name or f"source-{source_index}"
        return f"{source_index:02d}_{self._slugify(tail)}"

    def _finish_batch_item(self, batch_id: str) -> None:
        if not batch_id:
            return

        callback = None
        with self._batch_lock:
            batch = self._batch_state.get(batch_id)
            if not batch:
                return
            batch["remaining"] -= 1
            if batch["remaining"] <= 0:
                callback = batch.get("callback")
                del self._batch_state[batch_id]

        if callback:
            QTimer.singleShot(0, callback)
