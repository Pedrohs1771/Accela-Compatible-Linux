# ACCELA Windows Reference Notes

Reference archive:

`/home/pedrohs/Downloads/ACCELA-20260417235509-windows-binary (2).zip`

Files observed outside the repository:

- `ACCELA.exe`
- `vc_redist.x64.exe`
- `vc_redist.x86.exe`

Static observations:

- `ACCELA.exe` is a Windows PE32+ x86-64 GUI executable.
- `ACCELA.exe` size: `171530775` bytes.
- `ACCELA.exe` SHA256:
  `8f37f6828e60e43f6a1b7bbc4f145440b160df08de62fd4ab1a721731d80af14`
- `vc_redist.x64.exe` SHA256:
  `8995548dfffcde7c49987029c764355612ba6850ee09a7b6f0fddc85bdc5c280`
- `vc_redist.x86.exe` SHA256:
  `e7267c1bdf9237c0b4a28cf027c382b97aa909934f84f1c92d3fb9f04173b33e`
- Strings indicate PyInstaller runtime markers such as `_MEIPASS` and
  `PYINSTALLER_*`.
- The archive bundles VC Redistributables next to the executable.

Use in LumaTools:

- Used as packaging/runtime reference only.
- The binary was not copied into the repository.
- No source code was extracted or reused.
- The new Windows RC uses current LumaTools Python source and GitHub Actions
  `windows-latest` PyInstaller packaging.
