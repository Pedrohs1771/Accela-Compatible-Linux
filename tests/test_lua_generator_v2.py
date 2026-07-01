import pytest

from core.lua_script_generator import (
    LuaScriptGenerator,
    diff_and_update,
    generate_with_auto_tokens,
    merge_lua_scripts,
)


class MockSteamClient:
    def get_depot_key(self, appid, depot_id):
        if str(depot_id) == "101":
            return "auto_token_101"
        return None


def test_generate_with_auto_tokens():
    game_data = {
        "appid": "100",
        "game_name": "Test",
        "depots": {"101": {}, "102": {}},
        "tokens": {"102": "existing_token_102"}
    }
    
    client = MockSteamClient()
    script = generate_with_auto_tokens(game_data, client)
    
    assert 'addtoken(102, "existing_token_102")' in script
    assert 'addtoken(101, "auto_token_101")' in script


def test_merge_lua_scripts():
    script1 = """
addappid(100)
addappid(101, 0, "key101")
setManifestid(101, "12345678901")
addtoken(101, "token101")
"""
    script2 = """
addappid(100)
addappid(102, 0, "key102")
setManifestid(102, "12345678902")
addtoken(102, "token102")
"""

    merged = merge_lua_scripts(script1, script2)
    
    assert "addappid(100)" in merged
    assert 'addappid(101, 0, "key101")' in merged
    assert 'addappid(102, 0, "key102")' in merged
    assert 'setManifestid(101, "12345678901")' in merged
    assert 'setManifestid(102, "12345678902")' in merged
    assert 'addtoken(101, "token101")' in merged
    assert 'addtoken(102, "token102")' in merged


def test_diff_and_update():
    existing = """
addappid(100)
addappid(101)
setManifestid(101, "888888888")
addtoken(101, "my_custom_token")
"""

    new_data = {
        "appid": "100",
        "appids": ["100", "101", "102"],
        "game_name": "Test Update",
        "manifests": {
            "101": "999999999", # Should be ignored because 101 already has one in existing
            "102": "777777777"
        },
        "tokens": {
            "101": "new_token", # Should be ignored
            "102": "token102"
        }
    }

    updated = diff_and_update(existing, new_data)
    
    # 101 is kept custom
    assert 'setManifestid(101, "888888888")' in updated
    assert 'addtoken(101, "my_custom_token")' in updated
    
    # 102 is added
    assert 'addappid(102)' in updated
    assert 'setManifestid(102, "777777777")' in updated
    assert 'addtoken(102, "token102")' in updated
