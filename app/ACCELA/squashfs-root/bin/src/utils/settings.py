from PyQt6.QtCore import QSettings

APP_NAME = "ACCELA"
ORG_NAME = "Tachibana Labs"


def get_settings() -> QSettings:
    """Get the application settings object."""
    return QSettings(ORG_NAME, APP_NAME)
