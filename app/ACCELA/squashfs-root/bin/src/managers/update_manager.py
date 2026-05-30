import json
import logging
import os
import shlex
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from utils.helpers import get_base_path
from utils.version import app_version

logger = logging.getLogger(__name__)


class UpdateManager(QObject):
    """Check GitHub for updates, verify manifests and support rollback."""

    status_changed = pyqtSignal(str)
    release_detected = pyqtSignal(object)
    update_available_changed = pyqtSignal(bool)
    notification_requested = pyqtSignal(str, str)

    DEFAULT_REPO = "Pedrohs1771/Accela-Compatible-Linux"
    DEFAULT_BRANCH = "main"
    MANIFEST_PATH = "release/latest.json"
    CHECK_CACHE_TTL_SECONDS = 10
    HEARTBEAT_CHECK_SECONDS = 30
    STARTUP_CHECK_DELAY_MS = 300
    PENDING_AUTO_UPDATE_RETRY_SECONDS = 15

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.latest_release: Optional[Dict[str, str]] = None
        self.status_message = "Aguardando verificação."
        self.security_message = "Assinatura e SHA256 ainda não verificados."
        self._check_in_progress = False
        self._install_in_progress = False
        self._update_available = False
        self._last_check_at = 0.0
        self._last_check_interactive = False
        self._last_check_payload: Optional[Dict[str, object]] = None
        self._prepare_timer: Optional[QTimer] = None
        self._heartbeat_timer: Optional[QTimer] = None
        self._pending_auto_update_timer: Optional[QTimer] = None
        self._pending_auto_update_release: Optional[Dict[str, str]] = None
        self._announced_revision = ""
        self.release_detected.connect(self._handle_release_detected)

    @property
    def current_version(self) -> str:
        return app_version

    def reload_settings(self) -> None:
        self._last_check_at = 0.0
        self._last_check_payload = None
        self._configure_heartbeat()

    @classmethod
    def _version_metadata_file(cls) -> Path:
        return cls._base_path() / "VERSION.json"

    def get_repo_slug(self) -> str:
        configured = self.settings.value(
            "github_updates_repo", self.DEFAULT_REPO, type=str
        ).strip()
        return configured or self.DEFAULT_REPO

    def get_branch_name(self) -> str:
        configured = self.settings.value(
            "github_updates_branch", self.DEFAULT_BRANCH, type=str
        ).strip()
        return configured or self.DEFAULT_BRANCH

    def require_signed_updates(self) -> bool:
        return self.settings.value("github_signed_updates_only", True, type=bool)

    @staticmethod
    def _base_path() -> Path:
        return get_base_path()

    @classmethod
    def _revision_file(cls) -> Path:
        return cls._base_path() / ".repo_revision"

    @classmethod
    def _public_key_path(cls) -> Path:
        return cls._base_path() / "release" / "signing" / "public.pem"

    @classmethod
    def _backups_root(cls) -> Path:
        return cls._base_path() / "backups"

    def get_installed_revision(self) -> str:
        revision_file = self._revision_file()
        if not revision_file.exists():
            metadata_path = self._version_metadata_file()
            if metadata_path.exists():
                try:
                    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
                    return str(payload.get("commit_sha", "")).strip()
                except (OSError, json.JSONDecodeError):
                    logger.warning(
                        "Failed to read VERSION.json for installed revision",
                        exc_info=True,
                    )
            return ""

        try:
            return revision_file.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Failed to read installed repo revision", exc_info=True)
            return ""

    def is_update_available(self) -> bool:
        return self._update_available

    def available_backups(self) -> List[Path]:
        root = self._backups_root()
        if not root.exists():
            return []

        try:
            return sorted(
                [path for path in root.iterdir() if path.is_dir()],
                key=lambda item: item.name,
                reverse=True,
            )
        except OSError:
            logger.warning("Failed to enumerate backups", exc_info=True)
            return []

    def get_backup_summary(self) -> str:
        backups = self.available_backups()
        if not backups:
            return "Rollback: nenhum backup disponível."

        return f"Rollback: {len(backups)} backup(s). Mais recente: {backups[0].name}"

    def get_security_summary(self) -> str:
        return self.security_message

    def _set_update_available(self, available: bool) -> None:
        if self._update_available == available:
            return
        self._update_available = available
        self.update_available_changed.emit(available)

    def schedule_startup_check(self) -> None:
        enabled = self.settings.value("github_updates_enabled", True, type=bool)
        if not enabled:
            return
        self._configure_heartbeat()
        QTimer.singleShot(
            self.STARTUP_CHECK_DELAY_MS,
            lambda: self.check_for_updates_async(interactive=False, force=True),
        )

    def _configure_heartbeat(self) -> None:
        enabled = self.settings.value("github_updates_enabled", True, type=bool)

        if self._heartbeat_timer is None:
            self._heartbeat_timer = QTimer(self)
            self._heartbeat_timer.setInterval(self.HEARTBEAT_CHECK_SECONDS * 1000)
            self._heartbeat_timer.timeout.connect(
                lambda: self.check_for_updates_async(interactive=False, force=False)
            )

        if self._pending_auto_update_timer is None:
            self._pending_auto_update_timer = QTimer(self)
            self._pending_auto_update_timer.setInterval(
                self.PENDING_AUTO_UPDATE_RETRY_SECONDS * 1000
            )
            self._pending_auto_update_timer.timeout.connect(
                self._retry_pending_auto_update
            )

        if enabled:
            self._heartbeat_timer.start()
        else:
            self._heartbeat_timer.stop()
            if self._pending_auto_update_timer is not None:
                self._pending_auto_update_timer.stop()

    def check_for_updates_async(self, interactive: bool = False, force: bool = False) -> None:
        if self._check_in_progress:
            return

        if (
            not force
            and not interactive
            and self._last_check_payload is not None
            and (time.time() - self._last_check_at) < self.CHECK_CACHE_TTL_SECONDS
        ):
            self.latest_release = (
                dict(self._last_check_payload.get("release", {})) or None
            )
            self.security_message = str(
                self._last_check_payload.get(
                    "security_message",
                    "Assinatura e SHA256 ainda não verificados.",
                )
            )
            self._set_update_available(
                bool(self._last_check_payload.get("update_available", False))
            )
            self._set_status(
                str(
                    self._last_check_payload.get(
                        "status_message", "Verificação recente reaproveitada."
                    )
                )
            )
            return

        self._check_in_progress = True
        self._set_status("Verificando atualizações seguras no GitHub...")
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

        package_url = str(
            release.get("package_url") or release.get("zip_url") or ""
        ).strip()
        if not package_url:
            self._set_status("O update não informou um pacote instalável.")
            return False

        if self.require_signed_updates() and not release.get("signature_url"):
            self._set_status(
                "Update bloqueado: a política local exige assinatura válida."
            )
            return False

        self._install_in_progress = True
        self._pending_auto_update_release = None
        if self._pending_auto_update_timer is not None:
            self._pending_auto_update_timer.stop()
        self._set_status(
            f"Instalando {release.get('display_name', release.get('tag_name', 'novo update'))}..."
        )

        script_path, status_dir = self._write_update_script(release)
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

        self._monitor_prepared_update(status_dir)
        return True

    def rollback_to_latest_backup(self) -> bool:
        backups = self.available_backups()
        if not backups:
            self._set_status("Rollback indisponível: nenhum backup encontrado.")
            return False

        script_path = self._write_rollback_script(backups[0])
        try:
            subprocess.Popen(
                ["bash", str(script_path)],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            logger.error("Failed to launch rollback script: %s", exc, exc_info=True)
            self._set_status(f"Falha ao iniciar rollback: {exc}")
            return False

        self._set_status(f"Restaurando backup {backups[0].name}...")
        QTimer.singleShot(800, lambda: self.main_window.request_quit("rollback"))
        return True

    def _monitor_prepared_update(self, status_dir: Path) -> None:
        start_time = time.time()
        ready_file = status_dir / "ready"
        failed_file = status_dir / "failed"
        error_file = status_dir / "error.txt"

        if self._prepare_timer is not None:
            self._prepare_timer.stop()
            self._prepare_timer.deleteLater()

        self._prepare_timer = QTimer(self)
        self._prepare_timer.setInterval(300)

        def poll() -> None:
            if ready_file.exists():
                self._prepare_timer.stop()
                self._set_status("Update validado. Fechando ACCELA para aplicar a troca.")
                QTimer.singleShot(200, lambda: self.main_window.request_quit("self_update"))
                return

            if failed_file.exists():
                self._prepare_timer.stop()
                self._install_in_progress = False
                reason = "O pacote remoto falhou na validação."
                if error_file.exists():
                    try:
                        reason = error_file.read_text(encoding="utf-8").strip() or reason
                    except OSError:
                        pass
                self._set_status(f"Update bloqueado: {reason}")
                QMessageBox.warning(
                    self.main_window,
                    "Atualizações",
                    f"Update bloqueado antes da troca:\n\n{reason}",
                )
                return

            if (time.time() - start_time) > 120:
                self._prepare_timer.stop()
                self._install_in_progress = False
                self._set_status("Tempo esgotado ao preparar o update.")
                QMessageBox.warning(
                    self.main_window,
                    "Atualizações",
                    "O preparo do update demorou demais e foi cancelado.",
                )

        self._prepare_timer.timeout.connect(poll)
        self._prepare_timer.start()

    def _check_worker(self, interactive: bool) -> None:
        try:
            repo = self.get_repo_slug()
            release = self._fetch_latest_release()
            self.latest_release = release
            self.security_message = self._build_security_summary(release)
            installed_revision = self.get_installed_revision()
            latest_revision = str(release.get("commit_sha", "")).strip()
            update_state = self._determine_update_state(
                repo=repo,
                installed_revision=installed_revision,
                latest_revision=latest_revision,
            )
            update_available = bool(update_state.get("available", False))
            self._set_update_available(update_available)

            if update_available:
                self._set_status(
                    f"Atualização disponível: {release.get('display_name', 'novo update')}."
                )
                payload = dict(release)
                payload["interactive"] = interactive
                self.release_detected.emit(payload)
            else:
                current_label = update_state.get(
                    "label", release.get("display_name", self.current_version)
                )
                message = str(
                    update_state.get(
                        "message",
                        f"Você já está na versão mais recente ({current_label}).",
                    )
                )
                self._set_status(message)
                if interactive:
                    QTimer.singleShot(
                        0,
                        lambda: QMessageBox.information(
                            self.main_window,
                            "Atualizações",
                            message,
                        ),
                    )
            self._last_check_at = time.time()
            self._last_check_payload = {
                "release": dict(release),
                "security_message": self.security_message,
                "status_message": self.status_message,
                "update_available": update_available,
            }
        except Exception as exc:
            logger.error("Update check failed: %s", exc, exc_info=True)
            self.security_message = "Assinatura/SHA256 indisponíveis nesta verificação."
            self._set_update_available(False)
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
        revision = str(release.get("commit_sha", "")).strip()
        latest = release.get("display_name", "novo update")
        first_announcement = bool(revision) and revision != self._announced_revision

        if first_announcement:
            self._announced_revision = revision
            self.notification_requested.emit(
                "Atualização disponível",
                f"{latest} pronto para baixar.",
            )

        if auto_update and not interactive:
            if self._is_busy_for_update():
                self._pending_auto_update_release = dict(release)
                if self._pending_auto_update_timer is not None:
                    self._pending_auto_update_timer.start()
                self._set_status(
                    f"Update {latest} detectado. O download será preparado quando a fila ficar ociosa."
                )
                return
            self.install_update(release)
            return

        if not self.main_window.isVisible():
            return

        if not interactive and not first_announcement:
            return

        message = QMessageBox(self.main_window)
        message.setWindowTitle("Atualização disponível")
        message.setText(f"O update {latest} está disponível no GitHub.")
        message.setInformativeText(
            f"{self._build_security_summary(release)}\nDeseja baixar e instalar agora?"
        )
        message.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        message.setDefaultButton(QMessageBox.StandardButton.Yes)
        if message.exec() == QMessageBox.StandardButton.Yes:
            self.install_update(release)

    def _retry_pending_auto_update(self) -> None:
        if not self._pending_auto_update_release:
            if self._pending_auto_update_timer is not None:
                self._pending_auto_update_timer.stop()
            return

        if self._is_busy_for_update() or self._install_in_progress:
            return

        release = dict(self._pending_auto_update_release)
        self._pending_auto_update_release = None
        if self._pending_auto_update_timer is not None:
            self._pending_auto_update_timer.stop()
        self.install_update(release)

    def _is_busy_for_update(self) -> bool:
        task_manager = getattr(self.main_window, "task_manager", None)
        if task_manager is not None and getattr(task_manager, "is_processing", False):
            return True
        queue = getattr(getattr(self.main_window, "job_queue", None), "job_queue", None)
        return bool(queue)

    def _github_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ACCELA",
        }

    def _remote_commit_exists(self, repo: str, commit_sha: str) -> bool:
        if not commit_sha:
            return False
        response = requests.get(
            f"https://api.github.com/repos/{repo}/commits/{commit_sha}",
            headers=self._github_headers(),
            timeout=20,
        )
        if response.status_code == 404:
            return False
        response.raise_for_status()
        return True

    def _determine_update_state(
        self,
        repo: str,
        installed_revision: str,
        latest_revision: str,
    ) -> Dict[str, str | bool]:
        if installed_revision.startswith("local-"):
            label = installed_revision.split("-")[1][:8] if "-" in installed_revision else "local"
            return {
                "available": False,
                "label": label,
                "message": f"Build local em desenvolvimento detectada ({label}). Update automático desativado para evitar sobrescrever testes locais.",
            }

        if len(installed_revision) != 40 or any(ch not in "0123456789abcdef" for ch in installed_revision.lower()):
            return {
                "available": False,
                "label": installed_revision[:8] or "local",
                "message": "Revisão instalada fora do padrão GitHub. Update automático preservado para evitar sobrescrever uma build não padronizada.",
            }

        if not latest_revision:
            return {"available": False, "label": self.current_version, "message": "Manifesto sem revisão remota."}

        if not installed_revision:
            return {
                "available": True,
                "label": latest_revision[:8],
                "message": "Instalação sem revisão registrada. Update disponível.",
            }

        if installed_revision == latest_revision:
            label = installed_revision[:8]
            return {
                "available": False,
                "label": label,
                "message": f"Você já está na versão mais recente ({label}).",
            }

        compare_url = (
            f"https://api.github.com/repos/{repo}/compare/"
            f"{installed_revision}...{latest_revision}"
        )
        response = requests.get(compare_url, headers=self._github_headers(), timeout=30)
        if response.status_code == 200:
            payload = response.json()
            status = str(payload.get("status", "")).strip()
            ahead_by = int(payload.get("ahead_by", 0) or 0)
            behind_by = int(payload.get("behind_by", 0) or 0)
            label = latest_revision[:8]

            if status == "behind" or (behind_by > 0 and ahead_by == 0):
                return {
                    "available": True,
                    "label": label,
                    "message": f"Atualização disponível: {label}.",
                }

            if status in {"identical", "ahead"} or ahead_by > 0:
                return {
                    "available": False,
                    "label": installed_revision[:8],
                    "message": f"Seu ACCELA local já está adiantado em relação ao GitHub ({installed_revision[:8]}).",
                }

            return {
                "available": False,
                "label": installed_revision[:8],
                "message": "Seu ACCELA local divergiu do GitHub. Update automático foi preservado para evitar downgrade.",
            }

        if response.status_code == 404:
            if not self._remote_commit_exists(repo, installed_revision):
                return {
                    "available": False,
                    "label": installed_revision[:8],
                    "message": f"Build local não publicada no GitHub ({installed_revision[:8]}). Update automático desativado para evitar downgrade.",
                }

            return {
                "available": True,
                "label": latest_revision[:8],
                "message": f"Atualização disponível: {latest_revision[:8]}.",
            }

        response.raise_for_status()
        return {
            "available": False,
            "label": installed_revision[:8],
            "message": f"Não foi possível comparar {installed_revision[:8]} com {latest_revision[:8]}.",
        }

    def _fetch_latest_release(self) -> Dict[str, str]:
        repo = self.get_repo_slug()
        branch_name = self.get_branch_name()

        try:
            return self._fetch_manifest_release(repo, branch_name)
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                logger.info("No release/latest.json found; falling back to commit zip.")
            else:
                raise
        except RuntimeError:
            raise
        except Exception:
            logger.warning("Manifest fetch failed, falling back to commit zip.", exc_info=True)

        return self._fetch_commit_release(repo, branch_name)

    def _fetch_manifest_release(self, repo: str, branch_name: str) -> Dict[str, str]:
        manifest_url = (
            f"https://raw.githubusercontent.com/{repo}/{branch_name}/{self.MANIFEST_PATH}"
        )
        response = requests.get(manifest_url, headers=self._github_headers(), timeout=30)
        response.raise_for_status()
        manifest = response.json()

        package_url = str(manifest.get("package_url", "")).strip()
        if not package_url:
            raise RuntimeError("Manifesto latest.json sem package_url.")

        commit_sha = str(manifest.get("commit_sha", "")).strip()
        if not commit_sha:
            raise RuntimeError("Manifesto latest.json sem commit_sha.")

        version_label = str(manifest.get("version", "")).strip() or commit_sha[:8]
        display_name = (
            str(manifest.get("display_name", "")).strip()
            or f"{branch_name}-{version_label}"
        )

        return {
            "tag_name": version_label,
            "display_name": display_name,
            "branch_name": branch_name,
            "commit_sha": commit_sha,
            "commit_message": str(manifest.get("notes", "")).strip(),
            "package_url": package_url,
            "sha256_url": str(manifest.get("sha256_url", "")).strip(),
            "signature_url": str(manifest.get("signature_url", "")).strip(),
            "html_url": str(manifest.get("html_url", "")).strip(),
            "source": "manifest",
        }

    def _fetch_commit_release(self, repo: str, branch_name: str) -> Dict[str, str]:
        commit_url = f"https://api.github.com/repos/{repo}/commits/{branch_name}"
        response = requests.get(commit_url, headers=self._github_headers(), timeout=30)
        response.raise_for_status()
        commit = response.json()

        full_sha = str(commit.get("sha", "")).strip()
        if not full_sha:
            raise RuntimeError("Commit do GitHub sem sha.")

        short_sha = full_sha[:8]
        commit_message = (
            ((commit.get("commit") or {}).get("message") or "").splitlines()[0].strip()
        )

        return {
            "tag_name": short_sha,
            "display_name": f"{branch_name}-{short_sha}",
            "branch_name": branch_name,
            "commit_sha": full_sha,
            "commit_message": commit_message,
            "package_url": f"https://github.com/{repo}/archive/{full_sha}.zip",
            "sha256_url": "",
            "signature_url": "",
            "html_url": commit.get("html_url", ""),
            "source": "commit_zip",
        }

    def _build_security_summary(self, release: Dict[str, str]) -> str:
        hash_status = "válido" if release.get("sha256_url") else "indisponível"
        signature_status = (
            "válida ao instalar" if release.get("signature_url") else "indisponível"
        )
        source = (
            "GitHub Releases"
            if release.get("source") == "manifest"
            else "GitHub source archive"
        )
        return (
            f"Assinatura: {signature_status} | "
            f"SHA256: {hash_status} | "
            f"Fonte: {source}"
        )

    def _set_status(self, message: str) -> None:
        self.status_message = message
        self.status_changed.emit(message)

    def _load_public_key_text(self) -> str:
        public_key_path = self._public_key_path()
        if not public_key_path.exists():
            return ""

        try:
            return public_key_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Failed to read public signing key", exc_info=True)
            return ""

    def _write_update_script(self, release: Dict[str, str]) -> tuple[Path, Path]:
        temp_dir = Path(tempfile.mkdtemp(prefix="accela-update-"))
        script_path = temp_dir / "apply-update.sh"
        status_dir = temp_dir / "status"
        status_dir.mkdir(parents=True, exist_ok=True)
        package_url = shlex.quote(
            str(release.get("package_url") or release.get("zip_url") or "")
        )
        sha256_url = shlex.quote(str(release.get("sha256_url", "")).strip())
        signature_url = shlex.quote(str(release.get("signature_url", "")).strip())
        current_pid = os.getpid()
        source_revision = shlex.quote(str(release.get("commit_sha", "")).strip())
        source_version = shlex.quote(
            str(release.get("display_name", release.get("tag_name", ""))).strip()
        )
        require_signature = "true" if self.require_signed_updates() else "false"
        public_key_text = self._load_public_key_text()
        base_dir = shlex.quote(str(self._base_path()))
        launcher_path = shlex.quote(str(Path.home() / ".local" / "bin" / "accela"))
        status_dir_quoted = shlex.quote(str(status_dir))

        script = f"""#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(mktemp -d)"
ARCHIVE="$WORKDIR/update.zip"
HASH_FILE="$WORKDIR/update.sha256"
SIG_FILE="$WORKDIR/update.sig"
PUBKEY_FILE="$WORKDIR/public.pem"
EXTRACT_DIR="$WORKDIR/extracted"
STATUS_DIR={status_dir_quoted}
READY_FILE="$STATUS_DIR/ready"
FAILED_FILE="$STATUS_DIR/failed"
ERROR_FILE="$STATUS_DIR/error.txt"
BASE_DIR={base_dir}
LAUNCHER={launcher_path}
mkdir -p "$EXTRACT_DIR"

fail_update() {{
    printf '%s\\n' "$1" > "$ERROR_FILE"
    : > "$FAILED_FILE"
    exit 1
}}

download() {{
    local url="$1"
    local target="$2"

    if [ -z "$url" ]; then
        return 1
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 -C - "$url" -o "$target"
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -c -O "$target" "$url"
        return 0
    fi
    fail_update "Nem curl nem wget estão disponíveis."
}}

healthcheck() {{
    local source_dir="$1"
    [ -f "$source_dir/install.sh" ] || fail_update "Pacote do GitHub sem install.sh."
    [ -f "$source_dir/app/ACCELA/squashfs-root/AppRun" ] || fail_update "Pacote sem AppRun."
    [ -f "$source_dir/app/ACCELA/squashfs-root/bin/run.sh" ] || fail_update "Pacote sem run.sh."
    bash -n "$source_dir/install.sh" || fail_update "install.sh inválido."
    bash -n "$source_dir/app/ACCELA/squashfs-root/AppRun" || fail_update "AppRun inválido."
    bash -n "$source_dir/app/ACCELA/squashfs-root/bin/run.sh" || fail_update "run.sh inválido."
    python3 -m compileall "$source_dir/app/ACCELA/squashfs-root/bin/src" >/dev/null || fail_update "Código Python do update não compila."
    if command -v desktop-file-validate >/dev/null 2>&1; then
        desktop-file-validate "$source_dir/app/ACCELA/squashfs-root/ACCELA.desktop" >/dev/null 2>&1 || fail_update ".desktop do update é inválido."
    fi
}}

restore_backup() {{
    local backup_dir="$1"
    [ -d "$backup_dir" ] || return 0
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude 'backups' "$backup_dir/" "$BASE_DIR/"
        return 0
    fi
    python3 - "$backup_dir" "$BASE_DIR" <<'PY'
import shutil
import sys
from pathlib import Path

backup = Path(sys.argv[1])
base = Path(sys.argv[2])
for child in base.iterdir():
    if child.name == "backups":
        continue
    if child.is_dir():
        shutil.rmtree(child, ignore_errors=True)
    else:
        child.unlink(missing_ok=True)
for child in backup.iterdir():
    target = base / child.name
    if child.is_dir():
        shutil.copytree(child, target, dirs_exist_ok=True)
    else:
        shutil.copy2(child, target)
PY
}}

download {package_url} "$ARCHIVE" || fail_update "Falha ao baixar o pacote do update."

if [ -n {sha256_url} ]; then
    download {sha256_url} "$HASH_FILE" || fail_update "Falha ao baixar o SHA256."
    if ! python3 - "$ARCHIVE" "$HASH_FILE" <<'PY'
import hashlib
import pathlib
import sys

archive = pathlib.Path(sys.argv[1])
hash_file = pathlib.Path(sys.argv[2])
expected = hash_file.read_text(encoding="utf-8").strip().split()[0]
actual = hashlib.sha256(archive.read_bytes()).hexdigest()
if expected != actual:
    raise SystemExit(f"SHA256 inválido: esperado {{expected}}, obtido {{actual}}")
PY
    then
        fail_update "SHA256 inválido."
    fi
fi

if [ -n {signature_url} ]; then
    download {signature_url} "$SIG_FILE" || fail_update "Falha ao baixar a assinatura."
    cat > "$PUBKEY_FILE" <<'PEM'
{public_key_text}
PEM
    if ! command -v openssl >/dev/null 2>&1; then
        fail_update "openssl não está disponível para validar a assinatura."
    fi
    openssl dgst -sha256 -verify "$PUBKEY_FILE" -signature "$SIG_FILE" "$ARCHIVE" >/dev/null || fail_update "Assinatura inválida."
elif [ {require_signature} = "true" ]; then
    fail_update "Update bloqueado: assinatura ausente e política local exige assinatura válida."
fi

if ! python3 - "$ARCHIVE" "$EXTRACT_DIR" <<'PY'
import sys
import zipfile

archive, target = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(archive) as zf:
    zf.extractall(target)
PY
then
    fail_update "Falha ao extrair o pacote do update."
fi

SRC_DIR="$EXTRACT_DIR"
if [ ! -f "$SRC_DIR/install.sh" ]; then
    SRC_DIR="$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi
if [ -z "$SRC_DIR" ] || [ ! -f "$SRC_DIR/install.sh" ]; then
    fail_update "Pacote do GitHub sem install.sh."
fi

healthcheck "$SRC_DIR"
: > "$READY_FILE"

while kill -0 {current_pid} >/dev/null 2>&1; do
    sleep 1
done

chmod +x "$SRC_DIR/install.sh"
BACKUP_DIR=""
if [ -d "$BASE_DIR/squashfs-root" ]; then
    BACKUP_DIR="$(mktemp -d)"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude 'backups' "$BASE_DIR/" "$BACKUP_DIR/"
    else
        python3 - "$BASE_DIR" "$BACKUP_DIR" <<'PY'
import shutil
import sys
from pathlib import Path

base = Path(sys.argv[1])
backup = Path(sys.argv[2])
for child in base.iterdir():
    if child.name == "backups":
        continue
    target = backup / child.name
    if child.is_dir():
        shutil.copytree(child, target, dirs_exist_ok=True)
    else:
        shutil.copy2(child, target)
PY
    fi
fi

if ! bash "$SRC_DIR/install.sh" --no-prompt --source-revision {source_revision} --source-version {source_version}; then
    if [ -n "$BACKUP_DIR" ]; then
        restore_backup "$BACKUP_DIR"
    fi
    fail_update "A instalação do update falhou. Backup restaurado automaticamente."
fi

"$LAUNCHER" >/dev/null 2>&1 &
"""
        script_path.write_text(script, encoding="utf-8")
        os.chmod(script_path, 0o755)
        return script_path, status_dir

    def _write_rollback_script(self, backup_dir: Path) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="accela-rollback-"))
        script_path = temp_dir / "apply-rollback.sh"
        current_pid = os.getpid()
        base_dir = self._base_path()

        script = f"""#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR={shlex.quote(str(backup_dir))}
BASE_DIR={shlex.quote(str(base_dir))}

while kill -0 {current_pid} >/dev/null 2>&1; do
    sleep 1
done

if command -v rsync >/dev/null 2>&1; then
    rsync -a --delete --exclude 'backups' "$BACKUP_DIR/" "$BASE_DIR/"
else
    python3 - "$BACKUP_DIR" "$BASE_DIR" <<'PY'
import shutil
import sys
from pathlib import Path

backup = Path(sys.argv[1])
base = Path(sys.argv[2])

for child in base.iterdir():
    if child.name == "backups":
        continue
    if child.is_dir():
        shutil.rmtree(child, ignore_errors=True)
    else:
        child.unlink(missing_ok=True)

for child in backup.iterdir():
    target = base / child.name
    if child.is_dir():
        shutil.copytree(child, target, dirs_exist_ok=True)
    else:
        shutil.copy2(child, target)
PY
fi

"$HOME/.local/bin/accela" >/dev/null 2>&1 &
"""
        script_path.write_text(script, encoding="utf-8")
        os.chmod(script_path, 0o755)
        return script_path
