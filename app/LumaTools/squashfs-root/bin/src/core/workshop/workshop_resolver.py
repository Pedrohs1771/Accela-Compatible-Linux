from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from core.workshop.workshop_errors import (
    WorkshopError,
    classify_steamcmd_error,
)


class WorkshopResolver:
    def __init__(self, steamcmd: str | Path):
        self.steamcmd = str(steamcmd)

    def download(
        self,
        *,
        appid: str,
        workshop_id: str,
        target_root: str | Path,
        username: str = "",
        password: str = "",
        on_line: Callable[[str], None] | None = None,
        on_process: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> Path:
        root = Path(target_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        login = ["anonymous"] if not username else [username, password]
        command = [
            self.steamcmd,
            "+force_install_dir",
            str(root),
            "+login",
            *login,
            "+workshop_download_item",
            str(appid),
            str(workshop_id),
            "validate",
            "+quit",
        ]
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if on_process:
            on_process(process)
        lines: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip()
            if not text:
                continue
            lines.append(text)
            if on_line:
                on_line(text)
        return_code = process.wait()
        output = "\n".join(lines)
        download_path = self.find_download_path(root, str(appid), str(workshop_id))
        if return_code != 0 or download_path is None:
            code = classify_steamcmd_error(output)
            raise WorkshopError(
                code,
                f"SteamCMD nao conseguiu baixar o item {workshop_id}.",
                output[-4000:],
            )
        return download_path

    @staticmethod
    def find_download_path(root: Path, appid: str, itemid: str) -> Path | None:
        candidates = (
            root / "steamapps" / "workshop" / "content" / appid / itemid,
            root / "workshop" / "content" / appid / itemid,
        )
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        for candidate in root.rglob(itemid):
            if candidate.is_dir():
                return candidate
        return None
