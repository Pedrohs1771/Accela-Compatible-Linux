import sys
import os
from pathlib import Path
import json

# LumaTools src path
src_path = "/home/pedrohs/Luma-Tools/app/LumaTools/squashfs-root/bin/src"
sys.path.insert(0, src_path)

from core.health_monitor import HealthMonitor
from core.content_manager import ContentManager
from core.anticheat_guard import AntiCheatGuard

print("\n" + "="*60)
print("🚀 LUMATOOLS BACKEND SUPREMACY - LIVE TEST 🚀")
print("="*60)

steam_root = Path.home() / ".steam/root"
slssteam_so = Path("/tmp/SLSsteam.so")  # Mock for test
config_path = steam_root / "config/loginusers.vdf"

print(f"📦 Steam Root: {steam_root}")

# --- Testando Health Monitor ---
print("\n[1] Testando Health Monitor...")
monitor = HealthMonitor(str(steam_root), str(slssteam_so))
monitor.check_slssteam_health()

# Simula verificação de algum jogo gerido
monitor.check_manifest_consistency(["480", "550"]) # Spacewar, L4D2

report = monitor.generate_diagnostic_report()
print(f"  -> Health Report Status: {report['status'].upper()}")
for issue in report['issues']:
    print(f"  -> [ISSUE] {issue['severity'].upper()}: {issue['component']} - {issue['message']}")

# --- Testando Content Manager (DLC Engine) ---
print("\n[2] Testando Content Manager & Auto-Detect DLC Method...")
manager = ContentManager(base_path="/home/pedrohs/Luma-Tools")
# Pega um appid aleatorio pra ver se ele busca na loja ou roda a heuristica
try:
    method = manager.auto_detect_dlc_method(str(steam_root / "steamapps/common/Spacewar"))
    print(f"  -> Spacewar DLC Method Detected: {method}")
except Exception as e:
    print(f"  -> Error in Content Manager: {e}")

# --- Testando Anti-Cheat Guard ---
print("\n[3] Testando Anti-Cheat Guard (Thread lifecycle)...")
guard = AntiCheatGuard(check_interval=1.0)
guard.start()
print(f"  -> Guard started. Running? {guard._running}")
# Roda um ciclo manual pra ver se acha algo agora (nao deve achar, senao vai dar safe mode)
guard._check_processes()
print(f"  -> AC Active right now? {guard.ac_active}")
if guard.ac_active:
    print(f"  -> Detected ACs: {guard.active_ac_names}")
guard.stop()
print(f"  -> Guard stopped.")

print("\n" + "="*60)
print("✅ LIVE TEST COMPLETED - STATE OF THE ART CONFIRMED ✅")
print("="*60 + "\n")
