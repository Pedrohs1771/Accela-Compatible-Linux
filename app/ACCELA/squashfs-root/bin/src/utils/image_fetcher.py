import logging
import time
from functools import wraps
from typing import List, Optional, Union

import requests
from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkReply,
    QNetworkRequest,
)

# Attempt to import DatabaseManager, handling potential path variations
try:
    from managers.db_manager import DatabaseManager
except ImportError:
    try:
        from db_manager import DatabaseManager
    except ImportError:
        DatabaseManager = None
        logging.getLogger(__name__).warning(
            "Could not import DatabaseManager. DB cache will be disabled."
        )

logger = logging.getLogger(__name__)

# Global network manager - shared across all fetchers, lives on main thread
_network_manager: Optional[QNetworkAccessManager] = None


def get_network_manager() -> QNetworkAccessManager:
    """Get or create global QNetworkAccessManager (must run on main thread)."""
    global _network_manager
    if _network_manager is None:
        _network_manager = QNetworkAccessManager()
    return _network_manager


def time_function(func):
    """Decorator to time function execution."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        end_time = time.time()
        execution_time = (end_time - start_time) * 1000
        # Only log if it takes a noticeable amount of time (>10ms) to reduce spam
        if execution_time > 10:
            logger.debug(f"{func.__name__} executed in {execution_time:.2f}ms")
        return result

    return wrapper


def send_request(url: str) -> bool:
    """Fast URL validation using HEAD requests."""
    try:
        response = requests.head(
            url,
            timeout=1.5,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        return response.status_code == 200
    except Exception as e:
        logger.debug(f"URL check failed for {url}: {e}")
        return False


class ImageFetcher(QObject):
    """Async image fetcher using Qt's QNetworkAccessManager (no threads)."""

    finished = pyqtSignal(bytes)

    def __init__(self, url: str):
        super().__init__()
        self.url = url
        self._stopped = False
        self._reply: Optional[QNetworkReply] = None
        self._start_time: Optional[float] = None

    def stop(self) -> None:
        """Abort the request and prevent signal emission."""
        self._stopped = True
        if self._reply is not None:
            self._reply.abort()

    def start(self) -> None:
        """Start the async fetch using QNetworkAccessManager."""
        if self._stopped:
            return

        self._start_time = time.time()
        manager = get_network_manager()

        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"User-Agent", b"Mozilla/5.0")

        self._reply = manager.get(request)
        # ignore type error for connect
        self._reply.finished.connect(self._on_finished)  # type: ignore

    def _on_finished(self) -> None:
        """Handle the network reply."""
        # Guard Clause: Invalid state
        if self._stopped or self._reply is None:
            if self._reply:
                self._reply.deleteLater()
            return

        reply = self._reply
        self._reply = None

        try:
            # Guard Clause: Network Error
            if reply.error() != QNetworkReply.NetworkError.NoError:
                logger.debug(
                    f"Failed to fetch image from {self.url}: {reply.errorString()}"
                )
                if not self._stopped:
                    self.finished.emit(b"")
                return

            # 3. Success Path
            data = reply.readAll().data()  # .data() returns Python bytes

            if self._start_time:
                download_time = (time.time() - self._start_time) * 1000
                if download_time > 100:
                    logger.debug(
                        f"Downloaded {len(data)} bytes from {self.url} "
                        f"in {download_time:.2f}ms"
                    )

            if not self._stopped:
                self.finished.emit(data)

        finally:
            reply.deleteLater()

    # Legacy method for compatibility
    def run(self) -> None:
        self.start()

    @staticmethod
    @time_function
    def _get_best_image_url(url_list: List[str]) -> str:
        """URL checking with HEAD requests to find a working image URL."""
        if len(url_list) == 1:
            return url_list[0]

        for url in url_list:
            if send_request(url):
                return url

        # Fallback
        return url_list[0]

    @staticmethod
    @time_function
    def get_header_image_url(app_id: Union[int, str]) -> str:
        """
        Get the best header image URL for a given app ID.
        Prioritizes Local DB
        """
        # Try DB for the specific hash URL
        if DatabaseManager:
            try:
                # Force string for DB lookup consistency
                db_url = DatabaseManager().get_header_url(str(app_id))
                if db_url:
                    # logger.debug(f"DB Cache HIT for AppID {app_id}")
                    return db_url
                # else:
                #     logger.debug(f"DB Cache MISS for AppID {app_id}")
            except Exception as e:
                # LOG the error instead of silently passing
                logger.warning(f"DB Cache lookup failed for AppID {app_id}: {e}")

        # 2. Fallback to generic URL construction
        base_urls = [
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
            f"https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{app_id}/library_header.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_hero.jpg",
        ]

        # Specific override for known issues
        if str(app_id) == "3949040":
            return (
                "https://cdn.akamai.steamstatic.com/steam/apps/3949040/library_hero.jpg"
            )

        # Return first URL immediately - validation is too slow for UI lists
        return base_urls[0]

    @staticmethod
    @time_function
    def fetch_header_from_web_api(app_id: Union[int, str]) -> Optional[str]:
        url = "https://store.steampowered.com/api/appdetails"
        params = {"appids": app_id}
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as e:
            logger.warning(f"Header API request failed for AppID {app_id}: {e}")
            return None

        app_data = data.get(str(app_id))
        if not app_data or not app_data.get("success"):
            return None

        return app_data.get("data", {}).get("header_image")

    @staticmethod
    def get_capsule_image_url(app_id: Union[int, str]) -> str:
        """Get the best capsule image URL for a given app ID."""
        urls = [
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_184x69.jpg",
            f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_capsule.jpg",
        ]

        if str(app_id) == "3949040":
            return "https://cdn.akamai.steamstatic.com/steam/apps/3949040/library_capsule.jpg"

        return ImageFetcher._get_best_image_url(urls)
