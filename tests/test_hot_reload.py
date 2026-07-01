import os
import time
from unittest import mock

import pytest

from core.hot_reload import HotReloadWatcher


@pytest.fixture
def hot_reload(tmp_path):
    pipe_path = tmp_path / "SLSsteam.API"
    watcher = HotReloadWatcher(check_interval=0.01, api_pipe_path=str(pipe_path))
    yield watcher
    watcher.stop()


def test_watcher_detects_new_file(hot_reload, tmp_path):
    watch_dir = tmp_path / "scripts"
    watch_dir.mkdir()
    hot_reload.add_watch_dir(str(watch_dir), {".lua"})
    
    # Cria o arquivo novo
    new_script = watch_dir / "test.lua"
    new_script.write_text("print('hello')")
    
    with mock.patch.object(hot_reload, "_handle_modification") as mock_handle:
        with mock.patch("core.hot_reload.get_user_config_path", return_value=tmp_path / "config.yaml"):
            hot_reload._check_files()
            
            # O arquivo foi verificado
            assert str(new_script) in hot_reload.file_mtimes
            mock_handle.assert_called_with(str(new_script), False)


def test_watcher_detects_modification(hot_reload, tmp_path):
    watch_dir = tmp_path / "scripts"
    watch_dir.mkdir()
    hot_reload.add_watch_dir(str(watch_dir), {".lua"})
    
    script = watch_dir / "test.lua"
    script.write_text("print('old')")
    
    # Simula check inicial
    with mock.patch("core.hot_reload.get_user_config_path", return_value=tmp_path / "config.yaml"):
        hot_reload._check_files()
        
    assert str(script) in hot_reload.file_mtimes
    
    # Modifica o arquivo
    time.sleep(0.02) # Espera um pouco pra garantir mtime diferente se possível, mas vamos forçar
    script.write_text("print('new')")
    os.utime(str(script), (time.time() + 10, time.time() + 10))
    
    with mock.patch.object(hot_reload, "_handle_modification") as mock_handle:
        with mock.patch("core.hot_reload.get_user_config_path", return_value=tmp_path / "config.yaml"):
            hot_reload._check_files()
            mock_handle.assert_called_with(str(script), False)


def test_handle_modification_config(hot_reload, tmp_path):
    pipe_path = tmp_path / "SLSsteam.API"
    pipe_path.touch()
    
    config_path = tmp_path / "config.yaml"
    
    callback_called = False
    def on_config(path):
        nonlocal callback_called
        callback_called = True
        
    hot_reload.on_config_changed = on_config
    
    hot_reload._handle_modification(str(config_path), is_config=True)
    
    assert callback_called
    assert pipe_path.read_text() == "reload\n"


@mock.patch("subprocess.Popen")
def test_handle_modification_acf(mock_popen, hot_reload, tmp_path):
    acf_path = tmp_path / "appmanifest_1234.acf"
    
    callback_called = False
    def on_acf(path):
        nonlocal callback_called
        callback_called = True
        
    hot_reload.on_acf_changed = on_acf
    
    hot_reload._handle_modification(str(acf_path), is_config=False)
    
    assert callback_called
    mock_popen.assert_called_once_with(
        ["steam", "steam://nav/library/properties/1234"],
        stdout=mock.ANY,
        stderr=mock.ANY
    )
