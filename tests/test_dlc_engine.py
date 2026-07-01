import os
from pathlib import Path
from unittest import mock

import pytest

from core.content_manager import ContentManager


@pytest.fixture
def manager(tmp_path):
    return ContentManager(base_path=tmp_path)


def test_auto_detect_dlc_method(manager, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    # 1. Default -> slssteam
    assert manager.auto_detect_dlc_method(str(game_dir)) == "slssteam"
    
    # 2. Goldberg
    (game_dir / "steam_settings").mkdir()
    assert manager.auto_detect_dlc_method(str(game_dir)) == "goldberg"
    
    # 3. CreamAPI (Linux + steam_api.dll)
    # Remove goldberg
    (game_dir / "steam_settings").rmdir()
    
    (game_dir / "steam_api.dll").touch()
    with mock.patch("sys.platform", "linux"):
        assert manager.auto_detect_dlc_method(str(game_dir)) == "creamapi"


def test_generate_cream_api_config(manager, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    dlc_dict = {"100": "DLC 1", "200": "DLC 2"}
    ini_path = manager.generate_cream_api_config(str(game_dir), "999", dlc_dict)
    
    assert os.path.exists(ini_path)
    content = Path(ini_path).read_text(encoding="utf-8")
    assert "appid = 999" in content
    assert "100 = DLC 1" in content
    assert "200 = DLC 2" in content
    assert "orgapi = steam_api_o.dll" in content


def test_generate_goldberg_dlc_txt(manager, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    dlc_dict = {"100": "DLC 1", "200": "DLC 2"}
    txt_path = manager.generate_goldberg_dlc_txt(str(game_dir), dlc_dict)
    
    assert os.path.exists(txt_path)
    assert "steam_settings" in txt_path
    content = Path(txt_path).read_text(encoding="utf-8")
    assert "100=DLC 1" in content
    assert "200=DLC 2" in content


@mock.patch.object(ContentManager, "deep_scan_dlcs")
@mock.patch.object(ContentManager, "auto_detect_dlc_method")
def test_batch_activate_all_dlcs_creamapi(mock_detect, mock_scan, manager, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    mock_scan.return_value = {"100": "DLC 1"}
    mock_detect.return_value = "creamapi"
    
    result = manager.batch_activate_all_dlcs("999", str(game_dir))
    
    assert result["success"] is True
    assert result["method"] == "creamapi"
    assert len(result["paths"]) == 1
    assert "cream_api.ini" in result["paths"][0]


def test_verify_dlc_files_exist(manager, tmp_path):
    game_dir = tmp_path / "game"
    game_dir.mkdir()
    
    # Sem nada
    assert manager.verify_dlc_files_exist(str(game_dir)) is False
    
    # Com pasta dlc
    (game_dir / "dlc").mkdir()
    assert manager.verify_dlc_files_exist(str(game_dir)) is True
    
    # Com arquivo dlc
    (game_dir / "dlc").rmdir()
    (game_dir / "my_super_dlc_pack.pak").touch()
    assert manager.verify_dlc_files_exist(str(game_dir)) is True
