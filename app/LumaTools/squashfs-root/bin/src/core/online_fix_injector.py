import os
import shutil
import zipfile
import logging
import subprocess
import re
from typing import Optional, List, Tuple
from utils.steam_manifest import get_game_directory

logger = logging.getLogger("LumaTools.OnlineFixInjector")

class OnlineFixInjector:
    @staticmethod
    def _find_main_executable(game_dir: str, target_executable_name: Optional[str] = None) -> Optional[str]:
        """Tenta encontrar o executável principal do jogo, ou um executável específico se fornecido."""
        if target_executable_name:
            for root, _, files in os.walk(game_dir):
                for file in files:
                    if file.lower() == target_executable_name.lower():
                        return os.path.join(root, file)

        common_exec_names = ["lethal company.exe", "game.exe", "launcher.exe", "forzahorizon5.exe", "forzahorizon5_loader.exe"]
        for root, _, files in os.walk(game_dir):
            for file in files:
                if file.lower().endswith(".exe"):
                    if file.lower() in common_exec_names:
                        return os.path.join(root, file)
                    if os.path.basename(root).lower() in file.lower() or "game" in file.lower():
                        return os.path.join(root, file)
        
        for root, _, files in os.walk(game_dir):
            for file in files:
                if file.lower().endswith(".exe"):
                    return os.path.join(root, file)
        return None

    @staticmethod
    def _modify_ini_file(file_path: str, section: str, key: str, value: str) -> bool:
        """Modifica um arquivo .ini lidando com arquivos que podem não ter cabeçalhos de seção."""
        try:
            with open(file_path, 'r') as f:
                lines = f.readlines()

            new_lines = []
            found_section = False
            found_key = False
            
            # Se a seção for "ROOT" ou vazia, tratamos como o topo do arquivo sem seção
            if not section or section.upper() == "ROOT":
                for i, line in enumerate(lines):
                    if not line.strip().startswith("[") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip().lower() == key.lower():
                            new_lines.append(f"{k.strip()} = {value}\n")
                            found_key = True
                            continue
                    new_lines.append(line)
                if not found_key:
                    new_lines.insert(0, f"{key} = {value}\n")
            else:
                for line in lines:
                    if line.strip().startswith(f"[{section}]"):
                        found_section = True
                    elif found_section and line.strip().startswith("["):
                        if not found_key:
                            new_lines.append(f"{key} = {value}\n")
                            found_key = True
                        found_section = False
                    elif found_section and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip().lower() == key.lower():
                            new_lines.append(f"{k.strip()} = {value}\n")
                            found_key = True
                            continue
                    new_lines.append(line)
                
                if found_section and not found_key:
                    new_lines.append(f"{key} = {value}\n")
                elif not found_section:
                    new_lines.append(f"\n[{section}]\n{key} = {value}\n")

            with open(file_path, 'w') as f:
                f.writelines(new_lines)
            return True
        except Exception as e:
            logger.error(f"Erro ao modificar arquivo INI {file_path}: {e}")
            return False

    @staticmethod
    def inject_fix(game_dir: str, fix_path: str, target_executable: Optional[str] = None, config_modifications: Optional[List[Tuple[str, str, str]]] = None) -> Tuple[bool, List[str], str, Optional[str]]:
        if not os.path.exists(game_dir) or not os.path.exists(fix_path):
            return False, [], "", None

        found_overrides = []
        try:
            if fix_path.lower().endswith(".zip"):
                with zipfile.ZipFile(fix_path, 'r') as zip_ref:
                    zip_ref.extractall(game_dir)
            elif fix_path.lower().endswith(".rar"):
                password = "online-fix.me"
                subprocess.run(['7z', 'x', f'-p{password}', f"-o{game_dir}", fix_path, '-y'], check=True, capture_output=True)
            
            # Identificar o executável original (antes de qualquer injeção)
            # Para isso, olhamos o que já existia ou o maior .exe que não seja um loader conhecido
            original_exe = None
            for root, _, files in os.walk(game_dir):
                for file in files:
                    if file.lower().endswith(".exe") and "_loader" not in file.lower() and "onlinefix" not in file.lower():
                        original_exe = file
                        break

            actual_main_executable_path = OnlineFixInjector._find_main_executable(game_dir, target_executable)
            if actual_main_executable_path:
                exec_dir = os.path.dirname(actual_main_executable_path)
                with open(os.path.join(exec_dir, "steam_appid.txt"), "w") as f:
                    f.write("480")

            if config_modifications:
                for file_name, section, key, value in config_modifications:
                    config_file_path = os.path.join(game_dir, file_name)
                    if os.path.exists(config_file_path):
                        OnlineFixInjector._modify_ini_file(config_file_path, section, key, value)

            important_dlls = ["version", "winmm", "winhttp", "steam_api64", "wininet", "uplay_r1_loader64", "onlinefix64", "onlinefix", "steamoverlay64"]
            for root, _, files in os.walk(game_dir):
                for file in files:
                    name, ext = os.path.splitext(file.lower())
                    if ext == ".dll" and (name in important_dlls or "onlinefix" in name):
                        if name not in found_overrides:
                            found_overrides.append(name)
            
            required_overrides = ["onlinefix64", "steamoverlay64", "winmm", "steam_api64", "winhttp"]
            for dll in required_overrides:
                if dll not in found_overrides:
                    found_overrides.append(dll)

            # O separador correto para WINEDLLOVERRIDES no Proton é ';' (ponto e vírgula)
            override_str = ";".join([f"{o}=n,b" for o in found_overrides])
            
            # Lógica robusta de Launch Options
            if target_executable and original_exe and target_executable.lower() != original_exe.lower():
                # Se temos um loader, usamos o eval com sed para garantir que o Steam chame o loader em vez do jogo
                launch_options = f'WINEDLLOVERRIDES="{override_str}" eval "$(echo "%command%" | sed \'s/{original_exe}/{target_executable}/g\')"'
            else:
                launch_options = f'WINEDLLOVERRIDES="{override_str}" %command%'
            
            # Salvar info
            with open(os.path.join(game_dir, "LUMA_ONLINE_FIX_INFO.txt"), "w") as f:
                f.write(f"Launch Options:\n{launch_options}\n\nDLLs: {found_overrides}")
            
            return True, found_overrides, launch_options, actual_main_executable_path
        except Exception as e:
            logger.error(f"Erro: {e}")
            return False, [], "", None
