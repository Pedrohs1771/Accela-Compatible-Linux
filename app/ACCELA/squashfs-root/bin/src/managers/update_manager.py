import logging
import os
import shlex
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Dict, Optional

import requests
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from utils.version import app_version

logger = logging.getLogger(__name__)


class UpdateManager(QObject):
    """Check GitHub for updates and install the latest tagged version."""

    status_changed = pyqtSignal(str)
    release_detected = pyqtSignal(object)

    DEFAULT_REPO = "Pedrohs1771/Accela-Compatible-Linux"

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.latest_release: Optional[Dict[str, str]] = None
        self.status_message = "Aguardando verificação."
        self._check_in_progress = False
        self._install_in_progress = False
        self.release_detected.connect(self._handle_release_detected)

    @property
    def current_version(self) -> str:
        return app_version

    def reload_settings(self) -> None:
        pass

    def get_repo_slug(self) -> str:
        configured = self.settings.value(
            "github_updates_repo", self.DEFAULT_REPO, type=str
        ).strip()
        return configured or self.DEFAULT_REPO

    def schedule_startup_check(self) -> None:
        enabled = self.settings.value("github_updates_enabled", True, type=bool)
        if not enabled:
            return
        QTimer.singleShot(2500, lambda: self.check_for_updates_async(interactive=False))

    def check_for_updates_async(self, interactive: bool = False) -> None:
        if self._check_in_progress:
            return

        self._check_in_progress = True
        self._set_status("Verificando atualizações no GitHub...")
        thread = threading.Thread(
            target=self._check_worker,
            args=(interactive,),
            daemon=True,
        )
        thread.start()

    def install_update(self, release: Optional[Dict[str, str]] = None) -> bool:
        if self._install_in_progress:
            return False

        release = release or self.latest_release
        if not release:
            self._set_status("Nenhuma release selecionada para instalar.")
            return False

        zip_url = str(release.get("zip_url", "")).strip()
        if not zip_url:
            self._set_status("A release do GitHub não informou um pacote instalável.")
            return False

        self._install_in_progress = True
        self._set_status(f"Instalando {release.get('tag_name', 'nova versão')}...")

        script_path = self._write_update_script(release)
        try:
            subprocess.Popen(
                ["bash", str(script_path)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.error("Failed to launch updater script: %s", exc, exc_info=True)
            self._install_in_progress = False
            self._set_status(f"Falha ao iniciar a atualização: {exc}")
            return False

        QTimer.singleShot(800, lambda: self.main_window.request_quit("self_update"))
        return True

    def _check_worker(self, interactive: bool) -> None:
        try:
            release = self._fetch_latest_release()
            self.latest_release = release
            current_version = self._normalize_version(self.current_version)
            latest_version = self._normalize_version(release.get("tag_name", ""))
            update_available = bool(latest_version) and current_version != latest_version

            if update_available:
                self._set_status(
                    f"Atualização disponível: {release.get('tag_name')}."
                )
                payload = dict(release)
                payload["interactive"] = interactive
                self.release_detected.emit(payload)
            else:
                self._set_status(
                    f"Você já está na versão mais recente ({self.current_version})."
                )
                if interactive:
                    QTimer.singleShot(
                        0,
                        lambda: QMessageBox.information(
                            self.main_window,
                            "Atualizações",
                            f"Você já está na versão mais recente ({self.current_version}).",
                        ),
                    )
        except Exception as exc:
            logger.error("Update check failed: %s", exc, exc_info=True)
            self._set_status(f"Falha ao verificar atualizações: {exc}")
            if interactive:
                QTimer.singleShot(
                    0,
                    lambda: QMessageBox.warning(
                        self.main_window,
                        "Atualizações",
                        f"Não foi possível verificar atualizações.\n\n{exc}",
                    ),
                )
        finally:
            self._check_in_progress = False

    def _handle_release_detected(self, release: object) -> None:
        if not isinstance(release, dict):
            return

        auto_update = self.settings.value("github_auto_update", False, type=bool)
        interactive = bool(release.get("interactive"))

        if auto_update and not interactive:
            self.install_update(release)
            return

        if not self.main_window.isVisible():
            return

        latest = release.get("tag_name", "nova versão")
        message = QMessageBox(self.main_window)
        message.setWindowTitle("Atualização disponível")
        message.setText(f"A versão {latest} está disponível no GitHub.")
        message.setInformativeText("Deseja baixar e instalar agora?")
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.Yes)
        if message.exec() == QMessageBox.StandardButton.Yes:
            self.install_update(release)

    def _fetch_latest_release(self) -> Dict[str, str]:
        repo = self.get_repo_slug()
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ACCELA",
        }

        release_url = f"https://api.github.com/repos/{repo}/releases/latest"
        response = requests.get(release_url, headers=headers, timeout=30)
        if response.status_code == 404:
            tags_url = f"https://api.github.com/repos/{repo}/tags"
            tags_response = requests.get(tags_url, headers=headers, timeout=30)
            tags_response.raise_for_status()
            tags = tags_response.json()
            if not tags:
                raise RuntimeError("Nenhuma tag encontrada no repositório.")
            tag_name = tags[0].get("name", "").strip()
            if not tag_name:
                raise RuntimeError("A primeira tag do repositório está inválida.")
            return {
                "tag_name": tag_name,
                "zip_url": f"https://github.com/{repo}/archive/refs/tags/{tag_name}.zip",
                "html_url": f"https://github.com/{repo}/tree/{tag_name}",
            }

        response.raise_for_status()
        release = response.json()
        tag_name = str(release.get("tag_name", "")).strip()
        if not tag_name:
            raise RuntimeError("Release do GitHub sem tag_name.")

        return {
            "tag_name": tag_name,
            "zip_url": release.get("zipball_url", ""),
            "html_url": release.get("html_url", ""),
        }

    @staticmethod
    def _normalize_version(version: str) -> str:
        return str(version or "").strip().lstrip("vV")

    def _set_status(self, message: str) -> None:
        self.status_message = message
        self.status_changed.emit(message)

    def _write_update_script(self, release: Dict[str, str]) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="accela-update-"))
        script_path = temp_dir / "apply-update.sh"
        zip_url = shlex.quote(str(release.get("zip_url", "")))
        current_pid = os.getpid()

        script = f"""#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(mktemp -d)"
ARCHIVE="$WORKDIR/update.zip"
EXTRACT_DIR="$WORKDIR/extracted"
mkdir -p "$EXTRACT_DIR"

download() {{
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL {zip_url} -o "$ARCHIVE"
        return
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO "$ARCHIVE" {zip_url}
        return
    fi
    echo "Nem curl nem wget estão disponíveis." >&2
    exit 1
}}

download

python3 - "$ARCHIVE" "$EXTRACT_DIR" <<'PY'
import sys
import zipfile

archive, target = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(target)
PY

SRC_DIR="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/install.sh" ]; then
    echo "Pacote do GitHub sem install.sh." >&2
    exit 1
fi

while kill -0 {current_pid} >/dev/null 2>&1; do
    sleep 1
done

chmod +x "$SRC_DIR/install.sh"
bash "$SRC_DIR/install.sh" --no-prompt
"$HOME/.local/bin/accela" >/dev/null 2>&1 &
"""
        script_path.write_text(script, encoding="utf-8")
        os.chmod(script_path, 0o755)
        return script_path
