# LumaTools v1.1.0 RC Windows Notes

Highlights:

- Windows 10/11 x64 support through platform-specific Steam detection.
- `%LOCALAPPDATA%` data, jobs, logs, DLC cache and Workshop cache layout.
- Safe depot job staging with per-job keys/manifests/logs/result files.
- Real DLC install flow through cache/cube/verifier semantics.
- Workshop staging, rollback and physical enable/disable support.
- Windows Doctor and Repair entrypoints for CI smoke.
- One-line PowerShell bootstrap.

Release status:

This is an RC when validated by GitHub Actions `windows-latest`. It should not
be marked final until the artifact is run on real Windows 10/11 machines.
