$ErrorActionPreference = "Stop"

$InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LumaTools"
$DataRoot = Join-Path $env:LOCALAPPDATA "LumaTools"
$Shortcut = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\LumaTools.lnk"

if (Test-Path $Shortcut) {
    Remove-Item $Shortcut -Force
}

if (Test-Path $InstallRoot) {
    Remove-Item $InstallRoot -Recurse -Force
}

Write-Host "LumaTools program files removed."
Write-Host "User data was kept at: $DataRoot"
