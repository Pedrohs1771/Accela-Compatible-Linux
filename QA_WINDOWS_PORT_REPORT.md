# QA Windows Port Report

Date: 2026-06-06

Branch: `release/windows-v1.1.0-rc`

Conclusion: `APPROVED_RC_BY_CI_PENDING_REAL_WINDOWS_10_11_MANUAL_TEST`

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

The artifact was built by `.github/workflows/windows-rc.yml` on
`windows-latest`/Windows 2025. This is approved as an RC by CI, not a final
Windows release. Final release still requires at least one real Windows 10/11
machine test with Steam installed.

- CI run: https://github.com/Pedrohs1771/Luma-Tools/actions/runs/27069351812
- Head SHA: `403e599e8af4c942ce83fb260c755f5590e524ab`
- Artifact: `LumaTools-Windows-v1.1.0-rc`
- Artifact size: 486,548,693 bytes

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
- Windows PyInstaller artifact: `PASS`.
  - Workflow: `.github/workflows/windows-rc.yml`
  - Build job: `windows-build`
  - Smoke: `LumaDoctor.exe --self-test`
  - Uploaded artifact: `LumaTools-Windows-v1.1.0-rc`

## Recommendation

Publish as RC. Do not publish as final until the artifact is tested on a real
Windows 10/11 machine with Steam installed.
