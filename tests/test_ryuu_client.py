import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_download_target_does_not_duplicate_appid_directory(self):
        client = ryuu_client.RyuuClient("x" * 16)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            response = mock.Mock()
            response.iter_content.return_value = [b"zip"]
            client._get = mock.Mock(return_value=response)

            first = client.download("307110", root)
            nested = client.download("307110", root / "307110")

            expected = root / "307110" / "ryuu-307110-full.zip"
            self.assertEqual(first, expected)
            self.assertEqual(nested, expected)


if __name__ == "__main__":
    unittest.main()
