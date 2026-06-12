from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class WindowsRedistRequirement:
    key: str
    display_name: str
    evidence: tuple[str, ...]
    protontricks_verbs: tuple[str, ...]


_REQUIREMENT_PATTERNS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        "dotnet40",
        "Microsoft .NET Framework 4.x",
        (
            "dotnetfx40",
            "dotnetfx40_full",
            "net framework setup\\ndp\\v4",
            "net framework setup\\\\ndp\\\\v4",
        ),
        ("dotnet40",),
    ),
    (
        "xna40",
        "Microsoft XNA Framework 4.0",
        (
            "xnafx40",
            "microsoft\\xna\\framework\\v4.0",
            "microsoft\\\\xna\\\\framework\\\\v4.0",
            "xna framework",
        ),
        ("xna40",),
    ),
    (
        "vcrun",
        "Microsoft Visual C++ Runtime",
        (
            "vcredist",
            "vc_redist",
            "visual c++",
            "visual c runtime",
        ),
        ("vcrun2019",),
    ),
    (
        "directx",
        "DirectX Runtime",
        (
            "dxsetup",
            "directx",
            "d3dx",
            "xact",
            "xinput",
        ),
        ("d3dx9", "xact"),
    ),
)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _top_level_file_names(game_dir: Path) -> str:
    try:
        return "\n".join(item.name.lower() for item in game_dir.iterdir() if item.is_file())
    except OSError:
        return ""


def _build_detection_blob(game_dir: Path) -> str:
    installscript = _read_text(game_dir / "installscript.vdf")
    return f"{installscript}\n{_top_level_file_names(game_dir)}".lower()


def detect_windows_redists(game_dir: str | Path) -> list[WindowsRedistRequirement]:
    """Detect Windows redistributables that commonly need Proton prefix setup."""
    root = Path(game_dir)
    if not root.is_dir():
        return []

    blob = _build_detection_blob(root)
    if not blob.strip():
        return []

    detected: list[WindowsRedistRequirement] = []
    seen: set[str] = set()
    for key, display_name, patterns, verbs in _REQUIREMENT_PATTERNS:
        matches = tuple(pattern for pattern in patterns if pattern in blob)
        if matches and key not in seen:
            seen.add(key)
            detected.append(
                WindowsRedistRequirement(
                    key=key,
                    display_name=display_name,
                    evidence=matches,
                    protontricks_verbs=verbs,
                )
            )
    return detected


def protontricks_command(appid: str, requirements: Iterable[WindowsRedistRequirement]) -> str:
    verbs: list[str] = []
    for requirement in requirements:
        for verb in requirement.protontricks_verbs:
            if verb not in verbs:
                verbs.append(verb)
    return f"protontricks {appid} {' '.join(verbs)}".strip()


def write_proton_requirements_report(
    game_dir: str | Path,
    *,
    appid: str,
    game_name: str,
    requirements: Iterable[WindowsRedistRequirement],
    proton_tool: str = "",
    online_fix: bool = False,
) -> Path | None:
    reqs = list(requirements)
    if not reqs:
        return None

    root = Path(game_dir)
    root.mkdir(parents=True, exist_ok=True)
    command = protontricks_command(appid, reqs)

    lines = [
        "LumaTools - Proton Windows runtime report",
        "",
        f"Game: {game_name or 'Unknown'}",
        f"AppID: {appid or 'unknown'}",
        f"Proton tool: {proton_tool or 'Steam default'}",
        f"OnlineFix: {'yes' if online_fix else 'no'}",
        "",
        "Detected Windows runtime installers:",
    ]
    for requirement in reqs:
        evidence = ", ".join(requirement.evidence)
        lines.append(f"- {requirement.display_name} ({requirement.key}); evidence: {evidence}")

    lines.extend(
        [
            "",
            "Why this matters:",
            "This installation uses a Windows build on Linux. Some games fail before",
            "the window opens when the Proton prefix does not have these runtimes.",
            "Terraria is a common example because the Windows build uses .NET/XNA.",
            "",
            "Suggested manual repair if the game still does not launch:",
            command if command else "Install the detected runtimes into the app Proton prefix.",
            "",
            "If you do not need OnlineFix for this game, prefer the native Linux depot.",
        ]
    )

    report_path = root / "LUMA_PROTON_REQUIREMENTS.txt"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path
