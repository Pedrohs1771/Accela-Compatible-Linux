import os
import shutil
import zipfile
import logging
import subprocess
import re
import tarfile
import tempfile
from typing import Optional, List, Tuple
from utils.steam_manifest import get_game_directory

logger = logging.getLogger("LumaTools.OnlineFixInjector")

DEFAULT_ONLINE_FIX_LANGUAGE = "brazilian"

class OnlineFixInjector:
    @staticmethod
    def _safe_target(base_dir: str, relative_path: str) -> str:
        base = os.path.realpath(base_dir)
        target = os.path.realpath(os.path.join(base_dir, relative_path))
        if target != base and not target.startswith(base + os.sep):
            raise ValueError(f"Caminho inseguro dentro do arquivo: {relative_path}")
        return target

    @staticmethod
    def _copy_extracted_tree(source_dir: str, game_dir: str) -> None:
        for root, dirs, files in os.walk(source_dir):
            rel_root = os.path.relpath(root, source_dir)
            if rel_root == ".":
                rel_root = ""
            for directory in dirs:
                target_dir = OnlineFixInjector._safe_target(
                    game_dir, os.path.join(rel_root, directory)
                )
                os.makedirs(target_dir, exist_ok=True)
            for filename in files:
                source_path = os.path.join(root, filename)
                relative = os.path.join(rel_root, filename)
                target_path = OnlineFixInjector._safe_target(game_dir, relative)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.copy2(source_path, target_path)

    @staticmethod
    def _run_extractor(command: List[str]) -> Tuple[bool, str]:
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return result.returncode == 0, output.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            return False, str(exc)

    @staticmethod
    def _extract_rar_with_fallback(fix_path: str, game_dir: str, password: str) -> Tuple[bool, str]:
        extractors = [
            ("7z", ["7z", "x", f"-p{password}", f"-o{game_dir}", fix_path, "-y"]),
            ("unrar", ["unrar", "x", "-o+", f"-p{password}", fix_path, game_dir]),
            ("unar", ["unar", "-force-overwrite", "-password", password, "-output-directory", game_dir, fix_path]),
            ("bsdtar", ["bsdtar", f"--passphrase={password}", "-xf", fix_path, "-C", game_dir]),
        ]

        errors = []
        for name, command in extractors:
            if not shutil.which(command[0]):
                errors.append(f"{name}: não instalado")
                continue
            logger.info("Tentando extrair Online-Fix com %s", name)
            ok, output = OnlineFixInjector._run_extractor(command)
            if ok:
                return True, name
            errors.append(f"{name}: {output or 'falhou'}")

        return False, "\n".join(errors)

    @staticmethod
    def _extract_archive(fix_path: str, game_dir: str) -> Tuple[bool, str]:
        lower = fix_path.lower()
        try:
            with tempfile.TemporaryDirectory(prefix="lumatools-onlinefix-") as tmp_dir:
                if lower.endswith(".zip"):
                    with zipfile.ZipFile(fix_path, "r") as zip_ref:
                        for member in zip_ref.infolist():
                            OnlineFixInjector._safe_target(tmp_dir, member.filename)
                        zip_ref.extractall(tmp_dir)
                    OnlineFixInjector._copy_extracted_tree(tmp_dir, game_dir)
                    return True, "zip"

                if lower.endswith((".tar", ".tar.gz", ".tgz", ".tar.xz", ".txz")):
                    with tarfile.open(fix_path) as tar_ref:
                        for member in tar_ref.getmembers():
                            OnlineFixInjector._safe_target(tmp_dir, member.name)
                        tar_ref.extractall(tmp_dir)
                    OnlineFixInjector._copy_extracted_tree(tmp_dir, game_dir)
                    return True, "tar"

                if lower.endswith(".rar"):
                    ok, details = OnlineFixInjector._extract_rar_with_fallback(
                        fix_path, tmp_dir, "online-fix.me"
                    )
                    if ok:
                        OnlineFixInjector._copy_extracted_tree(tmp_dir, game_dir)
                        return True, details
                    return False, (
                        "Falha ao extrair RAR do Online-Fix.\n"
                        "Tente instalar p7zip-full, unrar, unar ou libarchive-tools.\n"
                        f"Detalhes:\n{details}"
                    )

            return False, f"Formato de fix não suportado: {fix_path}"
        except (OSError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
            return False, f"Arquivo de fix corrompido/incompleto ou sem permissão: {exc}"

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
    def _normalize_onlinefix_language(
        game_dir: str,
        language: str = DEFAULT_ONLINE_FIX_LANGUAGE,
    ) -> List[str]:
        updated_files = []
        language_pattern = re.compile(
            r"^([ \t]*Language[ \t]*=[ \t]*)([^\r\n]*)",
            flags=re.IGNORECASE | re.MULTILINE,
        )
        main_pattern = re.compile(
            r"^[ \t]*\[Main\][ \t]*(?:\r\n|\n|\r|$)",
            flags=re.IGNORECASE | re.MULTILINE,
        )

        for root, _, files in os.walk(game_dir):
            for filename in files:
                if filename.lower() != "onlinefix.ini":
                    continue

                ini_path = os.path.join(root, filename)
                try:
                    with open(
                        ini_path,
                        "r",
                        encoding="utf-8-sig",
                        errors="ignore",
                        newline="",
                    ) as handle:
                        content = handle.read()

                    updated, replacements = language_pattern.subn(
                        lambda match: f"{match.group(1)}{language}",
                        content,
                        count=1,
                    )
                    if not replacements:
                        main_match = main_pattern.search(content)
                        newline = "\r\n" if "\r\n" in content else "\n"
                        if main_match:
                            updated = (
                                content[:main_match.end()]
                                + f"Language={language}{newline}"
                                + content[main_match.end():]
                            )
                        else:
                            updated = (
                                f"[Main]{newline}Language={language}{newline}{newline}"
                                + content
                            )

                    if updated != content:
                        with open(
                            ini_path,
                            "w",
                            encoding="utf-8",
                            newline="",
                        ) as handle:
                            handle.write(updated)
                        updated_files.append(ini_path)
                except OSError as exc:
                    logger.warning(
                        "Não foi possível definir o idioma do Online-Fix em %s: %s",
                        ini_path,
                        exc,
                    )

        return updated_files

    @staticmethod
    def _pe_arch(path: Optional[str]) -> str:
        if not path:
            return ""
        try:
            with open(path, "rb") as f:
                if f.read(2) != b"MZ":
                    return ""
                f.seek(0x3C)
                pe_offset = int.from_bytes(f.read(4), "little")
                f.seek(pe_offset)
                if f.read(4) != b"PE\x00\x00":
                    return ""
                machine = int.from_bytes(f.read(2), "little")
        except OSError:
            return ""
        if machine == 0x014C:
            return "x86"
        if machine == 0x8664:
            return "x64"
        return ""

    @staticmethod
    def _normalize_dlllist(game_dir: str, skip_names: Optional[set] = None) -> List[str]:
        dlllist_path = os.path.join(game_dir, "dlllist.txt")
        if not os.path.isfile(dlllist_path):
            return []

        skip_names = skip_names or set()
        entries = []
        seen = set()
        try:
            with open(dlllist_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f.read().splitlines():
                    filename = os.path.basename(line.strip())
                    if not filename:
                        continue
                    name = os.path.splitext(filename)[0].lower()
                    if name in skip_names or name in seen:
                        continue
                    seen.add(name)
                    entries.append(filename)

            with open(dlllist_path, "w", encoding="utf-8", newline="") as f:
                f.write("\r\n".join(entries))
        except OSError:
            return []

        return [os.path.splitext(entry)[0].lower() for entry in entries]

    @staticmethod
    def inject_fix(game_dir: str, fix_path: str, target_executable: Optional[str] = None, config_modifications: Optional[List[Tuple[str, str, str, str]]] = None) -> Tuple[bool, List[str], str, Optional[str]]:
        if not os.path.exists(game_dir) or not os.path.exists(fix_path):
            return False, [], "", None

        found_overrides = []
        try:
            extracted, extractor_info = OnlineFixInjector._extract_archive(fix_path, game_dir)
            if not extracted:
                logger.error(extractor_info)
                return False, [], extractor_info, None
            logger.info("Online-Fix extraído com: %s", extractor_info)
            localized_files = OnlineFixInjector._normalize_onlinefix_language(game_dir)
            if localized_files:
                logger.info(
                    "Online-Fix configurado para PT-BR em %s arquivo(s).",
                    len(localized_files),
                )
            
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

            def add_override(name: str) -> None:
                name = (name or "").strip().lower()
                if name and name not in found_overrides:
                    found_overrides.append(name)

            main_arch = OnlineFixInjector._pe_arch(actual_main_executable_path)

            def should_skip_override(name: str) -> bool:
                return main_arch == "x86" and name == "steamoverlay32"

            skip_dlllist_names = {"steamoverlay32"} if main_arch == "x86" else set()
            for dll in OnlineFixInjector._normalize_dlllist(game_dir, skip_dlllist_names):
                add_override(dll)

            important_dlls = [
                "version",
                "winmm",
                "winhttp",
                "steam_api",
                "steam_api64",
                "wininet",
                "uplay_r1_loader64",
                "onlinefix",
                "onlinefix64",
                "steamoverlay32",
                "steamoverlay64",
            ]
            for root, _, files in os.walk(game_dir):
                for file in files:
                    name, ext = os.path.splitext(file.lower())
                    if ext == ".dll" and (name in important_dlls or "onlinefix" in name):
                        if main_arch == "x86" and name.endswith("64"):
                            continue
                        if main_arch == "x64" and name.endswith("32"):
                            continue
                        if should_skip_override(name):
                            continue
                        add_override(name)
            
            if main_arch == "x86":
                required_overrides = ["onlinefix", "winmm", "steam_api", "winhttp"]
            elif main_arch == "x64":
                required_overrides = ["onlinefix64", "steamoverlay64", "winmm", "steam_api64", "winhttp"]
            else:
                required_overrides = ["onlinefix", "onlinefix64", "winmm", "steam_api", "steam_api64", "winhttp"]
            for dll in required_overrides:
                add_override(dll)

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
