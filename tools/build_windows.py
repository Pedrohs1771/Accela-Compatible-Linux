#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_BIN = ROOT / "app" / "LumaTools" / "squashfs-root" / "bin"
SRC = SRC_BIN / "src"
WINDOWS_DIR = ROOT / "windows"
DIST_DIR = ROOT / "dist"
BUILD_DIR = DIST_DIR / "windows-build"
PACKAGE_DIR = DIST_DIR / "windows" / "LumaTools"
ARCHIVE_NAME = "LumaTools-Windows-v1.1.0-rc.zip"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(cwd or ROOT), check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def recreate_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def copy_tree(source: Path, target: Path) -> None:
    shutil.copytree(source, target, dirs_exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_pyinstaller() -> None:
    if os.name != "nt":
        raise SystemExit("Windows executable build must run on windows-latest or Windows.")

    pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
        pyinstaller = shutil.which("pyinstaller")
    if not pyinstaller:
        raise SystemExit("pyinstaller not found after installation")

    recreate_dir(BUILD_DIR)
    recreate_dir(PACKAGE_DIR)

    common = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--distpath",
        str(BUILD_DIR),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR / "spec"),
        "--paths",
        str(SRC),
        "--add-data",
        f"{SRC / 'res'}{os.pathsep}res",
        "--add-data",
        f"{SRC / 'deps'}{os.pathsep}deps",
        "--collect-all",
        "PyQt6",
        "--hidden-import",
        "PyQt6.QtNetwork",
    ]

    run(common + ["--onedir", "--windowed", "--name", "LumaTools", str(SRC / "main.py")])
    run(common + ["--onefile", "--console", "--name", "LumaDoctor", str(WINDOWS_DIR / "luma_doctor_entry.py")])
    run(common + ["--onefile", "--console", "--name", "LumaRepair", str(WINDOWS_DIR / "luma_repair_entry.py")])

    copy_tree(BUILD_DIR / "LumaTools", PACKAGE_DIR)
    for tool_name in ("LumaDoctor", "LumaRepair"):
        exe = BUILD_DIR / f"{tool_name}.exe"
        if exe.exists():
            shutil.copy2(exe, PACKAGE_DIR / f"{tool_name}.exe")


def copy_release_files() -> None:
    shutil.copy2(ROOT / "README.md", PACKAGE_DIR / "README.md")
    for filename in (
        "README_WINDOWS.md",
        "TROUBLESHOOTING_WINDOWS.md",
        "WINDOWS_RELEASE_NOTES.md",
        "WINDOWS_KNOWN_LIMITATIONS.md",
        "install_windows.ps1",
        "uninstall_windows.ps1",
        "bootstrap_windows.ps1",
    ):
        source = ROOT / filename
        if source.exists():
            shutil.copy2(source, PACKAGE_DIR / filename)

    redist_dir = PACKAGE_DIR / "vc_redist"
    redist_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("vc_redist.x64.exe", "vc_redist.x86.exe"):
        source = ROOT / "windows" / "redist" / filename
        if source.exists():
            shutil.copy2(source, redist_dir / filename)


def make_archive() -> Path:
    archive = DIST_DIR / ARCHIVE_NAME
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in PACKAGE_DIR.rglob("*"):
            if path.is_file():
                zf.write(path, Path("LumaTools") / path.relative_to(PACKAGE_DIR))

    sums = DIST_DIR / "SHA256SUMS.txt"
    sums.write_text(
        f"{sha256_file(archive)}  {archive.name}\n",
        encoding="utf-8",
    )
    return archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Windows LumaTools RC package")
    parser.add_argument("--skip-pyinstaller", action="store_true", help="Only create source package layout for diagnostics.")
    args = parser.parse_args()

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    if args.skip_pyinstaller:
        recreate_dir(PACKAGE_DIR)
        (PACKAGE_DIR / "bin").mkdir(parents=True, exist_ok=True)
        copy_tree(SRC, PACKAGE_DIR / "bin" / "src")
        shutil.copy2(SRC_BIN / "requirements.txt", PACKAGE_DIR / "bin" / "requirements.txt")
    else:
        build_pyinstaller()

    copy_release_files()
    archive = make_archive()
    print(f"Windows package ready: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
