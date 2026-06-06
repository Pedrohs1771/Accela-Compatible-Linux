# Troubleshooting Windows

- If antivirus quarantines the executable, restore it and allow the install
  directory. New PyInstaller apps are commonly flagged until reputation builds.
- If Steam is not detected, check `HKCU\Software\Valve\Steam` and
  `HKLM\Software\WOW6432Node\Valve\Steam`, then verify `steamapps`.
- If Workshop downloads fail with `needs_login`, use SteamCMD login manually.
- If DLC is `metadata_only`, the package did not include physical files and a
  manifest that can be installed.
- If a job fails, inspect `%LOCALAPPDATA%\LumaTools\jobs\<job_id>\result.json`.
- Rollbacks/backups are stored in `%LOCALAPPDATA%\LumaTools\backups`.
