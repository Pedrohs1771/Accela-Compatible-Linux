import logging

from utils.paths import Paths

logger = logging.getLogger(__name__)


def _load_version() -> str:
    """Load the application version from the resource file."""
    version_file = Paths.resource("version")

    if not version_file.exists():
        logger.warning("Version file not found, using unknown version")
        return "unknown version"

    try:
        with open(version_file, "r", encoding="utf-8") as f:
            return f.read().strip() or "unknown version"
    except Exception as e:
        logger.warning(f"Failed to read version file: {e}")
        return "unknown version"


app_version = _load_version()
