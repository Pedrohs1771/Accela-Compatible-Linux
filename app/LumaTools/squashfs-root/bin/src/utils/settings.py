from PyQt6.QtCore import QSettings

APP_NAME = "LumaTools"
ORG_NAME = "Tachibana Labs"
DEFAULT_GITHUB_REPO = "Pedrohs1771/LumaTools-Linux"
INVALID_GITHUB_REPOS = {
    "Pedrohs1771/LumaTools-Compatible-Linux",
    "Pedrohs1771/Luma-Tools-Compatible-Linux",
    "Pedrohs1771/LumaTools_Linux_GOD_Edition_v2",
    "Pedrohs1771/LumaTools",
}


def get_settings() -> QSettings:
    """Get the application settings object."""
    settings = QSettings(ORG_NAME, APP_NAME)
    configured = settings.value("github_updates_repo", "", type=str).strip()
    normalized = configured.replace(" ", "")
    if (
        not normalized
        or normalized in INVALID_GITHUB_REPOS
        or "accela" in normalized.lower()
    ):
        if configured != DEFAULT_GITHUB_REPO:
            settings.setValue("github_updates_repo", DEFAULT_GITHUB_REPO)
            settings.sync()
    elif configured != normalized:
        settings.setValue("github_updates_repo", normalized)
        settings.sync()
    return settings
