import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, Optional

import requests
from PyQt6.QtCore import QObject, pyqtSignal

from core.linux_paths import (
    detect_linux_steam_mode,
    find_primary_steam_root,
    find_slssteam_paths,
    get_slssteam_install_dir,
    get_slssteam_setup_command,
    list_steam_roots,
)

logger = logging.getLogger(__name__)


class DownloadSLSsteamTask(QObject):
    """Download and install the latest official SLSsteam build."""

    progress = pyqtSignal(str)
    progress_percentage = pyqtSignal(int)
    completed = pyqtSignal(str)
    error = pyqtSignal()

    RELEASES_URL = "https://api.github.com/repos/AceSLS/SLSsteam/releases/latest"
    RAW_SETUP_URL = (
        "https://raw.githubusercontent.com/AceSLS/SLSsteam/main/setup.sh"
    )

    def __init__(self, steam_path: Optional[str] = None):
        super().__init__()
        self.steam_path = steam_path
        self._is_running = True

    def stop(self) -> None:
        self._is_running = False

    @classmethod
    def install_dir(cls) -> Path:
        return get_slssteam_install_dir()

    @classmethod
    def version_file(cls) -> Path:
        return cls.install_dir() / "VERSION"

    @staticmethod
    def _elf_class(path: str | None) -> int | None:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, "rb") as handle:
                header = handle.read(5)
        except OSError:
            return None
        if len(header) < 5 or header[:4] != b"\x7fELF":
            return None
        if header[4] == 1:
            return 32
        if header[4] == 2:
            return 64
        return None

    @classmethod
    def _target_elf_class(cls) -> int | None:
        if sys.platform != "linux":
            return None
        steam_mode = detect_linux_steam_mode()
        root = find_primary_steam_root(preferred_mode=steam_mode if steam_mode != "missing" else None)
        if root is not None:
            for candidate in (
                root / "ubuntu12_32" / "steam",
                root / "steam.sh",
            ):
                detected = cls._elf_class(str(candidate))
                if detected:
                    return detected
        return 32

    @classmethod
    def installed_library_status(cls) -> Dict[str, object]:
        target_class = cls._target_elf_class()
        status: Dict[str, object] = {
            "installed": cls.install_dir().exists(),
            "compatible": False,
            "slssteam_path": "",
            "library_inject_path": "",
            "slssteam_class": None,
            "library_inject_class": None,
            "target_class": target_class,
        }
        if sys.platform != "linux":
            return status

        steam_mode = detect_linux_steam_mode()
        slssteam_path, library_inject_path = find_slssteam_paths(
            steam_mode,
            expected_elf_class=target_class,
        )
        status["slssteam_path"] = slssteam_path or ""
        status["library_inject_path"] = library_inject_path or ""
        status["slssteam_class"] = cls._elf_class(slssteam_path)
        status["library_inject_class"] = cls._elf_class(library_inject_path)
        status["compatible"] = (
            target_class in (32, 64)
            and status["slssteam_class"] == target_class
            and status["library_inject_class"] == target_class
        )
        return status

    @classmethod
    def install_latest_blocking(cls) -> str:
        temp_root = Path(tempfile.mkdtemp(prefix="lumatools-slssteam-"))
        archive_path = temp_root / "SLSsteam-Any.7z"
        extract_dir = temp_root / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            release = cls._fetch_latest_release()
            asset = cls._pick_asset(release)
            latest_version = release.get("tag_name", "").strip() or "unknown"

            cls._download_asset_blocking(asset, archive_path)
            cls._extract_archive(archive_path, extract_dir)
            cls._run_setup(extract_dir)

            cls.install_dir().mkdir(parents=True, exist_ok=True)
            cls.version_file().write_text(f"{latest_version}\n", encoding="utf-8")

            library_status = cls.installed_library_status()
            if sys.platform == "linux" and not library_status.get("compatible"):
                raise RuntimeError(
                    "SLSsteam instalado, mas as bibliotecas não são compatíveis "
                    f"(esperado={library_status.get('target_class')}, "
                    f"SLSsteam.so={library_status.get('slssteam_class')}, "
                    f"library-inject.so={library_status.get('library_inject_class')})."
                )

            return f"SLSsteam {latest_version} instalado em {cls.install_dir()}."
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @classmethod
    def check_update_available(cls) -> Dict[str, object]:
        status: Dict[str, object] = {
            "installed": cls.install_dir().exists(),
            "installed_version": "",
            "latest_version": "Desconhecida",
            "update_available": False,
            "steamclient_found": False,
            "steamclient_mismatch": None,
            "steamclient_error": False,
            "libraries_compatible": cls.installed_library_status().get("compatible", False),
            "error": False,
        }

        if cls.version_file().exists():
            try:
                status["installed_version"] = cls.version_file().read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                logger.warning(
                    "Failed to read local SLSsteam version file",
                    exc_info=True,
                )

        steamclient_path = cls._find_steamclient()
        status["steamclient_found"] = steamclient_path is not None
        if steamclient_path is not None:
            status["steamclient_mismatch"] = False

        try:
            release = cls._fetch_latest_release()
            asset = cls._pick_asset(release)
            latest_version = release.get("tag_name", "").strip() or "Desconhecida"
            status["latest_version"] = latest_version
            status["asset_url"] = asset.get("browser_download_url", "")

            installed_version = str(status.get("installed_version", "")).strip()
            if not status["installed"]:
                status["update_available"] = True
            elif installed_version:
                status["update_available"] = installed_version != latest_version
        except Exception:
            logger.warning("Failed to check SLSsteam release status", exc_info=True)
            status["error"] = True

        return status

    def run(self) -> None:
        temp_root = Path(tempfile.mkdtemp(prefix="lumatools-slssteam-"))
        archive_path = temp_root / "SLSsteam-Any.7z"
        extract_dir = temp_root / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        try:
            self.progress.emit("Consultando a release oficial do SLSsteam...")
            self.progress_percentage.emit(5)
            release = self._fetch_latest_release()
            asset = self._pick_asset(release)
            latest_version = release.get("tag_name", "").strip() or "unknown"

            self.progress.emit("Baixando o pacote oficial do SLSsteam...")
            self._download_asset(asset, archive_path)
            if not self._is_running:
                return

            self.progress.emit("Extraindo arquivos do SLSsteam...")
            self.progress_percentage.emit(55)
            self._extract_archive(archive_path, extract_dir)
            if not self._is_running:
                return

            self.progress.emit("Executando o instalador do SLSsteam...")
            self.progress_percentage.emit(75)
            self._run_setup(extract_dir)
            if not self._is_running:
                return

            self.install_dir().mkdir(parents=True, exist_ok=True)
            self.version_file().write_text(f"{latest_version}\n", encoding="utf-8")
            self.progress_percentage.emit(100)
            self.completed.emit(
                f"SLSsteam {latest_version} instalado em {self.install_dir()}."
            )
        except Exception as exc:
            logger.error("SLSsteam installation failed: %s", exc, exc_info=True)
            self.progress.emit(f"Erro ao instalar SLSsteam: {exc}")
            self.error.emit()
        finally:
            shutil.rmtree(temp_root, ignore_errors=True)

    @classmethod
    def _fetch_latest_release(cls) -> dict:
        response = requests.get(
            cls.RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "LumaTools",
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _pick_asset(release: dict) -> dict:
        assets = release.get("assets") or []
        for asset in assets:
            name = str(asset.get("name", ""))
            if name.startswith("SLSsteam-Any") and name.endswith(".7z"):
                return asset
        raise RuntimeError("Asset SLSsteam-Any.7z não encontrado na release.")

    def _download_asset(self, asset: dict, archive_path: Path) -> None:
        url = asset.get("browser_download_url", "")
        if not url:
            raise RuntimeError("Release do SLSsteam sem URL de download.")

        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", "0") or "0")
            downloaded = 0
            with archive_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if not self._is_running:
                        return
                    if not chunk:
                        continue
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        percent = 5 + int((downloaded / total) * 40)
                        self.progress_percentage.emit(min(percent, 45))

    @staticmethod
    def _download_asset_blocking(asset: dict, archive_path: Path) -> None:
        url = asset.get("browser_download_url", "")
        if not url:
            raise RuntimeError("Release do SLSsteam sem URL de download.")

        with requests.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 512):
                    if chunk:
                        handle.write(chunk)

    @staticmethod
    def _extract_archive(archive_path: Path, extract_dir: Path) -> None:
        extractor = None
        for candidate in ("7z", "7zz", "7zr"):
            found = shutil.which(candidate)
            if found:
                extractor = found
                break

        if extractor is None:
            raise RuntimeError(
                "7z não encontrado. Instale p7zip ou use o instalador completo do LumaTools."
            )

        subprocess.run(
            [extractor, "x", str(archive_path), f"-o{extract_dir}", "-y"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @classmethod
    def _run_setup(cls, extract_dir: Path) -> None:
        setup_path = cls._locate_setup_script(extract_dir)
        if setup_path is None:
            setup_path = extract_dir / "setup.sh"
            response = requests.get(cls.RAW_SETUP_URL, timeout=30)
            response.raise_for_status()
            setup_path.write_text(response.text, encoding="utf-8")

        os.chmod(setup_path, 0o755)
        setup_command = get_slssteam_setup_command()
        logger.info("Running SLSsteam setup command: %s", setup_command)
        subprocess.run(
            ["bash", str(setup_path), setup_command],
            cwd=str(setup_path.parent),
            check=True,
            env=os.environ.copy(),
        )

    @staticmethod
    def _locate_setup_script(extract_dir: Path) -> Optional[Path]:
        for candidate in extract_dir.rglob("setup.sh"):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _find_steamclient() -> Optional[Path]:
        for root in list_steam_roots():
            candidate = root / "ubuntu12_32" / "steamclient.so"
            if candidate.exists():
                return candidate
        return None
