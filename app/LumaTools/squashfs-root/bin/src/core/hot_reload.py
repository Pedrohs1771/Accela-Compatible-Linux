import os
import threading
import time
import logging
import subprocess
from pathlib import Path
from typing import Callable, Dict, Optional, Set

from utils.yaml_config_manager import get_user_config_path

logger = logging.getLogger(__name__)

class HotReloadWatcher:
    """Monitora diretórios e arquivos para hot reload de configurações e scripts."""

    def __init__(self, check_interval: float = 2.0, api_pipe_path: str = "/tmp/SLSsteam.API"):
        self.check_interval = check_interval
        self.api_pipe_path = api_pipe_path
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Mapeia caminho absoluto para mtime
        self.file_mtimes: Dict[str, float] = {}
        
        # Diretórios monitorados (extensões de interesse)
        self.watch_dirs: Dict[str, Set[str]] = {}
        
        # Callbacks
        self.on_lua_changed: Optional[Callable[[str], None]] = None
        self.on_acf_changed: Optional[Callable[[str], None]] = None
        self.on_config_changed: Optional[Callable[[str], None]] = None

    def add_watch_dir(self, directory: str, extensions: Set[str]) -> None:
        """Adiciona um diretório para monitoramento."""
        abs_dir = os.path.abspath(directory)
        self.watch_dirs[abs_dir] = extensions
        self._initialize_mtimes_for_dir(abs_dir, extensions)

    def _initialize_mtimes_for_dir(self, directory: str, extensions: Set[str]) -> None:
        if not os.path.isdir(directory):
            return
        for root, _, files in os.walk(directory):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if not extensions or ext in extensions:
                    path = os.path.join(root, file)
                    try:
                        self.file_mtimes[path] = os.path.getmtime(path)
                    except OSError:
                        pass

    def start(self) -> None:
        """Inicia a thread de monitoramento."""
        with self._lock:
            if self._running:
                return
            self._running = True
            
            # Inicializa monitoramento do config.yaml
            config_path = str(get_user_config_path())
            try:
                self.file_mtimes[config_path] = os.path.getmtime(config_path)
            except OSError:
                self.file_mtimes[config_path] = 0.0

            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="HotReloadThread")
            self._thread.start()
            logger.info("Hot Reload Engine started. Monitoring every %.1fs.", self.check_interval)

    def stop(self) -> None:
        """Para a thread de monitoramento."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=self.check_interval * 2)
            self._thread = None
            logger.info("Hot Reload Engine stopped.")

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_files()
            except Exception as e:
                logger.error("Error in HotReload loop: %s", e, exc_info=True)
            time.sleep(self.check_interval)

    def _check_files(self) -> None:
        """Verifica mtime de todos os arquivos nos diretórios monitorados."""
        current_files: Set[str] = set()
        
        # Verifica config isolado
        config_path = str(get_user_config_path())
        current_files.add(config_path)
        self._check_single_file(config_path, is_config=True)
        
        # Verifica diretórios
        for directory, extensions in self.watch_dirs.items():
            if not os.path.isdir(directory):
                continue
            for root, _, files in os.walk(directory):
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if not extensions or ext in extensions:
                        path = os.path.join(root, file)
                        current_files.add(path)
                        self._check_single_file(path)
                        
        # Remover arquivos deletados
        deleted_files = set(self.file_mtimes.keys()) - current_files
        for path in deleted_files:
            del self.file_mtimes[path]

    def _check_single_file(self, path: str, is_config: bool = False) -> None:
        try:
            mtime = os.path.getmtime(path)
            last_mtime = self.file_mtimes.get(path, -1)
            
            if last_mtime != -1 and mtime > last_mtime:
                # Arquivo modificado!
                self.file_mtimes[path] = mtime
                self._handle_modification(path, is_config)
            elif last_mtime == -1:
                # Arquivo novo
                self.file_mtimes[path] = mtime
                self._handle_modification(path, is_config)
                
        except OSError:
            pass

    def _handle_modification(self, path: str, is_config: bool) -> None:
        logger.info("Hot reload detected change in: %s", path)
        
        if is_config:
            self._trigger_slssteam_reload()
            if self.on_config_changed:
                self.on_config_changed(path)
        else:
            ext = os.path.splitext(path)[1].lower()
            if ext == ".lua":
                # Reload LUA script
                self._trigger_slssteam_reload()
                if self.on_lua_changed:
                    self.on_lua_changed(path)
            elif ext == ".acf":
                # ACF alterado, notifica Steam
                self._trigger_steam_ui_refresh(path)
                if self.on_acf_changed:
                    self.on_acf_changed(path)

    def _trigger_slssteam_reload(self) -> None:
        """Envia sinal de reload para a API do SLSsteam."""
        if os.path.exists(self.api_pipe_path):
            try:
                with open(self.api_pipe_path, 'w') as pipe:
                    pipe.write("reload\n")
                logger.debug("Sent reload command to SLSsteam API pipe.")
            except OSError as e:
                logger.warning("Failed to write to API pipe for hot reload: %s", e)

    def _trigger_steam_ui_refresh(self, acf_path: str) -> None:
        """Usa steam://nav/library para forçar a Steam a recarregar a interface do jogo."""
        try:
            filename = os.path.basename(acf_path)
            if filename.startswith("appmanifest_") and filename.endswith(".acf"):
                appid = filename.replace("appmanifest_", "").replace(".acf", "")
                if appid.isdigit():
                    logger.info("Refreshing Steam UI for AppID %s", appid)
                    subprocess.Popen(
                        ["steam", f"steam://nav/library/properties/{appid}"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
        except Exception as e:
            logger.warning("Failed to trigger Steam UI refresh: %s", e)
