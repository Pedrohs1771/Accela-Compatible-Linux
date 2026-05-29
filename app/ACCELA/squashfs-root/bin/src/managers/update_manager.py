import json
import logging
import os
import shlex
import subprocess
import tempfile
import threading
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

    DEFAULT_REPO = "Pedrohs1771/Accela-Compatible-Linux"
    DEFAULT_BRANCH = "main"
    MANIFEST_PATH = "release/latest.json"

    def __init__(self, main_window):
        super().__init__(parent=main_window)
        self.main_window = main_window
        self.settings = main_window.settings
        self.latest_release: Optional[Dict[str, str]] = None
        self.status_message = "Aguardando verificação."
        self.security_message = "Assinatura e SHA256 ainda não verificados."
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
            return ""

        try:
            return revision_file.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Failed to read installed repo revision", exc_info=True)
            return ""

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

    def schedule_startup_check(self) -> None:
        enabled = self.settings.value("github_updates_enabled", True, type=bool)
        if not enabled:
            return
        QTimer.singleShot(2500, lambda: self.check_for_updates_async(interactive=False))

    def check_for_updates_async(self, interactive: bool = False) -> None:
        if self._check_in_progress:
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
        self._set_status(
            f"Instalando {release.get('display_name', release.get('tag_name', 'novo update'))}..."
        )

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

    def _check_worker(self, interactive: bool) -> None:
        try:
            release = self._fetch_latest_release()
            self.latest_release = release
            self.security_message = self._build_security_summary(release)
            installed_revision = self.get_installed_revision()
            latest_revision = str(release.get("commit_sha", "")).strip()
            update_available = bool(latest_revision) and installed_revision != latest_revision

            if update_available:
                self._set_status(
                    f"Atualização disponível: {release.get('display_name', 'novo update')}."
                )
                payload = dict(release)
                payload["interactive"] = interactive
                self.release_detected.emit(payload)
            else:
                current_label = release.get("display_name", self.current_version)
                if installed_revision:
                    current_label = installed_revision[:8]
                self._set_status(
                    f"Você já está na versão mais recente ({current_label})."
                )
                if interactive:
                    QTimer.singleShot(
                        0,
                        lambda: QMessageBox.information(
                            self.main_window,
                            "Atualizações",
                            f"Você já está na versão mais recente ({current_label}).",
                        ),
                    )
        except Exception as exc:
            logger.error("Update check failed: %s", exc, exc_info=True)
            self.security_message = "Assinatura/SHA256 indisponíveis nesta verificação."
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

        latest = release.get("display_name", "novo update")
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
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ACCELA",
        }
        manifest_url = (
            f"https://raw.githubusercontent.com/{repo}/{branch_name}/{self.MANIFEST_PATH}"
        )
        response = requests.get(manifest_url, headers=headers, timeout=30)
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
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ACCELA",
        }
        commit_url = f"https://api.github.com/repos/{repo}/commits/{branch_name}"
        response = requests.get(commit_url, headers=headers, timeout=30)
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

    def _write_update_script(self, release: Dict[str, str]) -> Path:
        temp_dir = Path(tempfile.mkdtemp(prefix="accela-update-"))
        script_path = temp_dir / "apply-update.sh"
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

        script = f"""#!/usr/bin/env bash
set -euo pipefail

WORKDIR="$(mktemp -d)"
ARCHIVE="$WORKDIR/update.zip"
HASH_FILE="$WORKDIR/update.sha256"
SIG_FILE="$WORKDIR/update.sig"
PUBKEY_FILE="$WORKDIR/public.pem"
EXTRACT_DIR="$WORKDIR/extracted"
mkdir -p "$EXTRACT_DIR"

download() {{
    local url="$1"
    local target="$2"

    if [ -z "$url" ]; then
        return 1
    fi
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$target"
        return 0
    fi
    if command -v wget >/dev/null 2>&1; then
        wget -qO "$target" "$url"
        return 0
    fi
    echo "Nem curl nem wget estão disponíveis." >&2
    exit 1
}}

download {package_url} "$ARCHIVE"

if [ -n {sha256_url} ]; then
    download {sha256_url} "$HASH_FILE"
    python3 - "$ARCHIVE" "$HASH_FILE" <<'PY'
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
fi

if [ -n {signature_url} ]; then
    download {signature_url} "$SIG_FILE"
    cat > "$PUBKEY_FILE" <<'PEM'
{public_key_text}
PEM
    if ! command -v openssl >/dev/null 2>&1; then
        echo "openssl não está disponível para validar a assinatura." >&2
        exit 1
    fi
    openssl dgst -sha256 -verify "$PUBKEY_FILE" -signature "$SIG_FILE" "$ARCHIVE" >/dev/null
elif [ {require_signature} = "true" ]; then
    echo "Update bloqueado: assinatura ausente e política local exige assinatura válida." >&2
    exit 1
fi

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
bash "$SRC_DIR/install.sh" --no-prompt --source-revision {source_revision} --source-version {source_version}
"$HOME/.local/bin/accela" >/dev/null 2>&1 &
"""
        script_path.write_text(script, encoding="utf-8")
        os.chmod(script_path, 0o755)
        return script_path

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
