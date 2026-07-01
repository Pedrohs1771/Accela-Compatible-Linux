"""
LumaTools — Motor de Manifesto Multi-API com Fallback Inteligente.

Substitui o ManifestDownloader básico por um motor que:
- Carrega APIs de um registry JSON plugável
- Consulta APIs em paralelo com ThreadPoolExecutor
- Faz fallback automático entre APIs
- Valida ZIPs (deve conter .lua + .manifest)
- Extrai e instala manifestos no depotcache
- Gera scripts Lua compatíveis com OpenSteamTool/SLSsteam
- Cache local para reutilização de pacotes
- Progress callback para a UI
"""

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from utils.helpers import get_base_path

logger = logging.getLogger(__name__)

# Re-export for backward compat
__all__ = ["ManifestEngine", "ManifestDownloader"]

_REGISTRY_FILENAME = "api_registry.json"
_USER_AGENT = "Mozilla/5.0 LumaTools/2.0"
_DOWNLOAD_TIMEOUT = 30
_HEAD_TIMEOUT = 8
_CHUNK_SIZE = 32768


class APIEntry:
    """Represents a single manifest API endpoint."""

    __slots__ = (
        "name",
        "url",
        "status_url",
        "success_code",
        "requires_key",
        "key_param",
        "enabled",
        "priority",
    )

    def __init__(self, data: Dict[str, Any]):
        self.name: str = data.get("name", "Unknown")
        self.url: str = data.get("url", "")
        self.status_url: Optional[str] = data.get("status_url")
        self.success_code: int = int(data.get("success_code", 200))
        self.requires_key: bool = bool(data.get("requires_key", False))
        self.key_param: Optional[str] = data.get("key_param")
        self.enabled: bool = bool(data.get("enabled", True))
        self.priority: int = int(data.get("priority", 99))

    def build_url(self, appid: str, api_key: str = "") -> str:
        """Replace template placeholders in the URL."""
        url = self.url.replace("<appid>", str(appid))
        if self.key_param:
            url = url.replace(f"<{self.key_param}>", api_key)
        return url

    def build_status_url(self, appid: str, api_key: str = "") -> Optional[str]:
        """Build the status check URL if available."""
        if not self.status_url:
            return None
        url = self.status_url.replace("<appid>", str(appid))
        if self.key_param:
            url = url.replace(f"<{self.key_param}>", api_key)
        return url


class ManifestResult:
    """Result from a manifest fetch operation."""

    __slots__ = ("success", "zip_path", "api_name", "error", "lua_content", "manifest_files")

    def __init__(
        self,
        success: bool = False,
        zip_path: str = "",
        api_name: str = "",
        error: str = "",
        lua_content: str = "",
        manifest_files: Optional[List[str]] = None,
    ):
        self.success = success
        self.zip_path = zip_path
        self.api_name = api_name
        self.error = error
        self.lua_content = lua_content
        self.manifest_files = manifest_files or []


class APIAvailability:
    """Result of an availability check for a single API."""

    __slots__ = ("name", "available", "url", "response_time_ms")

    def __init__(
        self,
        name: str,
        available: bool,
        url: str = "",
        response_time_ms: float = 0,
    ):
        self.name = name
        self.available = available
        self.url = url
        self.response_time_ms = response_time_ms


class ManifestEngine:
    """Motor de manifesto multi-API com fallback inteligente.

    Substitui o antigo ManifestDownloader com:
    - Registry de APIs carregado de JSON
    - Download paralelo com ThreadPoolExecutor
    - Validação de ZIP (presença de .lua + .manifest)
    - Cache local de pacotes
    - Progress callback para UI
    """

    def __init__(self, api_registry_path: Optional[str] = None, api_key: str = ""):
        self.api_key = api_key
        self.download_dir = Path(get_base_path()) / "hubcap_manifests"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.download_dir / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_downloads: Dict[str, threading.Event] = {}

        # Load API registry
        self.apis = self._load_api_registry(api_registry_path)

    def _load_api_registry(self, path: Optional[str] = None) -> List[APIEntry]:
        """Load API definitions from the JSON registry file."""
        if path is None:
            # Look next to this module first, then in core/
            candidates = [
                Path(__file__).parent / _REGISTRY_FILENAME,
                Path(get_base_path()) / "core" / _REGISTRY_FILENAME,
            ]
        else:
            candidates = [Path(path)]

        for candidate in candidates:
            if candidate.exists():
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    apis = [APIEntry(entry) for entry in data if isinstance(entry, dict)]
                    apis.sort(key=lambda a: a.priority)
                    logger.info(
                        "Loaded %d APIs from registry: %s",
                        len(apis),
                        candidate,
                    )
                    return apis
                except (json.JSONDecodeError, OSError) as exc:
                    logger.error("Failed to load API registry from %s: %s", candidate, exc)

        # Fallback: hardcoded defaults
        logger.warning("No API registry found, using hardcoded defaults")
        return self._default_apis()

    @staticmethod
    def _default_apis() -> List[APIEntry]:
        """Hardcoded fallback API list."""
        return [
            APIEntry({
                "name": "Morrenus",
                "url": "https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key=<moapikey>",
                "status_url": "https://hubcapmanifest.com/api/v1/status/<appid>?api_key=<moapikey>",
                "success_code": 200,
                "requires_key": True,
                "key_param": "moapikey",
                "enabled": True,
                "priority": 1,
            }),
            APIEntry({
                "name": "Ryuu",
                "url": "http://167.235.229.108/<appid>",
                "success_code": 200,
                "enabled": True,
                "priority": 2,
            }),
            APIEntry({
                "name": "Sushi",
                "url": "https://raw.githubusercontent.com/sushi-dev55-alt/sushitools-games-repo-alt/refs/heads/main/<appid>.zip",
                "success_code": 200,
                "enabled": True,
                "priority": 3,
            }),
        ]

    # ── Availability Checks ───────────────────────────────────────────────────

    def check_availability(self, appid: str) -> List[APIAvailability]:
        """Check which APIs have manifests available for the given AppID.

        Runs checks in parallel for speed. Returns a list of
        :class:`APIAvailability` objects ordered by priority.
        """
        appid = str(appid).strip()
        results: List[APIAvailability] = []

        enabled_apis = [api for api in self.apis if api.enabled]
        if not enabled_apis:
            return results

        def _check_one(api: APIEntry) -> APIAvailability:
            import time

            start = time.monotonic()
            url = api.build_url(appid, self.api_key)

            try:
                # For Morrenus, use the status endpoint
                if api.status_url:
                    check_url = api.build_status_url(appid, self.api_key)
                    if check_url:
                        resp = requests.get(
                            check_url,
                            headers={"User-Agent": _USER_AGENT},
                            timeout=_HEAD_TIMEOUT,
                        )
                        available = resp.status_code == api.success_code
                        elapsed = (time.monotonic() - start) * 1000
                        return APIAvailability(api.name, available, url, elapsed)

                # Try HEAD first, fall back to GET
                resp = requests.head(
                    url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_HEAD_TIMEOUT,
                    allow_redirects=True,
                )
                if resp.status_code == api.success_code:
                    elapsed = (time.monotonic() - start) * 1000
                    return APIAvailability(api.name, True, url, elapsed)

                # HEAD failed, try GET
                resp = requests.get(
                    url,
                    headers={"User-Agent": _USER_AGENT},
                    timeout=_HEAD_TIMEOUT,
                    stream=True,
                )
                resp.close()
                available = resp.status_code == api.success_code
                elapsed = (time.monotonic() - start) * 1000
                return APIAvailability(api.name, available, url, elapsed)

            except requests.RequestException as exc:
                elapsed = (time.monotonic() - start) * 1000
                logger.debug("Availability check failed for %s: %s", api.name, exc)
                return APIAvailability(api.name, False, url, elapsed)

        with ThreadPoolExecutor(max_workers=min(5, len(enabled_apis))) as executor:
            futures = {executor.submit(_check_one, api): api for api in enabled_apis}
            for future in as_completed(futures):
                try:
                    results.append(future.result())
                except Exception as exc:
                    api = futures[future]
                    results.append(APIAvailability(api.name, False))
                    logger.debug("Availability check exception for %s: %s", api.name, exc)

        results.sort(key=lambda r: next(
            (a.priority for a in self.apis if a.name == r.name), 99
        ))
        return results

    # ── Manifest Fetching ─────────────────────────────────────────────────────

    def fetch_manifest(
        self,
        appid: str,
        api_key: str = "",
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> ManifestResult:
        """Fetch a manifest package for the given AppID.

        Tries APIs sequentially by priority. Returns the first valid result.

        Parameters
        ----------
        appid : str
            The Steam AppID to fetch manifests for.
        api_key : str, optional
            API key for APIs that require authentication (e.g., Morrenus).
        progress_cb : callable, optional
            ``progress_cb(status_text, bytes_downloaded, total_bytes)``

        Returns
        -------
        ManifestResult
            Contains the ZIP path, API name, and extracted data on success.
        """
        appid = str(appid).strip()
        effective_key = api_key or self.api_key

        # Check cache first
        cached = self._check_cache(appid)
        if cached:
            logger.info("Using cached manifest package for AppID %s", appid)
            return cached

        enabled_apis = [api for api in self.apis if api.enabled]
        if not enabled_apis:
            return ManifestResult(error="No APIs enabled in registry")

        for api in enabled_apis:
            if api.requires_key and not effective_key:
                logger.debug("Skipping %s: requires API key", api.name)
                continue

            url = api.build_url(appid, effective_key)
            logger.info("Trying API %s for AppID %s: %s", api.name, appid, url)

            if progress_cb:
                progress_cb(f"Tentando {api.name}...", 0, 0)

            result = self._download_from_api(appid, api, url, progress_cb)
            if result.success:
                # Cache the successful download
                self._cache_result(appid, result)
                return result

        return ManifestResult(
            error=f"AppID {appid} não encontrado em nenhuma API disponível"
        )

    def fetch_manifest_parallel(
        self,
        appid: str,
        api_key: str = "",
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
    ) -> ManifestResult:
        """Fetch manifest from all APIs in parallel, return the first success.

        This is faster than sequential when multiple APIs may be slow.
        """
        appid = str(appid).strip()
        effective_key = api_key or self.api_key

        # Check cache first
        cached = self._check_cache(appid)
        if cached:
            return cached

        enabled_apis = [
            api for api in self.apis
            if api.enabled and (not api.requires_key or effective_key)
        ]
        if not enabled_apis:
            return ManifestResult(error="No APIs enabled or missing API key")

        result_holder: List[ManifestResult] = []
        cancel_event = threading.Event()

        def _fetch_one(api: APIEntry) -> Optional[ManifestResult]:
            if cancel_event.is_set():
                return None
            url = api.build_url(appid, effective_key)
            res = self._download_from_api(appid, api, url, progress_cb)
            if res.success and not cancel_event.is_set():
                cancel_event.set()
                return res
            return None

        with ThreadPoolExecutor(max_workers=min(4, len(enabled_apis))) as executor:
            futures = {executor.submit(_fetch_one, api): api for api in enabled_apis}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.success:
                        result_holder.append(result)
                        # Cancel remaining futures
                        for remaining in futures:
                            remaining.cancel()
                        break
                except Exception as exc:
                    logger.debug("Parallel fetch exception: %s", exc)

        if result_holder:
            self._cache_result(appid, result_holder[0])
            return result_holder[0]

        return ManifestResult(
            error=f"AppID {appid} não encontrado em nenhuma API disponível"
        )

    # ── Download Logic ────────────────────────────────────────────────────────

    def _download_from_api(
        self,
        appid: str,
        api: APIEntry,
        url: str,
        progress_cb: Optional[Callable] = None,
    ) -> ManifestResult:
        """Download and validate a manifest ZIP from a single API."""
        target_path = self.download_dir / f"lumatools_fetch_{appid}_{api.name}.zip"

        try:
            response = requests.get(
                url,
                timeout=_DOWNLOAD_TIMEOUT,
                stream=True,
                headers={"User-Agent": _USER_AGENT},
            )

            if response.status_code != api.success_code:
                logger.debug(
                    "API %s returned status %d for AppID %s",
                    api.name,
                    response.status_code,
                    appid,
                )
                return ManifestResult(
                    error=f"{api.name}: HTTP {response.status_code}"
                )

            # Download with progress
            total_size = int(response.headers.get("content-length", 0))
            downloaded = 0

            with open(target_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        progress_cb(
                            f"Baixando de {api.name}...",
                            downloaded,
                            total_size,
                        )

            # Validate ZIP
            if not zipfile.is_zipfile(target_path):
                logger.warning(
                    "Download from %s for AppID %s is not a valid ZIP",
                    api.name,
                    appid,
                )
                target_path.unlink(missing_ok=True)
                return ManifestResult(error=f"{api.name}: arquivo não é um ZIP válido")

            # Validate contents
            validation = self._validate_zip_contents(target_path)
            if not validation[0]:
                logger.warning(
                    "ZIP from %s for AppID %s failed validation: %s",
                    api.name,
                    appid,
                    validation[1],
                )
                target_path.unlink(missing_ok=True)
                return ManifestResult(error=f"{api.name}: {validation[1]}")

            lua_content, manifest_files = validation[1], validation[2]

            logger.info(
                "Successfully downloaded manifest from %s for AppID %s (%d bytes, %d manifests)",
                api.name,
                appid,
                downloaded,
                len(manifest_files),
            )

            return ManifestResult(
                success=True,
                zip_path=str(target_path),
                api_name=api.name,
                lua_content=lua_content,
                manifest_files=manifest_files,
            )

        except requests.Timeout:
            logger.debug("API %s timed out for AppID %s", api.name, appid)
            return ManifestResult(error=f"{api.name}: timeout")

        except requests.RequestException as exc:
            logger.debug("API %s request error for AppID %s: %s", api.name, appid, exc)
            return ManifestResult(error=f"{api.name}: {exc}")

        except OSError as exc:
            logger.error("I/O error downloading from %s: %s", api.name, exc)
            return ManifestResult(error=f"{api.name}: I/O error")

    @staticmethod
    def _validate_zip_contents(zip_path: Path) -> Tuple[bool, Any, Any]:
        """Validate that a ZIP contains at least a .lua file and .manifest files.

        Returns
        -------
        tuple
            ``(is_valid, lua_content_or_error, manifest_files_list)``
        """
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                lua_files = [n for n in names if n.lower().endswith(".lua")]
                manifest_files = [n for n in names if n.lower().endswith(".manifest")]

                if not lua_files:
                    return (False, "ZIP não contém arquivo .lua", [])

                # Read the first Lua file
                lua_content = zf.read(lua_files[0]).decode("utf-8", errors="replace")

                # Check for addappid call
                if not re.search(r"addappid\s*\(", lua_content, re.IGNORECASE):
                    return (False, "Lua script não contém chamada addappid()", [])

                return (True, lua_content, manifest_files)

        except (zipfile.BadZipFile, OSError) as exc:
            return (False, f"ZIP inválido: {exc}", [])

    # ── Installation ──────────────────────────────────────────────────────────

    def install_manifest_package(
        self,
        zip_path: str,
        steam_root: str,
        lua_target_dir: Optional[str] = None,
        depotcache_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Extract and install a manifest ZIP package.

        Moves .manifest files to ``depotcache/`` and the .lua script to
        the Lua config directory.

        Parameters
        ----------
        zip_path : str
            Path to the manifest ZIP file.
        steam_root : str
            Steam installation root directory.
        lua_target_dir : str, optional
            Override directory for Lua scripts.
            Default: ``<steam_root>/config/stplug-in/``
        depotcache_dir : str, optional
            Override directory for depot cache.
            Default: ``<steam_root>/depotcache/``

        Returns
        -------
        dict
            ``{'success': bool, 'lua_path': str, 'manifests_installed': int,
              'appid': str, 'error': str}``
        """
        zip_file = Path(zip_path)
        if not zip_file.exists():
            return {"success": False, "error": "ZIP file not found"}

        steam_path = Path(steam_root)
        depot_dir = Path(depotcache_dir) if depotcache_dir else steam_path / "depotcache"
        lua_dir = Path(lua_target_dir) if lua_target_dir else steam_path / "config" / "stplug-in"

        depot_dir.mkdir(parents=True, exist_ok=True)
        lua_dir.mkdir(parents=True, exist_ok=True)

        manifests_installed = 0
        lua_path = ""
        appid = ""

        try:
            with zipfile.ZipFile(zip_file, "r") as zf:
                for name in zf.namelist():
                    lower_name = name.lower()

                    if lower_name.endswith(".manifest"):
                        # Move manifest to depotcache
                        target = depot_dir / Path(name).name
                        with zf.open(name) as src, open(target, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        manifests_installed += 1
                        logger.debug("Installed manifest: %s", target)

                    elif lower_name.endswith(".lua"):
                        # Read Lua content
                        lua_content = zf.read(name).decode("utf-8", errors="replace")

                        # Extract AppID from filename or content
                        fname_match = re.match(r"(\d+)\.lua$", Path(name).name)
                        if fname_match:
                            appid = fname_match.group(1)
                        else:
                            content_match = re.search(
                                r"addappid\s*\(\s*(\d+)", lua_content, re.IGNORECASE
                            )
                            if content_match:
                                appid = content_match.group(1)

                        # Comment out setManifestid calls (like LuaTools does)
                        processed_lines = []
                        for line in lua_content.splitlines():
                            if re.match(r"\s*setManifestid\s*\(", line, re.IGNORECASE):
                                processed_lines.append("-- " + line)
                            else:
                                processed_lines.append(line)

                        processed_content = "\n".join(processed_lines) + "\n"

                        # Write to target dir
                        target_lua = lua_dir / (f"{appid}.lua" if appid else Path(name).name)
                        target_lua.write_text(processed_content, encoding="utf-8")
                        lua_path = str(target_lua)
                        logger.info("Installed Lua script: %s", target_lua)

        except (zipfile.BadZipFile, OSError) as exc:
            return {"success": False, "error": str(exc)}

        return {
            "success": True,
            "lua_path": lua_path,
            "manifests_installed": manifests_installed,
            "appid": appid,
        }

    # ── Cache Management ──────────────────────────────────────────────────────

    def _check_cache(self, appid: str) -> Optional[ManifestResult]:
        """Check if a cached manifest package exists and is valid."""
        pattern = f"lumatools_fetch_{appid}.zip"
        cached_file = self.cache_dir / pattern
        if not cached_file.exists():
            # Also check legacy naming
            for legacy in self.download_dir.glob(f"lumatools_fetch_{appid}_*.zip"):
                if zipfile.is_zipfile(legacy):
                    cached_file = legacy
                    break
            else:
                return None

        validation = self._validate_zip_contents(cached_file)
        if not validation[0]:
            cached_file.unlink(missing_ok=True)
            return None

        return ManifestResult(
            success=True,
            zip_path=str(cached_file),
            api_name="cache",
            lua_content=validation[1],
            manifest_files=validation[2],
        )

    def _cache_result(self, appid: str, result: ManifestResult) -> None:
        """Cache a successful download for future reuse."""
        if not result.success or not result.zip_path:
            return

        cache_target = self.cache_dir / f"lumatools_fetch_{appid}.zip"
        src = Path(result.zip_path)
        if src.exists() and src != cache_target:
            try:
                shutil.copy2(src, cache_target)
                logger.debug("Cached manifest package for AppID %s", appid)
            except OSError as exc:
                logger.debug("Failed to cache manifest: %s", exc)

    def clear_cache(self, appid: Optional[str] = None) -> int:
        """Remove cached manifest packages.

        Parameters
        ----------
        appid : str, optional
            Only clear cache for this AppID. If None, clear all.

        Returns
        -------
        int
            Number of files removed.
        """
        removed = 0
        if appid:
            pattern = f"lumatools_fetch_{appid}*"
        else:
            pattern = "lumatools_fetch_*"

        for f in self.cache_dir.glob(pattern):
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass

        return removed

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Remove temporary download files (not cache)."""
        try:
            for item in self.download_dir.glob("lumatools_fetch_*"):
                if item.parent == self.cache_dir:
                    continue
                if item.is_file():
                    item.unlink()
        except OSError as exc:
            logger.error("Erro ao limpar diretório de downloads: %s", exc)


# ── Backward Compatibility ────────────────────────────────────────────────────
# The old ManifestDownloader class is preserved as an alias so existing imports
# in task_manager.py and elsewhere keep working without changes.

class ManifestDownloader(ManifestEngine):
    """Legacy alias for backward compatibility.

    Old code using ``ManifestDownloader().fetch_manifest(appid, api_key)``
    will continue to work transparently.
    """

    def __init__(self):
        super().__init__()
