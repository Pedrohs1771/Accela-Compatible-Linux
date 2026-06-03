import os
import tempfile
import unittest
from pathlib import Path

from core import ryuu_client


class RyuuClientLocalSecretsTests(unittest.TestCase):
    def test_save_load_and_mask_key_without_repo_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            old_config = os.environ.get("XDG_CONFIG_HOME")
            os.environ["XDG_CONFIG_HOME"] = tmp
            try:
                ryuu_client.save_ryuu_auth_key("abcd12345678wxyz")
                path = ryuu_client.secrets_path()

                self.assertEqual(path, Path(tmp) / "LumaTools" / "secrets.json")
                self.assertEqual(ryuu_client.load_ryuu_auth_key(), "abcd12345678wxyz")
                self.assertEqual(ryuu_client.mask_key("abcd12345678wxyz"), "abcd********wxyz")
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            finally:
                if old_config is None:
                    os.environ.pop("XDG_CONFIG_HOME", None)
                else:
                    os.environ["XDG_CONFIG_HOME"] = old_config


if __name__ == "__main__":
    unittest.main()
