#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_BIN = ROOT / "app" / "LumaTools" / "squashfs-root" / "bin"
WINDOWS_DIR = ROOT / "windows"
DIST_DIR = ROOT / "dist"
PACKAGE_DIR = DIST_DIR / "LumaTools-Windows-x64"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def ensure_windows() -> None:
    if os.name != "nt":
        raise SystemExit("build_windows.py deve ser executado no Windows.")


def recreate_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True)


def build_package(skip_venv: bool = False) -> Path:
    recreate_dir(PACKAGE_DIR)
    (PACKAGE_DIR / "bin").mkdir(parents=True, exist_ok=True)

    copy_tree(SRC_BIN / "src", PACKAGE_DIR / "bin" / "src")
    shutil.copy2(SRC_BIN / "requirements.txt", PACKAGE_DIR / "bin" / "requirements.txt")
    shutil.copy2(ROOT / "README.md", PACKAGE_DIR / "README.md")
    shutil.copy2(ROOT / "install_windows.ps1", PACKAGE_DIR / "install_windows.ps1")
    shutil.copy2(WINDOWS_DIR / "Launch-LumaTools.cmd", PACKAGE_DIR / "Launch-LumaTools.cmd")
    shutil.copy2(WINDOWS_DIR / "Run-LumaTools.ps1", PACKAGE_DIR / "Run-LumaTools.ps1")

    release_dir = ROOT / "release"
    if release_dir.exists():
        copy_tree(release_dir, PACKAGE_DIR / "release")

    if not skip_venv:
        run([sys.executable, "-m", "venv", str(PACKAGE_DIR / ".venv")])
        pip = PACKAGE_DIR / ".venv" / "Scripts" / "pip.exe"
        run([str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"])
        run([str(pip), "install", "-r", str(PACKAGE_DIR / "bin" / "requirements.txt")])

    archive = DIST_DIR / "LumaTools-Windows-x64.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in PACKAGE_DIR.rglob("*"):
            zf.write(path, path.relative_to(PACKAGE_DIR))
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Windows LumaTools package")
    parser.add_argument("--skip-venv", action="store_true")
    args = parser.parse_args()

    ensure_windows()
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    archive = build_package(skip_venv=args.skip_venv)
    print(f"Windows package ready: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
