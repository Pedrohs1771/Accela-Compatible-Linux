import requests
from bs4 import BeautifulSoup
import re
import os
from urllib.parse import quote_plus

class OnlineFixAPI:
    def __init__(self):
        self.base_url = "https://online-fix.me"
        self.session = requests.Session()
        # Cookies atualizados ou genéricos (o site às vezes permite busca básica sem login)
        self.cookies = {
            "dle_user_id": "5418946",
            "dle_password": "536a9921c326943c916f503080fc67a6",
            "PHPSESSID": "0sbefsht4ojcfddbaic3jk8brp"
        }
        self.session.cookies.update(self.cookies)
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://online-fix.me/"
        })

    def search_game(self, query):
        """Busca um jogo usando o método GET que é mais resiliente."""
        # Limpar a query para a busca
        clean_query = quote_plus(query)
        search_url = f"{self.base_url}/index.php?do=search&subaction=search&story={clean_query}"
        
        try:
            response = self.session.get(search_url)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Procurar links de jogos nos resultados
            # No Online-Fix, os resultados costumam estar em divs com a classe 'base' ou 'article'
            articles = soup.find_all(['div', 'article'], class_=['base', 'short-story', 'movie-item'])
            
            if not articles:
                # Tentativa secundária: todos os links que contêm /games/
                all_links = soup.find_all('a', href=True)
                for a in all_links:
                    href = a['href']
                    if '/games/' in href and query.lower() in a.get_text().lower():
                        return href
                return None

            for article in articles:
                a = article.find('a', href=True)
                if a and '/games/' in a['href']:
                    # Se o título bater com a busca, retornamos
                    title = a.get_text().lower()
                    if query.lower() in title:
                        return a['href']
            
            # Se não achou por título exato, pega o primeiro link de jogo válido
            for article in articles:
                a = article.find('a', href=True)
                if a and '/games/' in a['href']:
                    return a['href']
                    
            return None
        except Exception as e:
            print(f"Erro na busca: {e}")
            return None

    def get_fix_download_link(self, game_page_url):
        """Extrai o link da pasta de uploads da página de detalhes."""
        try:
            response = self.session.get(game_page_url)
            if response.status_code != 200:
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            all_links = soup.find_all('a', href=True)
            
            # Procurar por links de servidores de upload conhecidos
            targets = ['uploads.online-fix.me', 'hosters.online-fix.me', 'drive.online-fix.me']
            
            for a in all_links:
                href = a['href']
                if any(t in href for t in targets):
                    # Priorizar o link de 'uploads' pois é onde o fix costuma estar
                    if 'uploads.online-fix.me' in href:
                        return href
            
            # Se não achou uploads, tenta qualquer um dos outros
            for a in all_links:
                href = a['href']
                if any(t in href for t in targets):
                    return href
            
            return None
        except Exception as e:
            print(f"Erro ao extrair link: {e}")
            return None

    def get_direct_files(self, upload_url):
        """Lista os arquivos na pasta de uploads e retorna o link do .rar/.zip do fix."""
        try:
            # Garantir que a URL termina com /
            if not upload_url.endswith('/'):
                upload_url += '/'
                
            # Tentar entrar na pasta 'Fix Repair' se ela existir no caminho
            if 'Fix%20Repair' not in upload_url:
                test_url = upload_url + 'Fix%20Repair/'
                resp = self.session.get(test_url)
                if resp.status_code == 200:
                    upload_url = test_url
            
            response = self.session.get(upload_url)
            if response.status_code != 200:
                return []

            soup = BeautifulSoup(response.text, 'html.parser')
            files = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                # Filtrar arquivos de fix (geralmente .rar ou .zip)
                if href.lower().endswith(('.rar', '.zip')) and not href.startswith(('/', '..')):
                    # Construir URL absoluta
                    full_url = upload_url + href.lstrip('/')
                    files.append(full_url)
            
            # Ordenar para preferir arquivos que contenham 'Fix' ou 'Repair' no nome
            files.sort(key=lambda x: ('fix' in x.lower() or 'repair' in x.lower()), reverse=True)
            
            return files
        except Exception as e:
            print(f"Erro ao listar arquivos: {e}")
            return []

    def download_file(self, file_url, save_path, progress_callback=None):
        """Realiza o download do fix com suporte a callback de progresso."""
        try:
            response = self.session.get(file_url, stream=True, timeout=30)
            total_size = int(response.headers.get('content-length', 0))
            
            if response.status_code == 200:
                downloaded = 0
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                progress_callback(int(100 * downloaded / total_size))
                return True
        except Exception as e:
            print(f"Erro no download: {e}")
        return False
