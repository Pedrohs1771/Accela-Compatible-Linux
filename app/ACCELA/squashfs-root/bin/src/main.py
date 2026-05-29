import json
import multiprocessing
import os
import sys
from urllib.parse import unquote
import ctypes
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from ui.main_window import MainWindow
from ui.theme import update_appearance
from managers.cli_manager import run_cli_mode, open_cli_terminal
from utils.logger import setup_logging
from utils.settings import get_settings
from utils.yaml_config_manager import (
    backup_config_on_startup,
    ensure_slssteam_api_enabled,
    get_user_config_path,
)
from utils.version import app_version
from core.steam_helpers import fix_greenluma_offline_mode
from utils.helpers import create_font_from_settings


# -----------------------------------------------------------------------------
# Platform-specific adjustments
# -----------------------------------------------------------------------------
def set_app_user_model_id():
    """Set the AppUserModelID for Windows to ensure correct taskbar grouping."""
    if sys.platform == "win32":
        try:
            my_app_id = "god.is.in.the.wired.accela"
            # noinspection PyUnresolvedReferences
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(my_app_id)
        except (ImportError, AttributeError):
            pass  # Fails gracefully on non-Windows platforms or if ctypes is missing


set_app_user_model_id()

# Ensure project root is in path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _instance_server_name() -> str:
    if os.name == "posix":
        return f"accela.instance.{os.getuid()}"
    return "accela.instance"


def _cleanup_duplicate_gui_instances(logger) -> None:
    try:
        import psutil
    except ImportError:
        return

    current_pid = os.getpid()
    current_cwd = os.path.realpath(os.getcwd())
    duplicate_processes = []

    for process in psutil.process_iter(["pid", "cwd", "cmdline"]):
        try:
            pid = process.info.get("pid")
            if pid == current_pid:
                continue

            cwd = process.info.get("cwd") or ""
            if os.path.realpath(cwd) != current_cwd:
                continue

            cmdline = process.info.get("cmdline") or []
            if "src/main.py" not in " ".join(cmdline):
                continue
            if "-cli" in cmdline or "--cli" in cmdline:
                continue

            duplicate_processes.append(process)
        except (psutil.Error, OSError):
            continue

    for process in duplicate_processes:
        try:
            logger.warning(
                f"Terminating duplicate ACCELA instance PID {process.pid}"
            )
            process.terminate()
            process.wait(timeout=2)
        except psutil.TimeoutExpired:
            try:
                process.kill()
            except psutil.Error:
                pass
        except psutil.Error:
            continue


class SingleInstanceCoordinator:
    def __init__(self, logger):
        self.logger = logger
        self.server_name = _instance_server_name()
        self.server = None
        self.main_window = None

    def forward_to_primary(self, payload: dict) -> bool:
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(500):
            return False

        try:
            message = json.dumps(payload).encode("utf-8") + b"\n"
            socket.write(message)
            socket.flush()
            socket.waitForBytesWritten(500)
        finally:
            socket.disconnectFromServer()
        return True

    def start_listening(self, main_window: MainWindow) -> None:
        self.main_window = main_window
        self.server = QLocalServer()

        if not self.server.listen(self.server_name):
            QLocalServer.removeServer(self.server_name)
            if not self.server.listen(self.server_name):
                error_text = self.server.errorString()
                self.logger.warning(
                    f"Failed to start single-instance server: {error_text}"
                )
                self.server = None
                return

        self.server.newConnection.connect(self._on_new_connection)

    def cleanup(self) -> None:
        if self.server is not None:
            self.server.close()
            QLocalServer.removeServer(self.server_name)
            self.server = None

    def _on_new_connection(self) -> None:
        if self.server is None:
            return

        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                return
            socket.disconnected.connect(
                lambda sock=socket: self._process_connection_payload(sock)
            )

    def _process_connection_payload(self, socket: QLocalSocket) -> None:
        if self.main_window is None:
            socket.deleteLater()
            return

        try:
            raw = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
            if not raw:
                return

            payload = json.loads(raw)
            self.logger.info("Forwarded request received by running ACCELA instance")
            QTimer.singleShot(
                0, lambda data=payload: self.main_window.handle_external_command(data)
            )
        except json.JSONDecodeError as exc:
            self.logger.warning(f"Invalid single-instance payload received: {exc}")
        finally:
            socket.deleteLater()


def main():
    logger = setup_logging()

    logger.info("========================================")
    logger.info(f"ACCELA {app_version} starting...")
    logger.info("========================================")

    # People only have substance within the memories of other people.

    app = QApplication(sys.argv)
    app.setApplicationName("accela")
    app.setApplicationDisplayName("ACCELA")
    if hasattr(app, "setDesktopFileName"):
        app.setDesktopFileName("accela")

    # -------------------------------------------------------------------------
    # Argument Parsing
    # -------------------------------------------------------------------------
    cli_mode = False
    command_line_zips = []
    command_line_appid = None
    start_hidden = False

    def _add_zip_from_url(zip_url: str, found_suffix: str = "") -> bool:
        if not zip_url:
            return False
        if os.path.exists(zip_url):
            command_line_zips.append(zip_url)
            suffix = f" {found_suffix}" if found_suffix else ""
            logger.info(f"Found ZIP file from URL: {zip_url}{suffix}")
            return True
        logger.warning(f"ZIP file not found from URL: {zip_url}")
        return False

    def _parse_url_action(url: str):
        nonlocal cli_mode, command_line_appid
        try:
            url_content = url[9:]  # Remove 'accela://'
            if url_content.startswith("cli/"):
                cli_mode = True
                rest = url_content[4:]
            else:
                rest = url_content

            if "/" in rest:
                action, param_val = rest.split("/", 1)
                param_val = unquote(param_val)
            else:
                action = rest
                param_val = None

            if action == "download" and param_val and param_val.isdigit():
                command_line_appid = int(param_val)
                mode_str = "CLI" if cli_mode else "GUI"
                logger.info(
                    f"Found accela://{action} URL for AppID: {param_val} ({mode_str} mode)"
                )
            elif action == "zip" and param_val:
                _add_zip_from_url(param_val, "(GUI mode)" if not cli_mode else "")
            else:
                logger.warning(f"Invalid accela:// URL format: {url}")
        except ValueError as ve:
            logger.error(f"Failed to parse URL {url}: {ve}")

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-cli", "--cli"):
            cli_mode = True
        elif arg == "--start-hidden":
            start_hidden = True
        elif arg == "--appid" and i + 1 < len(args):
            appid_str = args[i + 1]
            if appid_str.isdigit():
                command_line_appid = int(appid_str)
            else:
                logger.error(f"Invalid AppID: {appid_str} (must be a number)")
            i += 1
        elif arg.startswith("accela://"):
            _parse_url_action(arg)
        elif arg.lower().endswith(".zip"):
            zip_file_path = os.path.abspath(arg)
            if os.path.exists(zip_file_path):
                command_line_zips.append(zip_file_path)
                logger.info(f"Found ZIP file from command line: {zip_file_path}")
            else:
                logger.warning(f"ZIP file not found: {arg}")
        i += 1

    if command_line_appid and command_line_zips:
        logger.error("Cannot use --appid and .zip files together. Choose one.")
        return None

    # -------------------------------------------------------------------------
    # CLI Mode Execution
    # -------------------------------------------------------------------------
    if cli_mode and (command_line_zips or command_line_appid):
        if cli_mode and sys.platform == "linux":
            if command_line_appid:
                logger.info(
                    f"Opening CLI mode in external terminal for AppID {command_line_appid}"
                )
                if open_cli_terminal(appid=command_line_appid):
                    return None
            elif command_line_zips:
                logger.info("Opening CLI mode in external terminal for ZIP(s)")
                if open_cli_terminal(zip_path=command_line_zips[0]):
                    return None

        if command_line_appid:
            logger.info(f"Will process AppID {command_line_appid} via CLI")
            return run_cli_mode(app, None, logger, appid=command_line_appid)
        else:
            logger.info(f"Processing {len(command_line_zips)} ZIPs via CLI")
            return run_cli_mode(app, command_line_zips, logger)

    # -------------------------------------------------------------------------
    # Single Instance Coordination
    # -------------------------------------------------------------------------
    instance_payload = {
        "zip_files": command_line_zips,
        "appid": command_line_appid,
        "start_hidden": start_hidden,
        "activate": bool(command_line_zips or command_line_appid or not start_hidden),
    }
    instance_coordinator = SingleInstanceCoordinator(logger)
    if instance_coordinator.forward_to_primary(instance_payload):
        logger.info("Existing ACCELA instance detected; forwarded request and exiting.")
        return None

    # -------------------------------------------------------------------------
    # GUI Mode Initialization
    # -------------------------------------------------------------------------

    config_path = get_user_config_path()
    try:
        backup_created = backup_config_on_startup(config_path)
        if backup_created:
            logger.info("SLSsteam config backup created at startup")

        if config_path.exists():
            if ensure_slssteam_api_enabled(config_path):
                logger.info("SLSsteam API enabled in config")
    except OSError as e:
        logger.error(f"Startup I/O error (Config/Backup): {e}")

    # 2. Settings & Theme
    settings = get_settings()
    accent_color = settings.value("accent_color", "#C06C84")
    bg_color = settings.value("background_color", "#000000")
    ui_mode = settings.value("ui_mode", "default")

    font_file = None
    font_to_use = QFont()

    if ui_mode == "sonic":
        accent_color = "#ffcc00"
        bg_color = "#002c83"
        font_file = settings.value("font-file", "sonic/sonic-1-hud-font.otf")
    else:
        font_to_use = create_font_from_settings(settings)

    # 3. GreenLuma Check
    try:
        fix_greenluma_offline_mode()
    except OSError as e:
        logger.warning(f"Failed to check GreenLuma status: {e}")

    # 4. Apply Appearance
    font_ok, font_info = update_appearance(
        app, accent_color, bg_color, font=font_to_use, font_file=font_file
    )
    if font_ok:
        logger.info(f"Loaded custom font: '{str(font_info)}'")
    else:
        logger.warning(f"Failed to load custom font: '{str(font_info)}'")

    # -------------------------------------------------------------------------
    # Main Window Launch
    # -------------------------------------------------------------------------
    try:
        main_win = MainWindow(start_hidden=start_hidden)
        instance_coordinator.start_listening(main_win)
        app.aboutToQuit.connect(instance_coordinator.cleanup)
        _cleanup_duplicate_gui_instances(logger)
        main_win.show()
        QTimer.singleShot(0, main_win.apply_startup_visibility)
        logger.info("Main window displayed successfully.")

        # ---------------------------------------------------------------------
        # Post-Launch Processing
        # ---------------------------------------------------------------------
        if command_line_zips or command_line_appid:
            def process_command_line_args():
                """Dispatcher for command line args."""
                if command_line_appid:
                    main_win.queue_manifest_download(command_line_appid)
                else:
                    logger.info(f"Adding {len(command_line_zips)} ZIP file(s) to queue")
                    for zip_file in command_line_zips:
                        main_win.add_job_safely(zip_file)

            QTimer.singleShot(0, process_command_line_args)

        sys.exit(app.exec())
    except Exception as e:
        logger.critical(
            f"A critical error occurred. Error: {e}",
            exc_info=True,
        )
        sys.exit(1)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
