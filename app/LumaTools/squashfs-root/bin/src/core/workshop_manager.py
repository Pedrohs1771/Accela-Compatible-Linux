import os
import re
import sys
import logging
import subprocess
import threading
import json
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class WorkshopManager:
    """
    Gerenciador de downloads do Workshop para Linux.
    Utiliza o DepotDownloader para baixar conteúdo diretamente.
    """
    
    def __init__(self):
        self.state = {
            "status": "idle",
            "progress": 0.0,
            "message": "",
            "last_error": ""
        }
        self.process = None
        self.lock = threading.Lock()

    def _get_depot_downloader_path(self) -> str:
        """Localiza o executável do DepotDownloader."""
        # Tenta caminhos comuns no LumaTools
        base_dir = Path(__file__).parent.parent.parent.parent # app/LumaTools
        potential_paths = [
            base_dir / "squashfs-root" / "bin" / "DepotDownloader",
            base_dir / "squashfs-root" / "bin" / "DepotDownloaderMod",
            Path.home() / ".local" / "share" / "LumaTools" / "squashfs-root" / "bin" / "DepotDownloader"
        ]
        
        for path in potential_paths:
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        
        # Fallback para o comando global se existir
        return "DepotDownloader"

    def download_item(self, appid: int, pubfile_id: int, download_dir: str):
        """Inicia o download de um item do workshop em uma thread separada."""
        thread = threading.Thread(target=self._run_download, args=(appid, pubfile_id, download_dir))
        thread.daemon = True
        thread.start()

    def _run_download(self, appid: int, pubfile_id: int, download_dir: str):
        with self.lock:
            if self.state["status"] == "downloading":
                logger.warning("Download já em progresso.")
                return
            self.state["status"] = "downloading"
            self.state["progress"] = 0.0
            self.state["message"] = "Iniciando download do Workshop..."

        exe = self._get_depot_downloader_path()
        cmd = [
            exe,
            "-app", str(appid),
            "-pubfile", str(pubfile_id),
            "-dir", download_dir,
            "-max-downloads", "8"
        ]

        logger.info(f"Executando comando: {' '.join(cmd)}")
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace'
            )

            percent_regex = re.compile(r"(\d{1,3}\.\d{2})%")
            
            for line in self.process.stdout:
                line = line.strip()
                if not line: continue
                
                match = percent_regex.search(line)
                with self.lock:
                    if match:
                        self.state["progress"] = float(match.group(1))
                        self.state["message"] = f"Baixando: {self.state['progress']}%"
                    else:
                        self.state["message"] = line

            rc = self.process.wait()
            with self.lock:
                if rc == 0:
                    self.state["status"] = "done"
                    self.state["message"] = "Download do Workshop concluído!"
                    self.state["progress"] = 100.0
                else:
                    self.state["status"] = "failed"
                    self.state["message"] = f"Erro no download (Código {rc})"
                    
        except Exception as e:
            with self.lock:
                self.state["status"] = "failed"
                self.state["message"] = f"Erro interno: {str(e)}"
                logger.error(f"Erro no WorkshopManager: {e}")

    def get_status(self) -> Dict[str, Any]:
        with self.lock:
            return self.state.copy()

    def cancel(self):
        with self.lock:
            if self.process:
                self.process.kill()
                self.state["status"] = "cancelled"
                self.state["message"] = "Download cancelado pelo usuário."
