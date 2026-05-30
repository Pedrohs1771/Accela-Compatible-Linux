#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "ACCELA" / "squashfs-root" / "bin" / "src"
FIXTURES = ROOT / "tests" / "fixtures"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from core.platform.linux import LinuxBackend  # noqa: E402
from managers.game_manager import GameManager  # noqa: E402


def time_call(label, func):
    started = time.perf_counter()
    result = func()
    elapsed = time.perf_counter() - started
    return {"label": label, "seconds": round(elapsed, 4), "result": result}


def benchmark_compileall():
    cmd = [sys.executable, "-m", "compileall", str(SRC)]
    started = time.perf_counter()
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return round(time.perf_counter() - started, 4)


def benchmark_linux_backend_scan():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "Steam"
        extra = Path(temp_dir) / "Extra"
        (root / "steamapps").mkdir(parents=True)
        (extra / "steamapps").mkdir(parents=True)
        template = (FIXTURES / "libraryfolders_linux.vdf.tpl").read_text(encoding="utf-8")
        (root / "steamapps" / "libraryfolders.vdf").write_text(
            template.format(PRIMARY_LIBRARY=str(root), SECONDARY_LIBRARY=str(extra)),
            encoding="utf-8",
        )
        from unittest.mock import patch

        with patch("core.platform.linux.list_steam_roots", return_value=[root]):
            with patch("core.platform.linux.get_steam_launch_command", return_value=["steam"]):
                backend = LinuxBackend(preferred_mode="native")
                started = time.perf_counter()
                install = backend.describe_steam_install()
                elapsed = time.perf_counter() - started
        return round(elapsed, 4), install.libraries


def benchmark_fake_library_scan(count: int = 1000):
    class FakeSettings:
        def value(self, key, default=None, type=None):  # noqa: A003
            if type is bool:
                return bool(default)
            return default

    class FakeMainWindow:
        settings = FakeSettings()

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir) / "Steam"
        steamapps = root / "steamapps"
        common = steamapps / "common"
        common.mkdir(parents=True)

        for index in range(count):
            game_dir = common / f"Game {index:04d}"
            game_dir.mkdir()
            (game_dir / f"game{index}.exe").write_text("x", encoding="utf-8")
            (steamapps / f"appmanifest_{100000 + index}.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"%s"\n\t"installdir"\t\t"%s"\n}\n'
                % (100000 + index, game_dir.name),
                encoding="utf-8",
            )

        manager = GameManager(FakeMainWindow())
        started = time.perf_counter()
        found = manager._scan_library(str(root), str(root))
        elapsed = time.perf_counter() - started
        return round(elapsed, 4), found


def main():
    compileall_seconds = benchmark_compileall()
    scan_seconds, libraries = benchmark_linux_backend_scan()
    fake_scan_seconds, fake_games = benchmark_fake_library_scan()
    payload = {
        "compileall_seconds": compileall_seconds,
        "linux_backend_scan_seconds": scan_seconds,
        "linux_backend_libraries": libraries,
        "fake_library_scan_1000_seconds": fake_scan_seconds,
        "fake_library_scan_1000_games_found": fake_games,
        "cwd": os.getcwd(),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
