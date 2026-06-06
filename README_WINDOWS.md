# LumaTools Windows RC

This is a Windows 10/11 x64 release candidate. It is built on GitHub Actions
`windows-latest` because PyInstaller should package on the target OS.

One-line installer:

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "iwr -useb https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/bootstrap_windows.ps1 | iex"
```

Installed paths:

- Program: `%LOCALAPPDATA%\Programs\LumaTools`
- Data: `%LOCALAPPDATA%\LumaTools`
- Logs: `%LOCALAPPDATA%\LumaTools\logs`
- Backups: `%LOCALAPPDATA%\LumaTools\backups`
- Jobs: `%LOCALAPPDATA%\LumaTools\jobs`

This RC does not require admin by default. Steam libraries under protected
locations may require the user to fix permissions or choose another library.
