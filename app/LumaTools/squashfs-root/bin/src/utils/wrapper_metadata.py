import json
import logging
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

WRAPPER_METADATA_FILENAME = "lumatools_wrapper_metadata.json"


def _get_wrapper_metadata_path(game_directory: str | Path) -> Path:
    return Path(game_directory) / ".DepotDownloader" / WRAPPER_METADATA_FILENAME


def persist_selected_dlcs(
    game_directory: str | Path, selected_dlcs: Iterable[Any]
) -> bool:
    """Persist selected DLC IDs for later uninstall cleanup."""
    metadata_path = _get_wrapper_metadata_path(game_directory)

    normalized_dlcs: list[str] = []
    seen: set[str] = set()
    for dlc_id in selected_dlcs:
        dlc_id_str = str(dlc_id).strip()
        if not dlc_id_str or dlc_id_str in seen:
            continue
        seen.add(dlc_id_str)
        normalized_dlcs.append(dlc_id_str)

    payload = {"selected_dlcs": normalized_dlcs}

    try:
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        with open(metadata_path, "w", encoding="utf-8") as metadata_file:
            json.dump(payload, metadata_file, ensure_ascii=True, indent=2)
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to persist wrapper metadata at {metadata_path}: {e}")
        return False


def load_selected_dlcs(game_directory: str | Path) -> list[str]:
    """Load persisted selected DLC IDs for a game installation."""
    metadata_path = _get_wrapper_metadata_path(game_directory)
    if not metadata_path.exists():
        return []

    try:
        with open(metadata_path, "r", encoding="utf-8") as metadata_file:
            payload = json.load(metadata_file)
    except (OSError, ValueError, TypeError) as e:
        logger.warning(f"Failed to read wrapper metadata at {metadata_path}: {e}")
        return []

    selected_dlcs = payload.get("selected_dlcs", [])
    if not isinstance(selected_dlcs, list):
        return []

    normalized_dlcs: list[str] = []
    seen: set[str] = set()
    for dlc_id in selected_dlcs:
        dlc_id_str = str(dlc_id).strip()
        if not dlc_id_str or dlc_id_str in seen:
            continue
        seen.add(dlc_id_str)
        normalized_dlcs.append(dlc_id_str)

    return normalized_dlcs
