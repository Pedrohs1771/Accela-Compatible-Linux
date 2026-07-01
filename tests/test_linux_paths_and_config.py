import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest import mock


def _ensure_qsettings_stub():
    qtcore = sys.modules.get("PyQt6.QtCore")
    if qtcore is None:
        pyqt6 = sys.modules.setdefault("PyQt6", types.ModuleType("PyQt6"))
        qtcore = types.ModuleType("PyQt6.QtCore")
        sys.modules["PyQt6.QtCore"] = qtcore
        setattr(pyqt6, "QtCore", qtcore)
    if not hasattr(qtcore, "QSettings"):
        class QSettings:
            def value(self, _key, default=None, type=None):
                return default

            def setValue(self, _key, _value):
                return None

        qtcore.QSettings = QSettings


def _ensure_psutil_stub():
    if "psutil" in sys.modules:
        return
    try:
        __import__("psutil")
    except ModuleNotFoundError:
        sys.modules["psutil"] = types.ModuleType("psutil")


class LinuxSteamModeTests(unittest.TestCase):
    def test_finds_running_steam_root_outside_standard_locations(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            steam_root = Path(tmpdir) / "mnt" / "games" / "Steam"
            (steam_root / "steamapps").mkdir(parents=True)
            executable = steam_root / "ubuntu12_32" / "steam"
            executable.parent.mkdir(parents=True)
            executable.touch()

            self.assertEqual(
                linux_paths._steam_root_from_executable(executable),
                steam_root,
            )

    def test_finds_steam_root_from_compat_environment(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            steam_root = Path(tmpdir) / "external" / "Steam"
            (steam_root / "steamapps").mkdir(parents=True)

            self.assertEqual(
                linux_paths._steam_root_from_environ(
                    f"PATH=/usr/bin\nSTEAM_COMPAT_CLIENT_INSTALL_PATH={steam_root}\n"
                ),
                steam_root,
            )

    def test_process_classifier_ignores_file_managers_opening_steam_paths(self):
        from core import linux_paths

        self.assertIsNone(
            linux_paths._classify_steam_process(
                "dolphin",
                "/usr/bin/dolphin /home/user/.local/share/Steam/steamapps/common/Game",
                "",
            )
        )

    def test_process_classifier_detects_flatpak_steam_launcher(self):
        from core import linux_paths

        self.assertEqual(
            linux_paths._classify_steam_process(
                "flatpak",
                "flatpak run com.valvesoftware.Steam",
                "",
            ),
            "flatpak",
        )

    def test_process_classifier_detects_flatpak_steam_binary_path(self):
        from core import linux_paths

        self.assertEqual(
            linux_paths._classify_steam_process(
                "steam",
                "/home/arch/.var/app/com.valvesoftware.Steam/.local/share/Steam/ubuntu12_32/steam",
                "",
            ),
            "flatpak",
        )

    def test_native_root_wins_when_flatpak_is_only_installed(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            native_root = home / ".local" / "share" / "Steam" / "steamapps"
            native_root.mkdir(parents=True)

            with (
                mock.patch.object(linux_paths, "_home", return_value=home),
                mock.patch.object(linux_paths, "detect_running_steam_mode", return_value=None),
                mock.patch.object(linux_paths.shutil, "which", return_value="/usr/bin/flatpak"),
                mock.patch.object(linux_paths, "_can_run", return_value=True),
            ):
                self.assertEqual(linux_paths.detect_linux_steam_mode(), "native")

    def test_running_flatpak_overrides_native_root(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            native_root = home / ".local" / "share" / "Steam" / "steamapps"
            native_root.mkdir(parents=True)

            with (
                mock.patch.object(linux_paths, "_home", return_value=home),
                mock.patch.object(linux_paths, "detect_running_steam_mode", return_value="flatpak"),
            ):
                self.assertEqual(linux_paths.detect_linux_steam_mode(), "flatpak")

    def test_plain_native_command_does_not_use_slssteam_wrapper(self):
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            wrapper = home / ".local" / "share" / "SLSsteam" / "path" / "steam"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
            wrapper.chmod(0o755)

            with (
                mock.patch.object(linux_paths, "_home", return_value=home),
                mock.patch.object(linux_paths.shutil, "which", return_value="/usr/bin/steam"),
            ):
                self.assertEqual(
                    linux_paths.get_steam_launch_command("native"),
                    [str(wrapper)],
                )
                self.assertEqual(
                    linux_paths.get_plain_steam_launch_command("native"),
                    ["steam"],
                )

    def test_plain_flatpak_command_unsets_audit_environment(self):
        from core import linux_paths

        with mock.patch.object(linux_paths.shutil, "which", return_value="/usr/bin/flatpak"):
            command = linux_paths.get_plain_steam_launch_command("flatpak")

        self.assertIn("--unset-env=LD_AUDIT", command)
        self.assertIn("--unset-env=LD_PRELOAD", command)
        self.assertIn("--unset-env=SHARED_LIBRARY_GUARD", command)
        self.assertEqual(command[-1], linux_paths.FLATPAK_APP_ID)

    def test_snap_slssteam_is_explicitly_unsupported(self):
        from core import linux_paths

        self.assertFalse(linux_paths.is_slssteam_supported("snap"))
        with self.assertRaises(RuntimeError):
            linux_paths.get_slssteam_setup_command("snap")


class SteamPlainLaunchTests(unittest.TestCase):
    def test_plain_launch_sanitizes_inherited_audit_environment(self):
        _ensure_psutil_stub()
        from core import steam_helpers

        dirty_env = {
            "PATH": "/usr/bin",
            "LD_AUDIT": "/tmp/SLSsteam.so",
            "LD_PRELOAD": "/tmp/inject.so",
            "SHARED_LIBRARY_GUARD": "0",
        }
        with (
            mock.patch.object(steam_helpers.sys, "platform", "linux"),
            mock.patch.object(steam_helpers, "detect_linux_steam_mode", return_value="native"),
            mock.patch.object(
                steam_helpers,
                "get_plain_steam_launch_command",
                return_value=["steam"],
            ),
            mock.patch.object(steam_helpers.os, "environ", dirty_env),
            mock.patch.object(steam_helpers.subprocess, "Popen") as popen,
        ):
            self.assertEqual(steam_helpers.start_steam_plain(), "SUCCESS")

        launch_env = popen.call_args.kwargs["env"]
        self.assertEqual(launch_env["PATH"], "/usr/bin")
        self.assertNotIn("LD_AUDIT", launch_env)
        self.assertNotIn("LD_PRELOAD", launch_env)
        self.assertNotIn("SHARED_LIBRARY_GUARD", launch_env)

    def test_slssteam_launch_uses_steam_launcher_and_verifies_loaded(self):
        _ensure_psutil_stub()
        from core import steam_helpers

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            slssteam = root / "SLSsteam.so"
            library_inject = root / "library-inject.so"
            steam_launcher = root / "bin" / "steam"
            steam_launcher.parent.mkdir(parents=True)
            for path in (slssteam, library_inject):
                path.write_bytes(b"\x7fELF\x01")
                path.chmod(0o755)
            steam_launcher.write_text("#!/bin/sh\n", encoding="utf-8")
            steam_launcher.chmod(0o755)
            launched_process = mock.Mock()

            with (
                mock.patch.object(steam_helpers.sys, "platform", "linux"),
                mock.patch.object(steam_helpers, "_elf_class", return_value=32),
                mock.patch.object(steam_helpers, "_valid_ld_audit_pair", return_value=True),
                mock.patch.object(
                    steam_helpers,
                    "_slssteam_launch_command",
                    return_value=[str(steam_launcher)],
                ),
                mock.patch.object(
                    steam_helpers,
                    "_wait_for_slssteam_launch",
                    return_value="SUCCESS",
                ) as wait_for_launch,
                mock.patch.object(
                    steam_helpers.subprocess,
                    "Popen",
                    return_value=launched_process,
                ) as popen,
            ):
                result = steam_helpers.start_steam_with_slssteam(
                    str(slssteam),
                    str(library_inject),
                    launch_command=["steam"],
                    expected_class=32,
                )

            self.assertEqual(result, "SUCCESS")
            self.assertEqual(popen.call_args.args[0], [str(steam_launcher)])
            self.assertEqual(
                popen.call_args.kwargs["env"]["LD_AUDIT"],
                f"{library_inject}:{slssteam}",
            )
            wait_for_launch.assert_called_once_with(
                str(slssteam),
                str(library_inject),
                launched_process,
                timeout_seconds=15.0,
            )


class LinuxBackendLibraryTests(unittest.TestCase):
    def test_detects_library_on_another_mounted_drive(self):
        from core.platform import linux as linux_backend

        with tempfile.TemporaryDirectory() as tmpdir:
            steam_root = Path(tmpdir) / "home" / "Steam"
            external_library = Path(tmpdir) / "mnt" / "games" / "SteamLibrary"
            (steam_root / "steamapps").mkdir(parents=True)
            (external_library / "steamapps").mkdir(parents=True)
            (steam_root / "steamapps" / "libraryfolders.vdf").write_text(
                (
                    '"libraryfolders"\n{\n'
                    f'  "0" "{steam_root}"\n'
                    f'  "1" "{external_library}"\n'
                    "}\n"
                ),
                encoding="utf-8",
            )

            with (
                mock.patch.object(
                    linux_backend,
                    "list_steam_roots",
                    return_value=[steam_root],
                ),
                mock.patch.object(
                    linux_backend,
                    "get_steam_launch_command",
                    return_value=["steam"],
                ),
            ):
                install = linux_backend.LinuxBackend("native").describe_steam_install()

            self.assertEqual(install.root, str(steam_root.resolve()))
            self.assertIn(str(external_library.resolve()), install.libraries)

    def test_normalizes_common_folder_to_external_library_root(self):
        from core.platform.common import resolve_steam_library_path

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            primary = root / "home" / "Steam"
            external = root / "mnt" / "games" / "SteamLibrary"
            (primary / "steamapps" / "common").mkdir(parents=True)
            (external / "steamapps" / "common").mkdir(parents=True)

            resolved = resolve_steam_library_path(
                external / "steamapps" / "common",
                [str(primary), str(external)],
            )

            self.assertEqual(resolved, str(external.resolve()))

    def test_preserves_non_steam_destination(self):
        from core.platform.common import resolve_steam_library_path

        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "downloads"
            destination.mkdir()

            self.assertEqual(
                resolve_steam_library_path(destination, []),
                str(destination.resolve()),
            )

    def test_normalizes_game_folder_to_library_root_even_without_known_libraries(self):
        from core.platform.common import resolve_steam_library_path

        with tempfile.TemporaryDirectory() as tmpdir:
            library = Path(tmpdir) / "mnt" / "games" / "SteamLibrary"
            game_dir = library / "steamapps" / "common" / "Terraria"
            game_dir.mkdir(parents=True)

            self.assertEqual(
                resolve_steam_library_path(game_dir, []),
                str(library.resolve()),
            )


@unittest.skipUnless(sys.platform == "linux", "SLSsteam path tests are Linux-only")
class SLSsteamConfigPathTests(unittest.TestCase):
    def test_flatpak_config_path_is_returned_even_when_missing(self):
        _ensure_qsettings_stub()
        from core import linux_paths
        from utils import yaml_config_manager

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            expected = (
                home
                / ".var"
                / "app"
                / linux_paths.FLATPAK_APP_ID
                / ".config"
                / "SLSsteam"
                / "config.yaml"
            )
            with (
                mock.patch("pathlib.Path.home", return_value=home),
                mock.patch.object(linux_paths, "detect_linux_steam_mode", return_value="flatpak"),
            ):
                self.assertEqual(yaml_config_manager.get_user_config_path(), expected)
                self.assertFalse(expected.exists())

    def test_snap_config_path_is_not_native_config_path(self):
        _ensure_qsettings_stub()
        from utils import yaml_config_manager
        from core import linux_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            expected = home / "snap" / "steam" / "common" / ".config" / "SLSsteam" / "config.yaml"
            with (
                mock.patch("pathlib.Path.home", return_value=home),
                mock.patch.object(linux_paths, "detect_linux_steam_mode", return_value="snap"),
            ):
                self.assertEqual(yaml_config_manager.get_user_config_path(), expected)


class SLSsteamAppTokenTests(unittest.TestCase):
    def test_rejects_hex_depot_key_without_modifying_config(self):
        _ensure_qsettings_stub()
        from utils import yaml_config_manager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            original = "AppTokens:\n  10: 123456789\n\nFakeOffline:\n"
            config_path.write_text(original, encoding="utf-8")

            self.assertFalse(
                yaml_config_manager.add_app_token(
                    config_path,
                    "20",
                    "702e3256d70804036c3a1ea8b94603cb3cca1b14a25f6110bf4b2a42a1e241b4",
                )
            )
            self.assertEqual(config_path.read_text(encoding="utf-8"), original)

    def test_accepts_decimal_uint64_token(self):
        _ensure_qsettings_stub()
        from utils import yaml_config_manager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text("AppTokens:\n\nFakeOffline:\n", encoding="utf-8")

            with mock.patch.object(
                yaml_config_manager, "_config_management_enabled", return_value=True
            ):
                self.assertTrue(
                    yaml_config_manager.add_app_token(
                        config_path, "20", "18446744073709551615"
                    )
                )

            self.assertIn(
                "  20: 18446744073709551615",
                config_path.read_text(encoding="utf-8"),
            )

    def test_sanitizes_invalid_app_tokens_while_preserving_valid_tokens(self):
        _ensure_qsettings_stub()
        from utils import yaml_config_manager

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "AdditionalApps:",
                        "  - 238370",
                        "AppTokens:",
                        '  1017510: "DLC 1017510"',
                        "  993090: 6308073361085917231",
                        "  238370: 475965f6a77dd6b37085519e3195eab3b947b3cefa6f9ee0172ad9cec0042db1",
                        "  204360: 14285758721387452983",
                        "",
                        "FakeOffline:",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            with mock.patch.object(
                yaml_config_manager, "_config_management_enabled", return_value=True
            ):
                self.assertTrue(
                    yaml_config_manager.fix_slssteam_config_indentation(config_path)
                )

            content = config_path.read_text(encoding="utf-8")
            self.assertIn("  993090: 6308073361085917231", content)
            self.assertIn("  204360: 14285758721387452983", content)
            self.assertNotIn("DLC 1017510", content)
            self.assertNotIn("475965f6a77dd6b", content)


class RyuuPostDownloadTests(unittest.TestCase):
    def test_task_manager_never_auto_offers_ryuu_after_download(self):
        task_manager_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "LumaTools"
            / "squashfs-root"
            / "bin"
            / "src"
            / "managers"
            / "task_manager.py"
        )
        source = task_manager_path.read_text(encoding="utf-8")
        finalize_body = source.split("# --- FINISH ---", 1)[0].rsplit(
            "def _finalize_job_logic", 1
        )[-1]

        self.assertNotIn("_start_ryuu_check_step()", finalize_body)


if __name__ == "__main__":
    unittest.main()
