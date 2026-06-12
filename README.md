<p align="right">
  <a href="./README.pt-br.md">🇧🇷 Leia em Português</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/app/LumaTools/squashfs-root/bin/res/logo.png" alt="LumaTools Logo" width="200">
</p>

<h1 align="center">LumaTools</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" alt="Windows">
  <img src="https://img.shields.io/badge/Linux-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="Linux">
  <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Status-Experimental_Windows-orange?style=for-the-badge" alt="Status">
</p>

<p align="center">
  <strong>The ultimate Swiss Army knife for game management and Steam compatibility.</strong><br>
  Developed by <b>Pedrohs</b>.
</p>

---

## 🚀 What is LumaTools?

**LumaTools** is a cross-platform launcher and library manager designed to give you total control over your Steam games. It automates complex processes such as downloading depots, applying compatibility patches, and emulating online features, ensuring a seamless gaming experience whether you are on **Linux (Arch, SteamOS, Ubuntu)** or **Windows (10/11)**.

## 🌟 Elite Features

*   **⚡ Native Steam Engine**: Deep integration with native Steam for library detection, manifests, and file management.
*   **🌐 Online-Compatible Core**: Built-in engine to automatically enable multiplayer and cooperative features.
*   **📦 Smart Depot Management**: Intelligent system to download and manage specific depots, optimizing disk space.
*   **🛠️ Zero-Config Goldberg Integration**: Automated application of the Goldberg Steam Emulator with `steam_appid.txt` generation and DLL injection.
*   **🔓 Steamless Auto-Unpack**: Automatic unpacking of SteamStub-protected executables for maximum performance.
*   **🎮 Cross-Platform Mastery**: Unified logic that adapts the app's behavior to the specific needs of each OS (Proton on Linux / Native on Windows).
*   **🏆 Achievement Generator**: System for generating and managing achievements for your personal library.

---

## 📥 Quick Installation (One-Liner)

### Windows (PowerShell)
Open PowerShell and paste this one-liner. It downloads the full Windows beta package first, then runs the local Windows installer:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $base=Join-Path $env:USERPROFILE 'Downloads\LumaTools-Windows-Install'; Remove-Item $base -Recurse -Force -ErrorAction SilentlyContinue; New-Item -ItemType Directory -Force $base | Out-Null; Set-Location $base; Invoke-WebRequest -Uri 'https://github.com/Pedrohs1771/Luma-Tools/releases/download/v1.0.7-windows-beta1/LumaTools-Windows-v1.0.7-beta1.zip' -OutFile 'LumaTools-Windows-v1.0.7-beta1.zip'; Expand-Archive -Force 'LumaTools-Windows-v1.0.7-beta1.zip' .; $installer=Get-ChildItem -Path . -Recurse -Filter install_windows.ps1 | Select-Object -First 1; if (-not $installer) { throw 'install_windows.ps1 not found in package' }; Set-Location $installer.DirectoryName; powershell -NoProfile -ExecutionPolicy Bypass -File $installer.FullName"
```

### Linux / Steam Deck (Terminal)
Open your favorite terminal and paste this one-liner to install the current ready version from the `main` branch. This is the recommended command when you want the newest committed LumaTools build:
```bash
curl -fsSL https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/bootstrap.sh | bash -s -- --from-main --fix-all
```

Alternative using `wget`:
```bash
wget -qO- https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/bootstrap.sh | bash -s -- --from-main --fix-all
```

Stable release channel. This resolves the latest Linux package from GitHub Releases, installs/updates LumaTools, and runs the repair pass for managed Steam appmanifests and SLSsteam entries:
```bash
curl -fsSL https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/bootstrap.sh | bash -s -- --fix-all
```

Stable release alternative using `wget`:
```bash
wget -qO- https://raw.githubusercontent.com/Pedrohs1771/Luma-Tools/main/bootstrap.sh | bash -s -- --fix-all
```

Manual fallback using `git`:
```bash
git clone --depth=1 https://github.com/Pedrohs1771/Luma-Tools.git
cd Luma-Tools
bash install.sh --no-prompt
```

Repair an existing installation:
```bash
lumatools --fix-all
```

### Linux Steam Modes

| Steam installation | LumaTools | SLSsteam |
| --- | --- | --- |
| Native package | Supported | Supported with ELF compatibility validation |
| Flatpak | Supported | Supported through the official Flatpak override and shared-library guard |
| Snap | Supported for library detection and clean Steam launch | Not currently supported by the official SLSsteam installer |

When more than one Steam package is installed, LumaTools prioritizes the
instance that is currently running. The clean fallback removes inherited
`LD_AUDIT`, `LD_PRELOAD`, and `SHARED_LIBRARY_GUARD` values to prevent
`ELFCLASS32`/`ELFCLASS64` startup failures.

### Release Assets

Linux stable:
```text
Always fetched automatically by bootstrap.sh from the latest GitHub release.
```

Windows beta:
```text
LumaTools-Windows-v1.0.7-beta1.zip
LumaTools-Windows-Port-Complete-v1.0.7-beta1.zip
```

---

## 🧠 Project Structure

```text
LumaTools/
├── app/LumaTools/          # Core application (Python + Resources)
├── windows/                # Windows-specific binaries and launchers
├── tools/                  # Build and automation scripts
├── install.sh              # Intelligent Linux installer
├── install_windows.ps1     # Intelligent Windows installer
└── lumatools               # Global command for Linux
```

---

## 🤝 Special Thanks

This project would not be possible without the solid foundation and inspiration from previous open-source projects. Special thanks to the **ACCELA** project for providing the base that allowed LumaTools to evolve.

*   **Open Source Base**: [ACCELA Dist Archive](https://portal3d.github.io/accela-dist-archive/)

---

## 🛠️ How to Build (Windows)

If you are a developer and want to generate your own build:

1.  Have **Python 3.10+** installed.
2.  Run the build script:
    ```powershell
    python tools/build_windows.py
    ```
3.  The final package will be available in the `dist/` folder.

---

<p align="center">
  Created with ❤️ by <b>Pedrohs</b>
</p>
