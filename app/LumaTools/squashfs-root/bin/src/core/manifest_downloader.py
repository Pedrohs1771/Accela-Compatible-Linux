import os
import json
import logging
import threading
import requests
import zipfile
import tempfile
from typing import Dict, List, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class ManifestDownloader:
    """
    Módulo avançado para download de manifestos de múltiplas APIs.
    Inspirado no backend do LuaToolsLinux.
    """
    
    DEFAULT_APIS = [
        {
            "name": "Morrenus",
            "url": "https://hubcapmanifest.com/api/v1/manifest/<appid>?api_key=<moapikey>",
            "enabled": True
        },
        {
            "name": "Ryuu",
            "url": "http://167.235.229.108/<appid>",
            "enabled": True
        },
        {
            "name": "Sushi",
            "url": "https://raw.githubusercontent.com/sushi-dev55-alt/sushitools-games-repo-alt/refs/heads/main/<appid>.zip",
            "enabled": True
        }
    ]

    def __init__(self):
        self.download_dir = Path(tempfile.gettempdir()) / "lumatools_downloads"
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.active_downloads = {}
        self.lock = threading.Lock()

    def fetch_manifest(self, appid: str, api_key: str = "") -> Optional[str]:
        """
        Tenta baixar o manifesto de todas as APIs habilitadas até obter sucesso.
        """
        logger.info(f"Iniciando busca de manifesto para AppID: {appid}")
        
        for api in self.DEFAULT_APIS:
            if not api["enabled"]:
                continue
                
            url = api["url"].replace("<appid>", str(appid)).replace("<moapikey>", api_key)
            logger.info(f"Tentando API: {api['name']} -> {url}")
            
            try:
                response = requests.get(url, timeout=15, stream=True)
                if response.status_code == 200:
                    target_path = self.download_dir / f"manifest_{appid}_{api['name']}.zip"
                    with open(target_path, "wb") as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    if zipfile.is_zipfile(target_path):
                        logger.info(f"Manifesto baixado com sucesso da API {api['name']}")
                        return str(target_path)
                    else:
                        logger.warning(f"Arquivo baixado da API {api['name']} não é um ZIP válido.")
                else:
                    logger.warning(f"API {api['name']} retornou status {response.status_code}")
            except Exception as e:
                logger.error(f"Erro ao acessar API {api['name']}: {e}")
                
        logger.error(f"Não foi possível encontrar manifestos para o AppID {appid} em nenhuma API.")
        return None

    def cleanup(self):
        """Remove arquivos temporários."""
        try:
            for item in self.download_dir.glob("*"):
                if item.is_file():
                    item.unlink()
        except Exception as e:
            logger.error(f"Erro ao limpar diretório de downloads: {e}")
