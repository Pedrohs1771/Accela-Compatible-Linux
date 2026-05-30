import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_path(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.normpath(os.fspath(path)))


def parse_libraryfolders_vdf(vdf_path: str | os.PathLike[str]) -> list[str]:
    libraries: list[str] = []
    try:
        content = Path(vdf_path).read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        logger.error("Failed to parse libraryfolders.vdf %s: %s", vdf_path, exc)
        return libraries

    matches = re.findall(r'^\s*"(?:path|\d+)"\s*"(.*?)"', content, re.MULTILINE)
    seen: set[str] = set()
    for raw_path in matches:
        normalized = normalize_path(raw_path.replace("\\\\", "\\"))
        steamapps_dir = os.path.join(normalized, "steamapps")
        if not os.path.isdir(steamapps_dir):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        libraries.append(normalized)
    return libraries
