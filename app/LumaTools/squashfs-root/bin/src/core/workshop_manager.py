from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

from core.workshop.workshop_installer import WorkshopInstaller
from core.workshop.workshop_errors import WorkshopError
from core.workshop.workshop_profiles import resolve_workshop_profile
from core.workshop.workshop_resolver import WorkshopResolver
from utils.helpers import get_base_path

logger = logging.getLogger(__name__)


class WorkshopManager:
    """SteamCMD-backed Workshop downloader and local mod registry."""

    STEAMCMD_URL = "https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz"

    def __init__(self, base_path: Path | None = None):
        self.base_path = Path(base_path or get_base_path())
        self.download_root = self.base_path / "workshop"
        self.registry_path = self.base_path / "workshop_mods.json"
        self.state = {
            "status": "idle",
            "progress": 0.0,
            "message": "",
            "last_error": "",
        }
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.installer = WorkshopInstaller()

    @staticmethod
    def parse_workshop_id(value: str) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        patterns = [
            r"[?&]id=(\d+)",
            r"/filedetails/\?id=(\d+)",
            r"/sharedfiles/filedetails/\?id=(\d+)",
            r"\b(\d{6,})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        return None

    def find_steamcmd(self) -> str | None:
        candidates = [
            shutil.which("steamcmd"),
            shutil.which("steamcmd.sh"),
            str(self.base_path / "steamcmd" / "steamcmd.sh"),
            str(Path.home() / ".steam" / "steamcmd" / "steamcmd.sh"),
            str(Path.home() / ".local" / "share" / "Steam" / "steamcmd" / "steamcmd.sh"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return None

    def ensure_steamcmd(self) -> str:
        existing = self.find_steamcmd()
        if existing:
            return existing

        target_dir = self.base_path / "steamcmd"
        target_dir.mkdir(parents=True, exist_ok=True)
        archive_path = Path(tempfile.gettempdir()) / "lumatools_steamcmd_linux.tar.gz"
        logger.info("Downloading SteamCMD to %s", archive_path)
        with requests.get(self.STEAMCMD_URL, stream=True, timeout=120) as response:
            response.raise_for_status()
            with archive_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)

        with tarfile.open(archive_path, "r:gz") as tar:
            safe_target = target_dir.resolve()
            for member in tar.getmembers():
                member_path = (safe_target / member.name).resolve()
                if not str(member_path).startswith(str(safe_target)):
                    raise RuntimeError("SteamCMD archive contem caminho inseguro.")
            tar.extractall(target_dir)

        steamcmd = target_dir / "steamcmd.sh"
        if not steamcmd.exists():
            raise FileNotFoundError("SteamCMD baixado, mas steamcmd.sh nao foi encontrado.")
        steamcmd.chmod(0o755)
        return str(steamcmd)

    def search_items(
        self,
        appid: int | str,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search public Steam Workshop results for an app.

        Steam does not expose a stable anonymous JSON search endpoint for all
        workshop apps, so this intentionally parses the public browse page and
        keeps only the small fields the UI needs.
        """
        appid_text = str(appid).strip()
        query_text = (query or "").strip()
        if not appid_text:
            raise ValueError("AppID do jogo nao encontrado.")
        if not query_text:
            raise ValueError("Digite o nome do mod para pesquisar.")

        url = (
            "https://steamcommunity.com/workshop/browse/"
            f"?appid={appid_text}"
            f"&searchtext={quote_plus(query_text)}"
            "&browsesort=trend"
            "&section=readytouseitems"
            "&actualsort=trend"
            "&p=1"
        )
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 LumaTools"},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict[str, Any]] = []
        seen: set[str] = set()

        detail_links = list(
            soup.select(
                'a[href*="/sharedfiles/filedetails/"], '
                'a[href*="/workshop/filedetails/"]'
            )
        )
        for link in detail_links:
            href = link.get("href", "")
            item_id = self.parse_workshop_id(href)
            if not item_id or item_id in seen or item_id == appid_text:
                continue
            seen.add(item_id)

            image_node = link.find("img")
            if image_node is None:
                parent = link.parent
                hops = 0
                while parent is not None and hops < 5 and image_node is None:
                    image_node = parent.find("img")
                    parent = parent.parent
                    hops += 1
            title = image_node.get("alt", "") if image_node else ""
            if not title:
                title = link.get_text(" ", strip=True)
            image = image_node.get("src", "") if image_node else ""
            results.append(
                {
                    "appid": appid_text,
                    "workshop_id": item_id,
                    "title": title or f"Workshop {item_id}",
                    "image": image,
                    "url": href,
                }
            )
            if len(results) >= limit:
                return results

        for node in soup.select(".workshopItem"):
            link = node.find("a", href=True)
            if not link:
                continue
            href = link.get("href", "")
            if "filedetails" not in href:
                continue
            item_id = self.parse_workshop_id(href)
            if not item_id or item_id in seen or item_id == appid_text:
                continue
            seen.add(item_id)

            title_node = node.select_one(".workshopItemTitle")
            image_node = node.find("img")
            title = (
                title_node.get_text(" ", strip=True)
                if title_node
                else (image_node.get("alt", "") if image_node else "")
            )
            image = image_node.get("src", "") if image_node else ""
            results.append(
                {
                    "appid": appid_text,
                    "workshop_id": item_id,
                    "title": title or f"Workshop {item_id}",
                    "image": image,
                    "url": href,
                }
            )
            if len(results) >= limit:
                return results

        if results:
            return results

        # Fallback for layout changes: scan every filedetails link.
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            if "filedetails" not in href:
                continue
            item_id = self.parse_workshop_id(href)
            if not item_id or item_id in seen or item_id == appid_text:
                continue
            seen.add(item_id)
            title = link.get_text(" ", strip=True) or f"Workshop {item_id}"
            image_node = link.find("img")
            results.append(
                {
                    "appid": appid_text,
                    "workshop_id": item_id,
                    "title": title,
                    "image": image_node.get("src", "") if image_node else "",
                    "url": link.get("href", ""),
                }
            )
            if len(results) >= limit:
                break

        if not results and not self.supports_workshop(appid_text):
            raise ValueError("Este jogo nao parece ter Workshop publico na Steam.")

        return results

    def supports_workshop(self, appid: int | str) -> bool:
        try:
            response = requests.get(
                "https://store.steampowered.com/api/appdetails",
                params={"appids": str(appid), "filters": "categories"},
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0 LumaTools"},
            )
            response.raise_for_status()
            data = response.json().get(str(appid), {})
            categories = data.get("data", {}).get("categories", [])
            for category in categories:
                description = str(category.get("description", "")).lower()
                if "workshop" in description:
                    return True
        except Exception:
            logger.debug("Workshop support lookup failed for %s", appid, exc_info=True)
        return False

    def load_registry(self) -> list[dict[str, Any]]:
        if not self.registry_path.exists():
            return []
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            logger.warning("Failed to load Workshop registry", exc_info=True)
            return []

    def save_registry(self, items: list[dict[str, Any]]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps(items, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def detect_mod_target(game_dir: str | os.PathLike[str]) -> Path:
        return Path(resolve_workshop_profile(game_dir).target_root)

    def download_item(self, appid: int | str, pubfile_id: int | str, download_dir: str | None = None):
        thread = threading.Thread(
            target=self._run_download,
            args=(str(appid), str(pubfile_id), download_dir),
            daemon=True,
        )
        thread.start()

    def download_item_sync(
        self,
        appid: int | str,
        pubfile_id: int | str,
        game_dir: str | os.PathLike[str] | None = None,
        username: str = "",
        password: str = "",
    ) -> dict[str, Any]:
        return self._run_download(
            str(appid),
            str(pubfile_id),
            None,
            game_dir=game_dir,
            username=username,
            password=password,
        )

    def _run_download(
        self,
        appid: str,
        pubfile_id: str,
        download_dir: str | None,
        game_dir: str | os.PathLike[str] | None = None,
        username: str = "",
        password: str = "",
    ) -> dict[str, Any]:
        with self.lock:
            if self.state["status"] == "downloading":
                raise RuntimeError("Download do Workshop ja esta em progresso.")
            self.state.update(
                {
                    "status": "downloading",
                    "progress": 0.0,
                    "message": "Iniciando SteamCMD...",
                    "last_error": "",
                }
            )

        try:
            steamcmd = self.ensure_steamcmd()
        except Exception:
            with self.lock:
                self.state.update(
                    {
                        "status": "failed",
                        "message": "SteamCMD nao encontrado.",
                        "last_error": "steamcmd_missing",
                    }
                )
            raise FileNotFoundError("SteamCMD nao encontrado e nao foi possivel baixar automaticamente.")

        target_root = Path(download_dir or self.download_root).expanduser().resolve()
        target_root.mkdir(parents=True, exist_ok=True)

        try:
            resolver = WorkshopResolver(steamcmd)

            def on_line(text: str) -> None:
                with self.lock:
                    self.state["message"] = text
                    if "Success. Downloaded item" in text:
                        self.state["progress"] = 100.0

            download_path = resolver.download(
                appid=appid,
                workshop_id=pubfile_id,
                target_root=target_root,
                username=username,
                password=password,
                on_line=on_line,
                on_process=lambda process: setattr(self, "process", process),
            )
            if game_dir:
                record = self.installer.install(
                    appid=appid,
                    workshop_id=pubfile_id,
                    source=download_path,
                    game_dir=game_dir,
                )
            else:
                record = {
                    "appid": appid,
                    "workshop_id": pubfile_id,
                    "title": f"Workshop {pubfile_id}",
                    "source": "steamcmd",
                    "download_path": str(download_path),
                    "installed_path": "",
                    "enabled": False,
                    "status": "public_downloaded" if not username else "downloaded",
                    "last_checked": datetime.now(timezone.utc).isoformat(),
                }
            self._upsert_record(record)
            with self.lock:
                self.state.update(
                    {
                        "status": "done",
                        "progress": 100.0,
                        "message": "Workshop concluido.",
                    }
                )
            return record
        except WorkshopError as exc:
            with self.lock:
                self.state.update(
                    {
                        "status": "failed",
                        "message": str(exc),
                        "last_error": exc.code.value,
                    }
                )
            logger.error(
                "Workshop download failed: %s (%s)",
                exc.code.value,
                exc.details,
            )
            raise
        except Exception as exc:
            with self.lock:
                self.state.update(
                    {"status": "failed", "message": str(exc), "last_error": str(exc)}
                )
            logger.error("Workshop download failed", exc_info=True)
            raise

    @staticmethod
    def _find_download_path(root: Path, appid: str, itemid: str) -> Path | None:
        return WorkshopResolver.find_download_path(root, str(appid), str(itemid))

    def install_item_to_game(
        self,
        download_path: str | os.PathLike[str],
        itemid: str,
        game_dir: str | os.PathLike[str],
    ) -> Path:
        record = self.installer.install(
            appid="",
            workshop_id=str(itemid),
            source=download_path,
            game_dir=game_dir,
        )
        return Path(record["installed_path"])

    def _upsert_record(self, record: dict[str, Any]) -> dict[str, Any]:
        items = [
            item
            for item in self.load_registry()
            if not (
                str(item.get("appid")) == str(record.get("appid"))
                and str(item.get("workshop_id")) == str(record.get("workshop_id"))
            )
        ]
        items.append(record)
        self.save_registry(items)
        return record

    def register_item(
        self,
        appid: str,
        workshop_id: str,
        download_path: str,
        installed_path: str = "",
        title: str = "",
    ) -> dict[str, Any]:
        record = {
            "appid": str(appid),
            "workshop_id": str(workshop_id),
            "title": title or f"Workshop {workshop_id}",
            "source": "steamcmd",
            "download_path": download_path,
            "installed_path": installed_path,
            "enabled": True,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }
        return self._upsert_record(record)

    def set_enabled(self, appid: str, workshop_id: str, enabled: bool) -> bool:
        changed = False
        items = self.load_registry()
        for item in items:
            if str(item.get("appid")) == str(appid) and str(item.get("workshop_id")) == str(workshop_id):
                self.installer.set_enabled(item, bool(enabled))
                changed = True
        if changed:
            self.save_registry(items)
        return changed

    def uninstall_item(self, appid: str, workshop_id: str) -> bool:
        changed = False
        items = self.load_registry()
        for item in items:
            if (
                str(item.get("appid")) == str(appid)
                and str(item.get("workshop_id")) == str(workshop_id)
            ):
                self.installer.uninstall(item)
                changed = True
        if changed:
            self.save_registry(items)
        return changed

    def repair_item(self, appid: str, workshop_id: str) -> dict[str, Any]:
        for item in self.load_registry():
            if (
                str(item.get("appid")) == str(appid)
                and str(item.get("workshop_id")) == str(workshop_id)
            ):
                return self.installer.repair(item)
        return {"ok": False, "issues": ["registry_entry_missing"]}

    def get_status(self) -> dict[str, Any]:
        with self.lock:
            return self.state.copy()

    def cancel(self):
        with self.lock:
            if self.process:
                self.process.kill()
                self.state["status"] = "cancelled"
                self.state["message"] = "Download cancelado pelo usuario."
