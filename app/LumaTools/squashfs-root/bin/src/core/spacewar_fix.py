"""
LumaTools — Spacewar Fix (AppID 480) para Multiplayer Online.

Aplica o fix universal de redirecionamento para o AppID 480 (Spacewar)
para permitir multiplayer via lobby em jogos desbloqueados.

Baseado na abordagem do OpenSteamTool ``-onlinefix`` e do OnlineFix.me,
adaptado para funcionar tanto com SLSsteam (Linux) quanto com
OpenSteamTool/GreenLuma (Windows).

Fluxo:
1. Gera ``steam_appid.txt`` com 480 no diretório do jogo
2. Gera ``force_appid.txt`` com o AppID real (para Goldberg/CreamAPI)
3. Configura ``FakeAppIds:`` no config.yaml do SLSsteam
4. Adiciona ``-onlinefix`` nas opções de lançamento do Steam
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SPACEWAR_APPID = "480"
STEAM_APPID_FILENAME = "steam_appid.txt"
FORCE_APPID_FILENAME = "force_appid.txt"
ONLINE_FIX_LAUNCH_OPTION = "-onlinefix"


class SpacewarFix:
    """Aplica o fix universal de AppID 480 (Spacewar) para multiplayer."""

    def apply(
        self,
        game_dir: str | os.PathLike[str],
        real_appid: str,
        config_path: Optional[Path] = None,
        *,
        set_launch_options: bool = True,
    ) -> dict[str, bool]:
        """Aplica o fix Spacewar para o jogo.

        Parameters
        ----------
        game_dir : str or Path
            Diretório de instalação do jogo.
        real_appid : str
            AppID real do jogo (usado no force_appid.txt).
        config_path : Path, optional
            Caminho do config.yaml do SLSsteam.
        set_launch_options : bool
            Se True, adiciona ``-onlinefix`` nas launch options do Steam.

        Returns
        -------
        dict
            Status de cada etapa: ``{'steam_appid': bool, 'force_appid': bool,
            'config_yaml': bool, 'launch_options': bool}``
        """
        game_path = Path(game_dir)
        results = {
            "steam_appid": False,
            "force_appid": False,
            "config_yaml": False,
            "launch_options": False,
        }

        if not game_path.exists():
            logger.error("Game directory does not exist: %s", game_path)
            return results

        real_appid = str(real_appid).strip()
        if not real_appid.isdigit():
            logger.error("Invalid AppID: %s", real_appid)
            return results

        # 1. Write steam_appid.txt with 480
        results["steam_appid"] = self._write_steam_appid(game_path)

        # 2. Write force_appid.txt with real AppID
        results["force_appid"] = self._write_force_appid(game_path, real_appid)

        # 3. Configure FakeAppIds in SLSsteam config.yaml
        if config_path or sys.platform == "linux":
            results["config_yaml"] = self._configure_fake_appid(
                real_appid, config_path
            )

        # 4. Set launch options
        if set_launch_options:
            results["launch_options"] = self._set_launch_options(real_appid)

        success_count = sum(1 for v in results.values() if v)
        logger.info(
            "SpacewarFix applied for AppID %s: %d/4 steps successful",
            real_appid,
            success_count,
        )
        return results

    def remove(
        self,
        game_dir: str | os.PathLike[str],
        real_appid: str,
        config_path: Optional[Path] = None,
    ) -> bool:
        """Remove o fix Spacewar de um jogo.

        Parameters
        ----------
        game_dir : str or Path
            Diretório de instalação do jogo.
        real_appid : str
            AppID real do jogo.
        config_path : Path, optional
            Caminho do config.yaml do SLSsteam.

        Returns
        -------
        bool
            True se pelo menos uma remoção foi bem-sucedida.
        """
        game_path = Path(game_dir)
        removed_any = False

        # Remove steam_appid.txt
        steam_appid_file = game_path / STEAM_APPID_FILENAME
        if steam_appid_file.exists():
            try:
                steam_appid_file.unlink()
                logger.info("Removed %s from %s", STEAM_APPID_FILENAME, game_path)
                removed_any = True
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", steam_appid_file, exc)

        # Remove force_appid.txt
        force_appid_file = game_path / FORCE_APPID_FILENAME
        if force_appid_file.exists():
            try:
                force_appid_file.unlink()
                logger.info("Removed %s from %s", FORCE_APPID_FILENAME, game_path)
                removed_any = True
            except OSError as exc:
                logger.warning("Failed to remove %s: %s", force_appid_file, exc)

        # Remove from config.yaml
        if config_path or sys.platform == "linux":
            self._remove_fake_appid(str(real_appid).strip(), config_path)
            removed_any = True

        return removed_any

    def is_applied(self, game_dir: str | os.PathLike[str]) -> bool:
        """Check if the Spacewar fix is currently applied."""
        game_path = Path(game_dir)
        steam_appid_file = game_path / STEAM_APPID_FILENAME
        if not steam_appid_file.exists():
            return False

        try:
            content = steam_appid_file.read_text(encoding="utf-8").strip()
            return content == SPACEWAR_APPID
        except OSError:
            return False

    # ── Internal Methods ──────────────────────────────────────────────────────

    @staticmethod
    def _write_steam_appid(game_dir: Path) -> bool:
        """Write steam_appid.txt with Spacewar AppID (480)."""
        target = game_dir / STEAM_APPID_FILENAME
        try:
            target.write_text(SPACEWAR_APPID + "\n", encoding="utf-8")
            logger.debug("Wrote %s with AppID %s", target, SPACEWAR_APPID)
            return True
        except OSError as exc:
            logger.error("Failed to write %s: %s", target, exc)
            return False

    @staticmethod
    def _write_force_appid(game_dir: Path, real_appid: str) -> bool:
        """Write force_appid.txt with the real AppID (for Goldberg)."""
        target = game_dir / FORCE_APPID_FILENAME
        try:
            target.write_text(real_appid + "\n", encoding="utf-8")
            logger.debug("Wrote %s with AppID %s", target, real_appid)
            return True
        except OSError as exc:
            logger.error("Failed to write %s: %s", target, exc)
            return False

    @staticmethod
    def _configure_fake_appid(
        real_appid: str,
        config_path: Optional[Path] = None,
    ) -> bool:
        """Add FakeAppId mapping in SLSsteam config.yaml.

        Maps the real AppID to 480 in the FakeAppIds section.
        """
        try:
            from utils.yaml_config_manager import get_user_config_path

            path = config_path or get_user_config_path()
            if not path.exists():
                logger.debug("Config file not found: %s", path)
                return False

            content = path.read_text(encoding="utf-8")

            # Check if FakeAppIds section exists
            fake_section_pattern = re.compile(r"^FakeAppIds:\s*$", re.MULTILINE)
            match = fake_section_pattern.search(content)

            entry = f"  {real_appid}: {SPACEWAR_APPID}"

            if match:
                # Check if this AppID already has a mapping
                existing = re.search(
                    rf"^\s*{re.escape(real_appid)}\s*:",
                    content[match.end():],
                    re.MULTILINE,
                )
                if existing:
                    logger.debug(
                        "FakeAppId mapping already exists for %s", real_appid
                    )
                    return True

                # Find insertion point (after last entry in FakeAppIds section)
                section_start = match.end()
                if section_start < len(content) and content[section_start] == "\n":
                    section_start += 1

                # Find next top-level key
                remaining = content[section_start:]
                next_key = re.search(r"^[A-Za-z]", remaining, re.MULTILINE)
                if next_key:
                    insert_pos = section_start + next_key.start()
                else:
                    insert_pos = len(content)

                new_content = (
                    content[:insert_pos]
                    + entry + "\n"
                    + content[insert_pos:]
                )
            else:
                # Create FakeAppIds section
                new_content = content.rstrip() + f"\nFakeAppIds:\n{entry}\n"

            path.write_text(new_content, encoding="utf-8")
            logger.info(
                "Configured FakeAppId: %s → %s in %s",
                real_appid,
                SPACEWAR_APPID,
                path,
            )
            return True

        except Exception as exc:
            logger.error("Failed to configure FakeAppId: %s", exc)
            return False

    @staticmethod
    def _remove_fake_appid(
        real_appid: str,
        config_path: Optional[Path] = None,
    ) -> bool:
        """Remove FakeAppId mapping from config.yaml."""
        try:
            from utils.yaml_config_manager import get_user_config_path

            path = config_path or get_user_config_path()
            if not path.exists():
                return False

            content = path.read_text(encoding="utf-8")
            pattern = re.compile(
                rf"^\s*{re.escape(real_appid)}\s*:\s*{SPACEWAR_APPID}\s*$\n?",
                re.MULTILINE,
            )
            new_content = pattern.sub("", content)
            if new_content != content:
                path.write_text(new_content, encoding="utf-8")
                logger.info("Removed FakeAppId for %s", real_appid)
                return True
            return False

        except Exception as exc:
            logger.error("Failed to remove FakeAppId: %s", exc)
            return False

    @staticmethod
    def _set_launch_options(real_appid: str) -> bool:
        """Add -onlinefix to Steam launch options for the app.

        This modifies ``localconfig.vdf`` to include the launch option.
        """
        if sys.platform != "linux":
            # On Windows, OpenSteamTool handles this via its own config
            logger.debug("Launch options only managed on Linux")
            return True

        try:
            from core.steam_helpers import find_steam_install

            steam_path = find_steam_install()
            if not steam_path:
                return False

            userdata_dir = Path(steam_path) / "userdata"
            if not userdata_dir.exists():
                return False

            modified = False
            for user_dir in userdata_dir.iterdir():
                if not user_dir.is_dir():
                    continue

                config_file = user_dir / "config" / "localconfig.vdf"
                if not config_file.exists():
                    continue

                try:
                    content = config_file.read_text(encoding="utf-8", errors="ignore")

                    # Look for existing launch options for this AppID
                    pattern = re.compile(
                        rf'"{re.escape(real_appid)}"'
                        r'\s*\{[^}]*?"LaunchOptions"\s*"([^"]*)"',
                        re.DOTALL,
                    )
                    match = pattern.search(content)

                    if match:
                        current_options = match.group(1)
                        if ONLINE_FIX_LAUNCH_OPTION in current_options:
                            continue  # Already set

                        new_options = (current_options.strip() + " " + ONLINE_FIX_LAUNCH_OPTION).strip()
                        new_content = (
                            content[:match.start(1)]
                            + new_options
                            + content[match.end(1):]
                        )
                        config_file.write_text(new_content, encoding="utf-8")
                        modified = True
                        logger.info(
                            "Added %s to launch options for AppID %s (user %s)",
                            ONLINE_FIX_LAUNCH_OPTION,
                            real_appid,
                            user_dir.name,
                        )
                except OSError as exc:
                    logger.debug("Failed to modify localconfig for user %s: %s", user_dir.name, exc)

            return modified

        except Exception as exc:
            logger.error("Failed to set launch options: %s", exc)
            return False
