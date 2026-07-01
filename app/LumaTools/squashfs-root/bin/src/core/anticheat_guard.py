import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Any

from utils.yaml_config_manager import get_user_config_path, update_yaml_boolean_value

logger = logging.getLogger(__name__)

# Palavras-chave conhecidas associadas a executáveis de Anti-Cheat
KNOWN_AC_KEYWORDS = {
    "vac_module",
    "easyanticheat",
    "eac_launcher",
    "beservice",
    "battleye",
    "vgc.exe",          # Vanguard
    "vgtray.exe",
    "xigncode",
    "nprotect",
    "gameguard",
    "punkbuster",
    "pnkbstr",
    "ricochet",         # CoD AC
}

class AntiCheatGuard:
    """Monitora processos do sistema para detectar anti-cheats e aplicar unhooking preventivo."""

    def __init__(self, check_interval: float = 2.0, api_pipe_path: str = "/tmp/SLSsteam.API"):
        self.check_interval = check_interval
        self.api_pipe_path = api_pipe_path
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        
        # Estado atual: se um AC está rodando no momento
        self.ac_active = False
        self.active_ac_names: Set[str] = set()
        
        # Memória para quando restaurar o SafeMode
        self._original_safe_mode: Optional[bool] = None

    def start(self) -> None:
        """Inicia a thread de monitoramento do daemon."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="AntiCheatGuardThread")
            self._thread.start()
            logger.info("Anti-Cheat Guard started. Monitoring every %.1fs.", self.check_interval)

    def stop(self) -> None:
        """Para a thread de monitoramento."""
        with self._lock:
            self._running = False
        if self._thread:
            self._thread.join(timeout=self.check_interval * 2)
            self._thread = None
            logger.info("Anti-Cheat Guard stopped.")

    def _monitor_loop(self) -> None:
        while self._running:
            try:
                self._check_processes()
            except Exception as e:
                logger.error("Error in AntiCheatGuard loop: %s", e, exc_info=True)
            time.sleep(self.check_interval)

    def _check_processes(self) -> None:
        """Lê /proc para buscar instâncias ativas de anti-cheats conhecidos."""
        found_acs: Set[str] = set()
        
        # Apenas Linux suporta iterar /proc dessa forma rápida
        if os.path.exists("/proc"):
            try:
                for pid_dir in os.listdir("/proc"):
                    if not pid_dir.isdigit():
                        continue
                    
                    cmdline_path = os.path.join("/proc", pid_dir, "cmdline")
                    if not os.path.isfile(cmdline_path):
                        continue
                        
                    try:
                        with open(cmdline_path, 'rb') as f:
                            # cmdline tem argumentos separados por null bytes
                            cmd_bytes = f.read()
                            if not cmd_bytes:
                                continue
                            
                            cmdline = cmd_bytes.replace(b'\x00', b' ').decode('utf-8', errors='ignore').lower()
                            
                            for keyword in KNOWN_AC_KEYWORDS:
                                if keyword in cmdline:
                                    found_acs.add(keyword)
                                    break
                    except OSError:
                        # Processo pode ter terminado enquanto líamos
                        continue
            except OSError as e:
                logger.debug("Failed to list /proc: %s", e)

        self._update_state(found_acs)

    def _update_state(self, found_acs: Set[str]) -> None:
        """Atualiza o estado interno e engatilha ações se o estado mudar."""
        with self._lock:
            if found_acs and not self.ac_active:
                # Anti-Cheat acabou de iniciar
                self.ac_active = True
                self.active_ac_names = found_acs
                logger.warning("DETECTED ANTI-CHEAT INVOCATION: %s. Applying protective measures.", ", ".join(found_acs))
                self._apply_protection()
                
            elif not found_acs and self.ac_active:
                # Anti-Cheat parou
                self.ac_active = False
                logger.info("Anti-Cheat processes (%s) terminated. Restoring normal hooks.", ", ".join(self.active_ac_names))
                self.active_ac_names.clear()
                self._restore_protection()
                
            elif found_acs and self.ac_active:
                # Atualiza conjunto se mudar
                if found_acs != self.active_ac_names:
                    self.active_ac_names = found_acs

    def _apply_protection(self) -> None:
        """Aplica SafeMode e envia comando via pipe para SLSsteam."""
        try:
            # 1. Enviar comando via Pipe se disponível
            if os.path.exists(self.api_pipe_path):
                # O comando exato dependeria da implementação da API do SLSsteam, 
                # assumimos 'reload' ou 'safemode:1' para forçar recarga segura
                try:
                    with open(self.api_pipe_path, 'w') as pipe:
                        pipe.write("safemode:1\n")
                    logger.debug("Sent safemode command to SLSsteam pipe.")
                except OSError as e:
                    logger.warning("Failed to write to SLSsteam pipe: %s", e)

            # 2. Atualizar config.yaml
            config_path = get_user_config_path()
            if config_path.exists():
                # Tenta ler o estado atual para restaurar depois
                with open(config_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match = re.search(r"^\s*SafeMode\s*:\s*(yes|no|true|false)\b", content, re.MULTILINE | re.IGNORECASE)
                    if match:
                        val = match.group(1).lower()
                        self._original_safe_mode = val in ("yes", "true")
                    else:
                        self._original_safe_mode = False # Default

                if update_yaml_boolean_value(config_path, "SafeMode", True):
                    logger.info("SafeMode enabled in config.yaml.")
                
        except Exception as e:
            logger.error("Failed to apply protection: %s", e, exc_info=True)

    def _restore_protection(self) -> None:
        """Restitui SafeMode para o estado anterior."""
        try:
            # 1. Pipe
            if os.path.exists(self.api_pipe_path):
                try:
                    with open(self.api_pipe_path, 'w') as pipe:
                        pipe.write("safemode:0\n")
                    logger.debug("Sent restore safemode command to SLSsteam pipe.")
                except OSError as e:
                    logger.warning("Failed to write to SLSsteam pipe: %s", e)

            # 2. YAML
            if self._original_safe_mode is not None:
                config_path = get_user_config_path()
                if config_path.exists():
                    if update_yaml_boolean_value(config_path, "SafeMode", self._original_safe_mode):
                        logger.info("SafeMode restored to %s in config.yaml.", self._original_safe_mode)
                        
        except Exception as e:
            logger.error("Failed to restore protection: %s", e, exc_info=True)
