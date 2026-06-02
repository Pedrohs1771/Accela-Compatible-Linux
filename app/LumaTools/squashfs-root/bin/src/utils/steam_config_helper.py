import os
import re
import logging

logger = logging.getLogger("LumaTools.SteamConfigHelper")

def set_steam_launch_options(steam_root, appid, launch_options):
    """
    Define as opções de inicialização no localconfig.vdf da Steam de forma robusta.
    Lida com escape de aspas e garante que o bloco do AppID exista.
    """
    if not steam_root or not os.path.exists(steam_root):
        return False
        
    userdata_path = os.path.join(steam_root, "userdata")
    if not os.path.exists(userdata_path):
        return False
        
    # Escapar aspas duplas para o formato VDF
    safe_launch_options = launch_options.replace('"', '\\"')
    
    success = False
    for user_id in os.listdir(userdata_path):
        user_config_path = os.path.join(userdata_path, user_id, "config", "localconfig.vdf")
        if os.path.exists(user_config_path):
            try:
                with open(user_config_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Regex para encontrar o bloco do AppID e capturar seu conteúdo
                # Tenta lidar com a estrutura de chaves aninhadas do VDF
                appid_block_pattern = rf'"{appid}"\s*\{{([^}}]*)\}}'
                
                if re.search(rf'"{appid}"', content):
                    if '"LaunchOptions"' in re.search(appid_block_pattern, content, re.DOTALL).group(0) if re.search(appid_block_pattern, content, re.DOTALL) else "":
                        # Substituir LaunchOptions existente dentro do bloco do AppID
                        # Usamos uma abordagem de substituição mais cuidadosa
                        def replace_launch_options(match):
                            block_content = match.group(1)
                            if '"LaunchOptions"' in block_content:
                                return rf'"{appid}"' + " {" + re.sub(r'"LaunchOptions"\s*"[^"]*"', f'"LaunchOptions" "{safe_launch_options}"', block_content) + "}"
                            return match.group(0)
                        
                        new_content = re.sub(appid_block_pattern, replace_launch_options, content, flags=re.DOTALL)
                    else:
                        # Inserir LaunchOptions no início do bloco do AppID
                        new_content = re.sub(
                            rf'("{appid}"\s*\{{)',
                            rf'\1\n\t\t\t\t"LaunchOptions"\t\t"{safe_launch_options}"',
                            content
                        )
                    
                    if new_content != content:
                        with open(user_config_path, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                        success = True
                        logger.info(f"LaunchOptions atualizadas para AppID {appid} no usuário {user_id}")
                else:
                    logger.warning(f"AppID {appid} não encontrado no localconfig.vdf do usuário {user_id}")
                    
            except Exception as e:
                logger.error(f"Erro ao editar localconfig para usuário {user_id}: {e}")
                
    return success
