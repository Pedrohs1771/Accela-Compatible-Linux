from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

class DlcRegistry:
    """Persistent per-DLC installation state."""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        default_root = (
            Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
            / "LumaTools"
        )
        self.path = Path(path or (default_root / "dlc_registry.json"))

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "games": {}}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {"version": 1, "games": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "games": {}}
        payload.setdefault("version", 1)
        payload.setdefault("games", {})
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def update(self, base_appid: str, dlc_record: dict[str, Any]) -> dict[str, Any]:
        payload = self.load()
        games = payload.setdefault("games", {})
        game = games.setdefault(str(base_appid), {"dlcs": {}})
        record = dict(dlc_record)
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        game.setdefault("dlcs", {})[str(record["appid"])] = record
        self.save(payload)
        return record

    def get(self, base_appid: str, dlc_appid: str) -> dict[str, Any] | None:
        return (
            self.load()
            .get("games", {})
            .get(str(base_appid), {})
            .get("dlcs", {})
            .get(str(dlc_appid))
        )

    def sync_discovery(
        self,
        base_appid: str,
        records: list[dict[str, Any]],
        package_path: str = "",
    ) -> None:
        payload = self.load()
        games = payload.setdefault("games", {})
        game = games.setdefault(str(base_appid), {"dlcs": {}})
        current = game.setdefault("dlcs", {})
        discovered_ids = {str(record["appid"]) for record in records}
        for appid in list(current):
            if appid in discovered_ids:
                continue
            if current[appid].get("status") == "installed":
                continue
            current_archive = str(
                (current[appid].get("provenance") or {}).get("archive") or ""
            )
            current_package = str(current[appid].get("source_package") or "")
            if package_path and package_path in {current_archive, current_package}:
                del current[appid]
        for record in records:
            appid = str(record["appid"])
            if current.get(appid, {}).get("status") == "installed":
                continue
            current[appid] = {
                **record,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        self.save(payload)
