import logging
import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal

from utils.helpers import get_base_path

# Constants
APP_NAME = "accela"
MAX_PREVIOUS_LOGS = 4

logger = logging.getLogger(__name__)


class QtLogHandler(QObject, logging.Handler):
    """Custom logging handler that emits signals to Qt widgets."""

    new_record = pyqtSignal(str)
    flushOnClose = False

    def __init__(self):
        super().__init__()
        # Initialize QObject part of the mixin
        QObject.__init__(self)
        logging.Handler.__init__(self)

        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        self.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.new_record.emit(msg)
        except RuntimeError:
            # Qt object has been deleted
            pass

    def flush(self) -> None:
        # No-op to avoid issues with deleted Qt objects
        pass

    def close(self) -> None:
        # No-op to avoid issues with deleted Qt objects
        pass


# Global handler instance
qt_log_handler = QtLogHandler()
_current_log_name: Optional[str] = None
_log_dir = get_base_path() / "logs"


def _create_file_handler(log_path: Path) -> Optional[logging.FileHandler]:
    """Attempt to create a file handler at the specified path."""
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    try:
        handler = logging.FileHandler(
            log_path,
            mode="w",  # Create new file for each session
            encoding="utf-8",
            delay=False,
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        print(f"Log file created: {log_path}", file=sys.stderr)
        return handler
    except (PermissionError, OSError) as e:
        print(f"Error: Could not create log file at {log_path}: {e}", file=sys.stderr)
        return None


def setup_logging() -> logging.Logger:
    """Setup logging with timestamped log files."""
    # Clean up old logs on launch
    cleanup_old_logs()

    # Get the timestamped log path
    log_path = get_log_path()
    system_platform = platform.system()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    handlers: List[logging.Handler] = []

    # 1. File Handler (Main Path)
    file_handler = _create_file_handler(log_path)

    # 2. File Handler (Fallback to TEMP if main fails)
    if not file_handler:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        temp_dir = Path(os.environ.get("TEMP", os.getcwd()))
        fallback_path = temp_dir / f"{APP_NAME}_{timestamp}.log"
        print(f"Attempting fallback log: {fallback_path}", file=sys.stderr)
        file_handler = _create_file_handler(fallback_path)

    if file_handler:
        handlers.append(file_handler)

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    handlers.append(console_handler)

    # Qt Handler
    qt_log_handler.setLevel(logging.INFO)
    qt_log_handler.setFormatter(formatter)
    handlers.append(qt_log_handler)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Reduce noise from third-party libraries when offline
    logging.getLogger("CMServerList").setLevel(logging.CRITICAL)

    # Clear existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Add new handlers
    for handler in handlers:
        root_logger.addHandler(handler)

    # Re-acquire logger after config
    local_logger = logging.getLogger(__name__)

    # Log configuration details
    local_logger.info("Logging Initialized")
    local_logger.info("Platform: %s", system_platform)
    local_logger.info("Python: %s", sys.version)
    local_logger.info("Log file: %s", log_path)
    local_logger.info("File level: DEBUG")
    local_logger.info("Console level: INFO")
    local_logger.info("Qt GUI level: INFO")

    return local_logger


def open_log_directory() -> bool:
    """Open the log directory in the system file manager."""
    global _log_dir

    try:
        system = platform.system().lower()
        cmd = ["xdg-open"]  # Default for Linux/Unix

        if system == "windows":
            cmd = ["explorer"]

        subprocess.run(cmd + [str(_log_dir)], check=False)
        return True
    except Exception as e:
        local_logger = logging.getLogger(__name__)
        local_logger.error("Failed to open log directory: %s", e)
        return False


def get_log_path() -> Path:
    """Return path to a timestamped log file with counter if needed."""
    global _current_log_name, _log_dir

    try:
        _log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fallback to temp directory
        temp_dir = Path(os.environ.get("TEMP", os.getcwd())) / "logs" / APP_NAME
        temp_dir.mkdir(parents=True, exist_ok=True)
        _log_dir = temp_dir

    # Base name with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{APP_NAME}_{timestamp}"

    # Find next available filename
    counter = 1
    while True:
        if counter == 1:
            log_name = f"{base_name}.log"
        else:
            log_name = f"{base_name}_{counter}.log"

        log_path = _log_dir / log_name
        if not log_path.exists():
            break
        counter += 1

    _current_log_name = log_name
    return log_path


def cleanup_old_logs() -> None:
    """Clean up old log files on startup."""
    global MAX_PREVIOUS_LOGS

    base_path = get_base_path()
    log_dir = base_path / "logs"

    if not log_dir.exists():
        return

    # Get all app specific .log files
    log_files = [f for f in log_dir.glob(f"{APP_NAME}*.log") if f.is_file()]

    if not log_files:
        return

    # Sort by modification time (newest first)
    log_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    # Keep only the N most recent files
    for old_log in log_files[MAX_PREVIOUS_LOGS:]:
        try:
            old_log.unlink()
            print(f"Removed old log file: {old_log.name}", file=sys.stderr)
        except OSError as e:
            print(f"Could not remove {old_log.name}: {e}", file=sys.stderr)
