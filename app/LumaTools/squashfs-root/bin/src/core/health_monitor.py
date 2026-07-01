import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from core.lua_script_generator import parse_lua_script
from utils.steam_manifest import validate_acf_integrity
from utils.yaml_config_manager import get_user_config_path

logger = logging.getLogger(__name__)

class HealthMonitor:
    """Monitor de integridade e auto-diagnóstico do LumaTools e ecossistema associado."""

    def __init__(self, steam_root: str | os.PathLike[str], slssteam_so_path: str | os.PathLike[str]):
        self.steam_root = Path(steam_root).expanduser().resolve()
        self.slssteam_so_path = Path(slssteam_so_path).expanduser().resolve()
        self.report: Dict[str, Any] = {
            "status": "ok",
            "issues": [],
            "repairs": []
        }

    def _add_issue(self, severity: str, message: str, component: str) -> None:
        if severity in ["error", "critical"]:
            self.report["status"] = "error"
        elif severity == "warning" and self.report["status"] == "ok":
            self.report["status"] = "warning"
            
        self.report["issues"].append({
            "severity": severity,
            "component": component,
            "message": message
        })
        logger.log(logging.WARNING if severity == "warning" else logging.ERROR, "[%s] %s", component, message)

    def _add_repair(self, message: str, component: str) -> None:
        self.report["repairs"].append({
            "component": component,
            "message": message
        })
        logger.info("[%s] Repaired: %s", component, message)

    def check_slssteam_health(self) -> None:
        """Verifica SLSsteam.so e config.yaml."""
        if not self.slssteam_so_path.exists():
            self._add_issue("critical", f"SLSsteam.so not found at {self.slssteam_so_path}", "SLSsteam")
            return
            
        try:
            # Verifica ELF type (deve ser 32-bit para a steam client)
            result = subprocess.run(["file", "-b", str(self.slssteam_so_path)], capture_output=True, text=True)
            if "32-bit" not in result.stdout and "ELF" in result.stdout:
                self._add_issue("error", f"SLSsteam.so is not 32-bit: {result.stdout.strip()}", "SLSsteam")
        except FileNotFoundError:
            pass # 'file' command missing
            
        config_path = get_user_config_path()
        if not config_path.exists():
            self._add_issue("warning", f"config.yaml not found at {config_path}", "SLSsteam Config")

    def check_manifest_consistency(self, managed_appids: List[str]) -> None:
        """Verifica integridade dos manifests para os jogos gerenciados."""
        for appid in managed_appids:
            if not validate_acf_integrity(str(self.steam_root), appid):
                self._add_issue("warning", f"Appmanifest for AppID {appid} is inconsistent or missing.", "Manifests")

    def check_lua_script_validity(self, plugins_dir: str | os.PathLike[str]) -> None:
        """Valida scripts LUA usando o parser."""
        plugins = Path(plugins_dir).expanduser().resolve()
        if not plugins.exists():
            return
            
        for lua_file in plugins.glob("*.lua"):
            try:
                content = lua_file.read_text(encoding="utf-8", errors="ignore")
                data = parse_lua_script(content)
                if not data.get("appids"):
                    self._add_issue("warning", f"Script {lua_file.name} has no valid addappid() calls.", "LUA Scripts")
            except Exception as e:
                self._add_issue("error", f"Failed to parse script {lua_file.name}: {e}", "LUA Scripts")

    def check_proton_compatibility(self, game_dir: str | os.PathLike[str]) -> None:
        """Verifica se existe compatibilidade Proton requerida."""
        root = Path(game_dir).expanduser().resolve()
        if not root.exists():
            return
            
        has_exe = any(root.glob("*.exe"))
        has_online_fix = (root / "LUMA_ONLINE_FIX_INFO.txt").exists()
        
        if has_exe and has_online_fix:
            # Requer override
            content = (root / "LUMA_ONLINE_FIX_INFO.txt").read_text(encoding="utf-8")
            if "WINEDLLOVERRIDES" not in content:
                self._add_issue("warning", f"Online Fix in {root.name} might be missing WINEDLLOVERRIDES.", "Proton")

    def check_online_fix_integrity(self, game_dir: str | os.PathLike[str]) -> None:
        """Verifica se as DLLs do Online Fix estão íntegras."""
        root = Path(game_dir).expanduser().resolve()
        if not (root / "LUMA_ONLINE_FIX_INFO.txt").exists():
            return
            
        if not any(root.rglob("OnlineFix64.dll")) and not any(root.rglob("OnlineFix.dll")):
            self._add_issue("error", f"OnlineFix DLLs missing in {root.name} despite LUMA_ONLINE_FIX_INFO.txt", "OnlineFix")

    def auto_repair(self, managed_appids: List[str]) -> None:
        """Tenta corrigir automaticamente os problemas encontrados."""
        for issue in self.report["issues"]:
            if issue["component"] == "Manifests" and "AppID" in issue["message"]:
                # Exemplo de auto repair para manifest: reescreve ACF com status de update
                appid = issue["message"].split("AppID ")[1].split(" ")[0]
                from utils.steam_manifest import repair_installed_app_state
                if repair_installed_app_state(str(self.steam_root), appid):
                    self._add_repair(f"Repaired manifest for AppID {appid}", "Manifests")
                    
            elif issue["component"] == "SLSsteam Config" and "not found" in issue["message"]:
                from utils.yaml_config_manager import ensure_slssteam_config
                ensure_slssteam_config(get_user_config_path())
                self._add_repair("Created default SLSsteam config.yaml", "SLSsteam Config")

    def generate_diagnostic_report(self) -> Dict[str, Any]:
        """Gera o relatório final e zera o estado."""
        final_report = dict(self.report)
        self.report = {
            "status": "ok",
            "issues": [],
            "repairs": []
        }
        return final_report
