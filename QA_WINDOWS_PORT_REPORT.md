# QA Windows Port Report

Date: 2026-06-06

Branch: `release/windows-v1.1.0-rc`

Conclusion: `APPROVED_RC_BY_LOCAL_TESTS_PENDING_WINDOWS_CI`

## Environment

- Development host: Linux.
- Windows build target: GitHub Actions `windows-latest`.
- Windows real-machine manual testing: not available in this session.

## Implemented

- Platform backend interface under `platforms/`.
- Windows Steam detection via registry/fallback path abstraction.
- `%LOCALAPPDATA%\LumaTools` data layout.
- Per-job Windows layout with `keys.vdf`, `manifests`, `staging`, `logs`,
  `download_plan.json` and `result.json`.
- Windows localconfig LaunchOptions writer with backups.
- ACF string escaping and atomic write/rollback.
- Windows Doctor and Repair entrypoints.
- PyInstaller Windows build script for GitHub Actions.
- PowerShell bootstrap/uninstall.
- ACCELA reference notes.

## CI Requirement

The artifact must be built by `.github/workflows/windows-rc.yml` on
`windows-latest`. Without that CI artifact and smoke test, this remains an RC,
not a final Windows release.

## Status

- Linux regression: `PASS`.
  - Command: `PYTHONPATH=app/LumaTools/squashfs-root/bin/src python -m unittest discover -s tests -v`
  - Result: `Ran 34 tests ... OK`
- Compile check: `PASS`.
  - Command: `python -m compileall -q app/LumaTools/squashfs-root/bin/src tests tools windows`
- Windows simulated fixtures: `PASS`.
  - Covered `%LOCALAPPDATA%` layout, job isolation, fake Steam registry root,
    fake `libraryfolders.vdf`, `localconfig.vdf` launch options, ACF escaping,
    atomic ACF backup and rollback.
- Windows source-package dry run: `PASS`.
  - Command: `PYTHONPATH=app/LumaTools/squashfs-root/bin/src python tools/build_windows.py --skip-pyinstaller`
  - Output: `dist/LumaTools-Windows-v1.1.0-rc.zip`
- Windows PyInstaller artifact: `PENDING_GITHUB_ACTIONS`.
  - Required workflow: `.github/workflows/windows-rc.yml`

## Recommendation

Publish as RC only after GitHub Actions passes and uploads
`LumaTools-Windows-v1.1.0-rc.zip`.
