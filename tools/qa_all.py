#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "app" / "ACCELA" / "squashfs-root" / "bin" / "src"
REQUIREMENTS = ROOT / "app" / "ACCELA" / "squashfs-root" / "bin" / "requirements.txt"
REPORT_MD = ROOT / "QA_REPORT.md"
REPORT_JSON = ROOT / "QA_REPORT.json"
APP_VENV_PYTHON = (
    ROOT / "app" / "ACCELA" / "squashfs-root" / "bin" / ".venv" / "bin" / "python"
)
QA_VENV_DIR = ROOT / ".qa-venv"


@dataclass
class StepResult:
    name: str
    ok: bool
    details: str


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Timeout executando {' '.join(cmd)}") from exc


def qa_python() -> str:
    return str(APP_VENV_PYTHON) if APP_VENV_PYTHON.exists() else sys.executable


def python_has_module(python_bin: str, module: str) -> bool:
    result = run([python_bin, "-c", f"import {module}"])
    return result.returncode == 0


def ensure_gui_test_python() -> str:
    python_bin = qa_python()
    if python_has_module(python_bin, "PyQt6"):
        return python_bin

    if not QA_VENV_DIR.exists():
        ensure_ok(run([sys.executable, "-m", "venv", str(QA_VENV_DIR)]), "python -m venv .qa-venv")

    venv_python = str(QA_VENV_DIR / "bin" / "python")
    venv_pip = str(QA_VENV_DIR / "bin" / "pip")
    if not python_has_module(venv_python, "PyQt6"):
        ensure_ok(run([venv_pip, "install", "--upgrade", "pip", "setuptools", "wheel"]), "pip upgrade .qa-venv")
        ensure_ok(run([venv_pip, "install", "-r", str(REQUIREMENTS)]), "pip install .qa-venv")
    return venv_python


def step(name: str, fn: Callable[[], str]) -> StepResult:
    try:
        details = fn()
        return StepResult(name=name, ok=True, details=details)
    except Exception as exc:  # noqa: BLE001
        return StepResult(name=name, ok=False, details=str(exc))


def ensure_ok(result: subprocess.CompletedProcess, label: str) -> str:
    if result.returncode != 0:
        raise RuntimeError(f"{label} falhou:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")
    return result.stdout.strip() or "ok"


def check_shell_syntax() -> str:
    scripts = [
        ROOT / "install.sh",
        ROOT / "dev-install.sh",
        ROOT / "publish-update.sh",
        ROOT / "app" / "ACCELA" / "squashfs-root" / "AppRun",
        ROOT / "app" / "ACCELA" / "squashfs-root" / "bin" / "run.sh",
    ]
    for script in scripts:
        ensure_ok(run(["bash", "-n", str(script)]), f"bash -n {script.name}")
    return "bash -n passou"


def check_compileall() -> str:
    return ensure_ok(run([qa_python(), "-m", "compileall", str(SRC)]), "compileall")


def check_unit_tests() -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    python_bin = ensure_gui_test_python()
    return ensure_ok(
        run([python_bin, "-m", "unittest", "discover", "-s", str(ROOT / "tests"), "-v"], env=env),
        "unit tests",
    )


def check_fresh_venv() -> str:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="accela-qa-venv-") as tmp:
        venv_dir = Path(tmp) / "venv"
        ensure_ok(run([sys.executable, "-m", "venv", str(venv_dir)]), "python -m venv")
        pip = venv_dir / "bin" / "pip"
        python = venv_dir / "bin" / "python"
        ensure_ok(run([str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"]), "pip upgrade")
        ensure_ok(run([str(pip), "install", "-r", str(REQUIREMENTS)]), "pip install -r")
        return ensure_ok(
            run(
                [
                    str(python),
                    "-c",
                    "import importlib; [importlib.import_module(m) for m in ('PyQt6','requests','bs4','cachetools')]; print('deps ok')",
                ]
            ),
            "import smoke",
        )


def check_benchmark() -> str:
    return ensure_ok(run([ensure_gui_test_python(), str(ROOT / "tools" / "benchmark_accela.py")]), "benchmark")


def check_desktop_file() -> str:
    validator = shutil.which("desktop-file-validate")
    if not validator:
        return "desktop-file-validate indisponível"
    return ensure_ok(
        run([validator, str(ROOT / "app" / "ACCELA" / "squashfs-root" / "ACCELA.desktop")]),
        "desktop-file-validate",
    )


def check_docker_smoke() -> str:
    docker = shutil.which("docker")
    if not docker:
        return "docker indisponível"

    commands = {
        "ubuntu:24.04": "apt-get update >/dev/null && apt-get install -y bash python3 curl wget git rsync p7zip-full openssl ca-certificates >/dev/null && bash install.sh --diagnose --json",
        "fedora:41": "dnf install -y bash python3 curl wget git rsync p7zip p7zip-plugins openssl ca-certificates >/dev/null && bash install.sh --diagnose --json",
        "archlinux:latest": "pacman -Sy --noconfirm bash python curl wget git rsync p7zip openssl ca-certificates >/dev/null && bash install.sh --diagnose --json",
    }
    outputs = []
    for image, command in commands.items():
        result = run(
            [
                docker,
                "run",
                "--rm",
                "-v",
                f"{ROOT}:/workspace",
                "-w",
                "/workspace",
                image,
                "bash",
                "-lc",
                command,
            ],
            timeout=600,
        )
        ensure_ok(result, f"docker smoke {image}")
        outputs.append(f"{image}: OK")
    return "; ".join(outputs)


def write_report(results: list[StepResult]) -> None:
    report = {
        "results": [asdict(item) for item in results],
        "passed": all(item.ok for item in results),
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = ["# QA REPORT", ""]
    for item in results:
        status = "PASS" if item.ok else "FAIL"
        lines.append(f"- {status} `{item.name}`")
        lines.append(f"  {item.details}")
    lines.append("")
    lines.append(f"Resultado final: {'APROVADO' if report['passed'] else 'REPROVADO'}")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="ACCELA QA Lab")
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--release", action="store_true")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    mode = "quick"
    if args.release:
        mode = "release"
    if args.full:
        mode = "full"

    results = [
        step("shell-syntax", check_shell_syntax),
        step("compileall", check_compileall),
        step("unit-tests", check_unit_tests),
        step("desktop-file", check_desktop_file),
    ]

    if mode in {"release", "full"}:
        results.append(step("fresh-venv", check_fresh_venv))
        results.append(step("benchmark", check_benchmark))
        results.append(step("docker-smoke", check_docker_smoke))

    write_report(results)
    return 0 if all(item.ok for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
