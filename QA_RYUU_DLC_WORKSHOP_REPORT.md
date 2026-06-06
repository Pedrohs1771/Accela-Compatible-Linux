# QA Ryuu, DLC and Workshop Report

Date: 2026-06-06

## Result

Recommendation: **approved as RC/beta internal for DLC/Workshop backend**.

The Workshop flow, DLC safety/cache backend and one physical free DLC install
test passed. Final public release still needs normal packaging/update regression
before publishing, but the previous blocking DLC gate now has `PASS_REAL_DLC`.

This report records the Linux backend state before the Windows RC port.

## Automated Tests

- 30 tests passed.
- Python compilation passed for all changed modules.
- Qt/runtime import smoke test passed.
- Metadata-only DLC never became installed.
- Locked and failed DLC did not modify ACF.
- Cached local authorized content installed and passed verifier.
- Repair restored manifest/ACF only when registered files existed.
- Uninstall removed only registered files.
- Uninstall restored base files when a DLC depot overwrote existing files.
- Workshop rollback, physical enable/disable, repair and selective uninstall
  passed.

## Real DLC and Ryuu QA

### We Need To Go Deeper

- Base AppID: `307110`
- Hubcap package:
  `~/.local/share/LumaTools/hubcap_manifests/lumatools_fetch_307110.zip`
- Ryuu package downloaded during QA:
  `~/.local/share/LumaTools/qa/ryuu-real/307110/ryuu-307110-full.zip`
- Ryuu download size: `741827` bytes
- Ryuu SHA256:
  `85cce5a87523adb8e8cb5aa43a9d594023eb20485f75fb21f06f309e59d52862`

DLC results:

| DLC AppID | Detection | Result | Reason |
| --- | --- | --- | --- |
| `1128020` | Depot and manifest found | `metadata_only` | Manifest exists, but no local payload or confirmed entitlement |
| `2241680` | Depot and manifest found | `metadata_only` | Manifest exists, but no local payload or confirmed entitlement |
| `1534780` | Metadata found | `metadata_only` | No DLC depot mapping, manifest or local files |

The Ryuu package itself exposed only `1534780` as DLC metadata. It did not
contain a dedicated DLC depot or physical payload for that DLC.

### Among Us

- Base AppID: `945360`
- Package:
  `~/.local/share/LumaTools/hubcap_manifests/lumatools_fetch_945360.zip`
- Eight DLC entries were detected.
- All eight remained `metadata_only`.
- The previously false commented entry `945362` is no longer detected.
- Each DLC reports missing depot, manifest and local content.

### ACF Safety

The SHA256 values for these files were identical before and after prefetch:

- `appmanifest_307110.acf`
- `appmanifest_945360.acf`

Prefetch did not register metadata-only DLCs in `InstalledDepots`.

### Dedicated DLC Entitlement Scan

Six dedicated DLC depots were found among locally installed games and checked
against the official Steam Store API:

- `1128020` - We Need To Go Deeper: Buried Treasure DLC
- `2241680` - We Need To Go Deeper: Supporter Pack
- `2152440` - Dome Keeper: Engineer Gear Pack
- `2380060` - Dome Keeper: Assessor Gear Pack
- `4331610` - Dome Keeper: The Lost Keepers
- `273300` - Outlast: Whistleblower DLC

None were reported as free. No physical download was attempted without a
confirmed owned/free entitlement.

## DLC_PHYSICAL_INSTALL_TEST

Status: **PASS_REAL_DLC**

Game: The Binding of Isaac: Rebirth (`250900`)

DLC tested: The Binding of Isaac: Repentance+ (`3353470`)

Public metadata:

- SteamDB reports `3353470` as DLC for `250900`.
- SteamDB reports `3353470` as free on the store / free on demand.
- Package source:
  `~/.local/share/LumaTools/hubcap_manifests/lumatools_fetch_250900.zip`
- Package SHA256:
  `d5e38d4175e17542d1c6609c3b97200fde560c8e59f667ccc6e099fd74e88ea8`

Parser results:

- Base Windows depot: `250902`
- Base manifest: `4994611894646808503`
- DLC depot: `3353471`
- DLC manifest: `229910742625134068`
- DLC status before download: `installable`
- Entitlement class used: `free_dlc`

Physical install results:

- Base depot `250902` downloaded/validated with return code `0`.
- DLC depot `3353471` downloaded with return code `0`.
- DLC downloaded bytes: `694913520`.
- DLC uncompressed bytes: `763003388`.
- DLC files installed: `1179`.
- Files overwritten from the base game: `4`.
- DLC manifest copied to `steamapps/depotcache`.
- ACF `InstalledDepots` received depot `3353471`.
- `LUMA_DLC_CONTENT_INFO.json` was written.
- Content Doctor after install: `ok: true`.
- Repair result: `installed`.
- Repair verification: `ok: true`.
- Uninstall result: `detected`.
- Uninstall removed DLC-only files: `1175`.
- Uninstall restored overwritten base files: `4`.
- Content Doctor after uninstall: `ok: true`.

Final safety state after uninstall:

- DLC depot manifest `3353471_229910742625134068.manifest` removed from
  `depotcache`.
- ACF no longer contains `3353471`.
- Base executable `isaac-ng.exe` remains present.
- Final game directory size after uninstall: `312M`.

Artifact:

- `isaac-physical-dlc/result.json`

## Real Workshop QA

Game: Project Zomboid (`108600`)

Public item tested:

- Workshop ID: `3072719389`
- Anonymous SteamCMD download: passed
- Downloaded files: 5
- Staging install: passed
- `install_manifest.json`: created
- Physical disable: passed
- Physical enable: passed
- Repair while disabled and enabled: passed
- Selective uninstall: passed
- Unregistered QA file survived uninstall
- Final reinstall and repair: passed

Existing item migrated:

- Workshop ID: `3736001855`
- `install_manifest.json`: created
- Repair: passed

Final Content Doctor result for Project Zomboid:

- `ok: true`
- no Workshop issues

## Bugs Fixed

- DLC declarations with a dedicated self-depot were previously hidden.
- DLC declarations followed by separate platform depots were previously not
  associated with the DLC AppID. The Isaac package exposed this bug.
- Commented `addappid` lines were incorrectly parsed as DLCs.
- Ryuu output path duplicated the AppID directory.
- Package scanning did not recurse through nested Ryuu directories.
- Metadata-only status lacked per-field diagnostics.
- DLC cache did not exist.
- Post-install flow prompted to apply Ryuu instead of only prefetching DLC data.
- Workshop enable/disable only changed JSON.
- Workshop installs lacked staging, rollback and install manifests.
- Old Workshop entries lacked repairable manifests.
- DLC uninstall could remove overwritten base files instead of restoring them.
  The installer now stores persistent replacement backups and restores them on
  uninstall.

## Remaining Work

- Add an authenticated Steam entitlement provider that confirms account-owned
  DLC without storing passwords.
- Wire the physical free/owned DLC downloader into the normal cube action, so
  UI activation uses the same verified provider exercised by the Isaac QA
  script.
- Extend `cached_installable` for downloaded free/owned DLC payloads, not only
  local ZIP payloads.
- Add UI actions for DLC repair/uninstall and Workshop repair/uninstall without
  changing the existing visual design.

## QA Artifacts

Artifacts are stored under:

`~/.local/share/LumaTools/qa/`

Important files:

- `ryuu-real/result.json`
- `dlc-prefetch-results.json`
- `content-doctor-307110.json`
- `content-doctor-945360.json`
- `content-doctor-108600-final.json`
- `isaac-physical-dlc/result.json`
- `workshop-real/result.json`
- `workshop-steamcmd/result.json`
- `free-dlc-candidates.json`
- `acf-before.sha256`
- `acf-after.sha256`
