from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from core.dlc_discovery import DlcCandidate, discover_dlc_package
from core.dlc_cache import DlcCache
from core.dlc_manifest_installer import DlcInstallError, DlcManifestInstaller
from core.dlc_registry import DlcRegistry
from core.dlc_verifier import diagnose_dlc_content, verify_dlc_install


BASE_APPID = "100"
DLC_APPID = "200"
DEPOT_ID = "300"
MANIFEST_ID = "400"


def _acf_text() -> str:
    return (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{BASE_APPID}"\n'
        '\t"StateFlags"\t\t"4"\n'
        '\t"installdir"\t\t"Test Game"\n'
        '\t"SizeOnDisk"\t\t"0"\n'
        '\t"BytesToDownload"\t\t"0"\n'
        '\t"TargetBuildID"\t\t"0"\n'
        '\t"InstalledDepots"\n'
        "\t{\n"
        "\t}\n"
        "}\n"
    )


class DlcContentBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.steam = self.root / "SteamLibrary"
        self.game = self.steam / "steamapps" / "common" / "Test Game"
        self.game.mkdir(parents=True)
        (self.steam / "depotcache").mkdir(parents=True)
        self.acf = self.steam / "steamapps" / f"appmanifest_{BASE_APPID}.acf"
        self.acf.write_text(_acf_text(), encoding="utf-8")
        self.registry = DlcRegistry(self.root / "dlc_registry.json")
        self.installer = DlcManifestInstaller(self.registry)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _package(
        self,
        *,
        local_authorized: bool = True,
        encrypted: bool = False,
        include_payload: bool = True,
        include_manifest: bool = True,
    ) -> Path:
        package = self.root / "content.zip"
        spec = {
            "schema": "lumatools.dlc.v1",
            "base_appid": BASE_APPID,
            "dlcs": [
                {
                    "appid": DLC_APPID,
                    "name": "Test DLC",
                    "depots": [DEPOT_ID],
                    "manifests": {DEPOT_ID: MANIFEST_ID},
                    "content_roots": ["payload/dlc"],
                    "local_package_authorized": local_authorized,
                    "encrypted": encrypted,
                }
            ],
        }
        lua = (
            f'addappid({BASE_APPID})\n'
            f'addappid({DLC_APPID})\n'
            f'addappid({DEPOT_ID}, 1, "test-key")\n'
            f'setManifestid({DEPOT_ID}, "{MANIFEST_ID}")\n'
        )
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("lumatools_dlc.json", json.dumps(spec))
            archive.writestr("package.lua", lua)
            if include_payload:
                archive.writestr("payload/dlc/content.bin", b"real-dlc-content")
            if include_manifest:
                archive.writestr(
                    f"{DEPOT_ID}_{MANIFEST_ID}.manifest",
                    b"manifest-content",
                )
        return package

    def test_metadata_only_never_becomes_installed(self) -> None:
        package = self._package(local_authorized=False)
        _, candidates = discover_dlc_package(package)
        candidate = candidates[0]
        self.assertEqual(candidate.status, "metadata_only")
        self.assertFalse(candidate.installable)

        before = self.acf.read_bytes()
        with self.assertRaises(DlcInstallError):
            self.installer.install(
                candidate,
                package_path=package,
                game_dir=self.game,
                steam_root=self.steam,
                slssteam_enabled=False,
            )
        self.assertEqual(self.acf.read_bytes(), before)
        self.assertFalse((self.game / "content.bin").exists())

        record = candidate.to_dict()
        self.registry.update(BASE_APPID, record)
        self.installer.write_game_info(self.game, BASE_APPID)
        diagnosis = diagnose_dlc_content(
            base_appid=BASE_APPID,
            game_dir=self.game,
            steam_root=self.steam,
        )
        self.assertFalse(diagnosis["ok"])
        self.assertIn(
            f"{DLC_APPID}:metadata_only_no_files",
            diagnosis["issues"],
        )

    def test_local_authorized_package_without_files_reports_exact_reason(self) -> None:
        package = self._package(local_authorized=True, include_payload=False)
        _, candidates = discover_dlc_package(package)
        candidate = candidates[0]
        self.assertEqual(candidate.status, "metadata_only")
        self.assertEqual(candidate.failed_reason, "local_files_not_found")
        self.assertIn("local_content", candidate.missing_fields)

    def test_real_payload_and_manifest_become_installed(self) -> None:
        package = self._package()
        _, candidates = discover_dlc_package(package)
        candidate = candidates[0]
        self.assertTrue(candidate.installable)

        record = self.installer.install(
            candidate,
            package_path=package,
            game_dir=self.game,
            steam_root=self.steam,
            slssteam_enabled=False,
        )
        self.assertEqual(record["status"], "installed")
        self.assertTrue((self.game / "content.bin").is_file())
        self.assertTrue(
            (self.steam / "depotcache" / f"{DEPOT_ID}_{MANIFEST_ID}.manifest").is_file()
        )
        self.assertIn(f'"{DEPOT_ID}"', self.acf.read_text(encoding="utf-8"))
        self.assertTrue((self.game / "LUMA_DLC_CONTENT_INFO.json").is_file())
        self.assertTrue(
            verify_dlc_install(
                base_appid=BASE_APPID,
                candidate=record,
                game_dir=self.game,
                steam_root=self.steam,
            )["ok"]
        )

    def test_failed_download_is_failed_and_does_not_change_acf(self) -> None:
        package = self._package(include_payload=False, include_manifest=False)
        candidate = DlcCandidate(
            appid=DLC_APPID,
            name="Free DLC",
            base_appid=BASE_APPID,
            depot_ids=[DEPOT_ID],
            manifests={DEPOT_ID: MANIFEST_ID},
            entitlement="free_dlc",
            status="installable",
            manifest_found=True,
        )
        before = self.acf.read_bytes()
        with self.assertRaises(DlcInstallError):
            self.installer.install(
                candidate,
                package_path=package,
                game_dir=self.game,
                steam_root=self.steam,
                downloader=lambda _candidate, _stage: {
                    "ok": False,
                    "failed_reason": "failed_download",
                },
                slssteam_enabled=False,
            )
        self.assertEqual(self.acf.read_bytes(), before)
        self.assertEqual(
            self.registry.get(BASE_APPID, DLC_APPID)["status"],
            "failed",
        )

    def test_locked_dlc_does_not_change_acf(self) -> None:
        package = self._package(encrypted=True)
        _, candidates = discover_dlc_package(package)
        candidate = candidates[0]
        self.assertEqual(candidate.status, "locked")
        before = self.acf.read_bytes()
        with self.assertRaises(DlcInstallError):
            self.installer.install(
                candidate,
                package_path=package,
                game_dir=self.game,
                steam_root=self.steam,
                slssteam_enabled=False,
            )
        self.assertEqual(self.acf.read_bytes(), before)

    def test_repair_restores_manifest_and_acf_but_not_missing_files(self) -> None:
        package = self._package()
        _, candidates = discover_dlc_package(package)
        record = self.installer.install(
            candidates[0],
            package_path=package,
            game_dir=self.game,
            steam_root=self.steam,
            slssteam_enabled=False,
        )
        manifest = self.steam / "depotcache" / f"{DEPOT_ID}_{MANIFEST_ID}.manifest"
        manifest.unlink()
        self.acf.write_text(_acf_text(), encoding="utf-8")

        repaired = self.installer.repair(
            base_appid=BASE_APPID,
            dlc_appid=DLC_APPID,
            game_dir=self.game,
            steam_root=self.steam,
        )
        self.assertEqual(repaired["status"], "installed")
        self.assertTrue(manifest.is_file())

        (self.game / "content.bin").unlink()
        with self.assertRaisesRegex(DlcInstallError, "registered_files_missing"):
            self.installer.repair(
                base_appid=BASE_APPID,
                dlc_appid=DLC_APPID,
                game_dir=self.game,
                steam_root=self.steam,
            )

    def test_uninstall_removes_only_registered_files(self) -> None:
        package = self._package()
        _, candidates = discover_dlc_package(package)
        self.installer.install(
            candidates[0],
            package_path=package,
            game_dir=self.game,
            steam_root=self.steam,
            slssteam_enabled=False,
        )
        unrelated = self.game / "keep-me.txt"
        unrelated.write_text("base game", encoding="utf-8")

        record = self.installer.uninstall(
            base_appid=BASE_APPID,
            dlc_appid=DLC_APPID,
            game_dir=self.game,
            steam_root=self.steam,
        )
        self.assertEqual(record["status"], "detected")
        self.assertFalse((self.game / "content.bin").exists())
        self.assertTrue(unrelated.exists())
        self.assertNotIn(f'"{DEPOT_ID}"', self.acf.read_text(encoding="utf-8"))

    def test_uninstall_restores_replaced_base_files(self) -> None:
        base_file = self.game / "content.bin"
        base_file.write_bytes(b"base-content")
        package = self._package()
        _, candidates = discover_dlc_package(package)
        self.installer.install(
            candidates[0],
            package_path=package,
            game_dir=self.game,
            steam_root=self.steam,
            slssteam_enabled=False,
        )
        self.assertEqual(base_file.read_bytes(), b"real-dlc-content")

        record = self.installer.uninstall(
            base_appid=BASE_APPID,
            dlc_appid=DLC_APPID,
            game_dir=self.game,
            steam_root=self.steam,
        )
        self.assertEqual(base_file.read_bytes(), b"base-content")
        self.assertIn("content.bin", record["restored_files"])

    def test_parser_detects_dlc_with_self_depot_and_ignores_comments(self) -> None:
        package = self.root / "self-depot.zip"
        lua = (
            f"addappid({BASE_APPID}) -- Base\n"
            "-- DLCS WITH DEDICATED DEPOTS\n"
            f"addappid({DLC_APPID}) -- Dedicated DLC\n"
            f'addappid({DLC_APPID}, 1, "key") -- Dedicated DLC depot\n'
            f'setManifestid({DLC_APPID}, "{MANIFEST_ID}")\n'
            "-- addappid(999999) -- Empty/commented depot\n"
        )
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("package.lua", lua)
            archive.writestr(
                f"{DLC_APPID}_{MANIFEST_ID}.manifest",
                b"manifest",
            )
        base_appid, candidates = discover_dlc_package(package)
        self.assertEqual(base_appid, BASE_APPID)
        self.assertEqual([item.appid for item in candidates], [DLC_APPID])
        self.assertEqual(candidates[0].depot_ids, [DLC_APPID])
        self.assertTrue(candidates[0].manifest_found)
        self.assertEqual(candidates[0].status, "metadata_only")
        self.assertIn(
            "entitlement_or_local_content",
            candidates[0].missing_fields,
        )

    def test_parser_groups_following_dedicated_depots_with_dlc_appid(self) -> None:
        package = self.root / "grouped-depots.zip"
        lua = (
            f"addappid({BASE_APPID}) -- Base\n"
            f"addappid({DLC_APPID}) -- First DLC\n"
            'addappid(301, 1, "win-key") -- First DLC Win32\n'
            'setManifestid(301, "401")\n'
            'addappid(302, 1, "linux-key") -- First DLC Linux\n'
            'setManifestid(302, "402")\n'
            "addappid(201) -- Second DLC\n"
            'addappid(303, 1, "other-key") -- Second DLC Win32\n'
            'setManifestid(303, "403")\n'
        )
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("package.lua", lua)
            archive.writestr("301_401.manifest", b"manifest")
            archive.writestr("302_402.manifest", b"manifest")
            archive.writestr("303_403.manifest", b"manifest")

        _, candidates = discover_dlc_package(package)
        first = next(item for item in candidates if item.appid == DLC_APPID)
        second = next(item for item in candidates if item.appid == "201")
        self.assertEqual(first.depot_ids, ["301", "302"])
        self.assertEqual(first.manifests, {"301": "401", "302": "402"})
        self.assertEqual(second.depot_ids, ["303"])

    def test_cache_records_diagnostic_without_fake_installable(self) -> None:
        package = self.root / "manifest-only.zip"
        lua = (
            f"addappid({BASE_APPID}) -- Base\n"
            f"addappid({DLC_APPID}) -- DLC\n"
            f'addappid({DLC_APPID}, 1, "key") -- DLC depot\n'
            f'setManifestid({DLC_APPID}, "{MANIFEST_ID}")\n'
        )
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("package.lua", lua)
            archive.writestr(
                f"{DLC_APPID}_{MANIFEST_ID}.manifest",
                b"manifest",
            )
        cache = DlcCache(self.root / "cache")
        report = cache.cache_package(package, source="test")
        record = report["dlcs"][0]
        self.assertEqual(record["status"], "metadata_only")
        self.assertFalse(record["installable"])
        self.assertTrue(record["manifest_file_found"])
        self.assertTrue(record["depot_id_found"])
        self.assertFalse(record["local_content_found"])
        self.assertIn("entitlement_or_local_content", record["missing_fields"])
        self.assertTrue(
            (self.root / "cache" / BASE_APPID / DLC_APPID / "status.json").is_file()
        )

    def test_cached_real_content_can_be_installed_and_verified(self) -> None:
        package = self._package()
        cache = DlcCache(self.root / "cache")
        report = cache.cache_package(package, source="test")
        cached = report["dlcs"][0]
        self.assertEqual(cached["status"], "cached_installable")

        candidate = DlcCandidate(
            **{
                key: value
                for key, value in cached.items()
                if key in DlcCandidate.__dataclass_fields__
            }
        )
        record = self.installer.install_cached(
            candidate,
            cache_path=cached["cache_path"],
            game_dir=self.game,
            steam_root=self.steam,
            slssteam_enabled=False,
        )
        self.assertEqual(record["status"], "installed")
        self.assertTrue((self.game / "content.bin").is_file())
        self.assertTrue(
            (self.steam / "depotcache" / f"{DEPOT_ID}_{MANIFEST_ID}.manifest").is_file()
        )
        self.assertIn(f'"{DEPOT_ID}"', self.acf.read_text(encoding="utf-8"))

    def test_registry_sync_removes_stale_metadata_but_preserves_installed(self) -> None:
        self.registry.update(
            BASE_APPID,
            {
                "appid": "201",
                "status": "metadata_only",
                "provenance": {"archive": "/tmp/source.zip"},
            },
        )
        self.registry.update(
            BASE_APPID,
            {"appid": "202", "status": "installed"},
        )
        self.registry.sync_discovery(
            BASE_APPID,
            [{"appid": "203", "status": "metadata_only"}],
            package_path="/tmp/source.zip",
        )
        records = (
            self.registry.load()["games"][BASE_APPID]["dlcs"]
        )
        self.assertNotIn("201", records)
        self.assertIn("202", records)
        self.assertIn("203", records)


if __name__ == "__main__":
    unittest.main()
