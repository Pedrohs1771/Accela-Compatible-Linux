import os
from pathlib import Path
from unittest import mock

import pytest

from core.health_monitor import HealthMonitor


@pytest.fixture
def monitor(tmp_path):
    steam_root = tmp_path / "steam"
    steam_root.mkdir()
    slssteam_so = tmp_path / "SLSsteam.so"
    slssteam_so.touch()
    
    return HealthMonitor(str(steam_root), str(slssteam_so))


def test_check_slssteam_health(monitor, tmp_path):
    # Success
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "ELF 32-bit"
        with mock.patch("core.health_monitor.get_user_config_path", return_value=tmp_path / "config.yaml"):
            (tmp_path / "config.yaml").touch()
            monitor.check_slssteam_health()
            assert monitor.report["status"] == "ok"
            
    # Error: Not 32-bit
    with mock.patch("subprocess.run") as mock_run:
        mock_run.return_value.stdout = "ELF 64-bit"
        with mock.patch("core.health_monitor.get_user_config_path", return_value=tmp_path / "config.yaml"):
            monitor.check_slssteam_health()
            assert monitor.report["status"] == "error"
            assert "64-bit" in monitor.report["issues"][0]["message"]


def test_check_lua_script_validity(monitor, tmp_path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    
    valid = plugins / "valid.lua"
    valid.write_text("addappid(123)")
    
    invalid = plugins / "invalid.lua"
    invalid.write_text("print('hello')")
    
    monitor.check_lua_script_validity(str(plugins))
    
    assert monitor.report["status"] == "warning"
    assert "invalid.lua" in monitor.report["issues"][0]["message"]


def test_check_online_fix_integrity(monitor, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    (game_dir / "LUMA_ONLINE_FIX_INFO.txt").touch()
    
    # Error: Missing DLLs
    monitor.check_online_fix_integrity(str(game_dir))
    assert monitor.report["status"] == "error"
    assert "OnlineFix DLLs missing" in monitor.report["issues"][0]["message"]
    
    # Success: DLL present
    monitor.report["status"] = "ok"
    monitor.report["issues"].clear()
    (game_dir / "OnlineFix64.dll").touch()
    monitor.check_online_fix_integrity(str(game_dir))
    assert monitor.report["status"] == "ok"


def test_auto_repair(monitor, tmp_path):
    monitor._add_issue("warning", "Appmanifest for AppID 123 is inconsistent or missing.", "Manifests")
    
    with mock.patch("utils.steam_manifest.repair_installed_app_state", return_value=True):
        monitor.auto_repair(["123"])
        
        assert len(monitor.report["repairs"]) == 1
        assert "Repaired manifest for AppID 123" in monitor.report["repairs"][0]["message"]


def test_generate_diagnostic_report(monitor):
    monitor._add_issue("error", "Test error", "Test")
    monitor._add_repair("Test repair", "Test")
    
    report = monitor.generate_diagnostic_report()
    
    assert report["status"] == "error"
    assert len(report["issues"]) == 1
    assert len(report["repairs"]) == 1
    
    # Internal state reset
    assert monitor.report["status"] == "ok"
    assert len(monitor.report["issues"]) == 0
