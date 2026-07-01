import os
import threading
import time
from unittest import mock

import pytest

from core.anticheat_guard import AntiCheatGuard


@pytest.fixture
def mock_proc_fs(tmp_path):
    """Mocks a /proc filesystem structure."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    return proc_dir


@pytest.fixture
def anticheat_guard(tmp_path):
    # Usa tmp_path para o pipe falso
    pipe_path = tmp_path / "SLSsteam.API"
    guard = AntiCheatGuard(check_interval=0.01, api_pipe_path=str(pipe_path))
    yield guard
    guard.stop()


def create_mock_process(proc_dir, pid, cmdline):
    pid_dir = proc_dir / str(pid)
    pid_dir.mkdir()
    cmd_path = pid_dir / "cmdline"
    # Null byte separated arguments
    cmd_bytes = b"\x00".join([arg.encode('utf-8') for arg in cmdline])
    cmd_path.write_bytes(cmd_bytes)


def test_guard_detects_anticheat(anticheat_guard, mock_proc_fs):
    # Setup mock /proc and config
    create_mock_process(mock_proc_fs, 1234, ["/usr/bin/bash", "-c", "echo hello"])
    create_mock_process(mock_proc_fs, 5678, ["C:\\Games\\EAC\\EasyAntiCheat_Setup.exe"])
    
    with mock.patch("core.anticheat_guard.os.listdir", return_value=[str(p.name) for p in mock_proc_fs.iterdir()]), \
         mock.patch("core.anticheat_guard.os.path.isfile", return_value=True), \
         mock.patch("builtins.open", mock.mock_open(read_data=b"C:\\Games\\EAC\\EasyAntiCheat_Setup.exe\x00")):
        
        # Mock actual open call specifically for the cmdline to return eac
        def mock_open_impl(path, *args, **kwargs):
            if "5678" in str(path):
                return mock.mock_open(read_data=b"C:\\Games\\EAC\\EasyAntiCheat_Setup.exe\x00")()
            return mock.mock_open(read_data=b"/usr/bin/bash\x00-c\x00echo hello\x00")()
            
        with mock.patch("builtins.open", side_effect=mock_open_impl):
            with mock.patch.object(anticheat_guard, "_apply_protection") as mock_apply:
                anticheat_guard._check_processes()
                
                assert anticheat_guard.ac_active is True
                assert "easyanticheat" in anticheat_guard.active_ac_names
                mock_apply.assert_called_once()


def test_guard_restores_state(anticheat_guard, mock_proc_fs):
    # Começa com AC ativo
    anticheat_guard.ac_active = True
    anticheat_guard.active_ac_names = {"easyanticheat"}
    
    # Simula que /proc está vazio (AC fechou)
    with mock.patch("core.anticheat_guard.os.listdir", return_value=[]):
        with mock.patch.object(anticheat_guard, "_restore_protection") as mock_restore:
            anticheat_guard._check_processes()
            
            assert anticheat_guard.ac_active is False
            assert len(anticheat_guard.active_ac_names) == 0
            mock_restore.assert_called_once()


def test_apply_protection_writes_to_pipe(anticheat_guard, tmp_path):
    # Cria o pipe (arquivo normal para o teste)
    pipe_path = tmp_path / "SLSsteam.API"
    pipe_path.touch()
    
    with mock.patch("core.anticheat_guard.get_user_config_path") as mock_get_config:
        mock_config = tmp_path / "config.yaml"
        mock_config.write_text("SafeMode: no\n")
        mock_get_config.return_value = mock_config
        
        anticheat_guard._apply_protection()
        
        # Verifica se escreveu no pipe
        assert pipe_path.read_text() == "safemode:1\n"
        # Verifica se modificou config
        assert "SafeMode: yes" in mock_config.read_text()
        assert anticheat_guard._original_safe_mode is False


def test_restore_protection(anticheat_guard, tmp_path):
    pipe_path = tmp_path / "SLSsteam.API"
    pipe_path.touch()
    
    anticheat_guard._original_safe_mode = False
    
    with mock.patch("core.anticheat_guard.get_user_config_path") as mock_get_config:
        mock_config = tmp_path / "config.yaml"
        mock_config.write_text("SafeMode: yes\n")
        mock_get_config.return_value = mock_config
        
        anticheat_guard._restore_protection()
        
        assert pipe_path.read_text() == "safemode:0\n"
        assert "SafeMode: no" in mock_config.read_text()
