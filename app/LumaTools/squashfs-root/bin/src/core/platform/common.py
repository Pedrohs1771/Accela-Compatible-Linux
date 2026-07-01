import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def normalize_path(path: str | os.PathLike[str]) -> str:
    return os.path.realpath(os.path.normpath(os.fspath(path)))


def resolve_steam_library_path(
    path: str | os.PathLike[str],
    library_paths: list[str] | tuple[str, ...] = (),
) -> str:
    """Return the Steam library root represented by a user-selected path.

    Steam users commonly select either the library root, ``steamapps`` or
    ``steamapps/common`` in a folder picker. All three must resolve to the
    same root because download code appends ``steamapps/common`` itself.
    """
    candidate = Path(normalize_path(Path(path).expanduser()))
    normalized_libraries = [
        Path(normalize_path(Path(library).expanduser()))
        for library in library_paths
        if library
    ]

    for library in normalized_libraries:
        common_dir = library / "steamapps" / "common"
        if candidate in {library, library / "steamapps", common_dir}:
            return str(library)
        try:
            candidate.relative_to(common_dir)
        except ValueError:
            continue
        return str(library)

    current = candidate
    while True:
        if current.name.lower() == "steamapps":
            return str(current.parent)
        if current.parent == current:
            break
        current = current.parent

    if candidate.name.lower() == "common" and candidate.parent.name.lower() == "steamapps":
        return str(candidate.parent.parent)
    if candidate.name.lower() == "steamapps":
        return str(candidate.parent)
    return str(candidate)


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
