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


def main():
    compileall_seconds = benchmark_compileall()
    scan_seconds, libraries = benchmark_linux_backend_scan()
    payload = {
        "compileall_seconds": compileall_seconds,
        "linux_backend_scan_seconds": scan_seconds,
        "linux_backend_libraries": libraries,
        "cwd": os.getcwd(),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
