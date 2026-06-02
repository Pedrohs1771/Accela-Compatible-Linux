param(
    [string]$SourceRoot = $(Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$InstallRoot = $(Join-Path $env:LOCALAPPDATA "Programs\LumaTools"),
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"

function Copy-Tree([string]$Source, [string]$Target) {
    if (-not (Test-Path $Target)) {
        New-Item -ItemType Directory -Force -Path $Target | Out-Null
    }
    Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments = "") {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.Arguments = $Arguments
    $shortcut.WorkingDirectory = Split-Path -Parent $Target
    $shortcut.IconLocation = $Target
    $shortcut.Save()
}

function Register-Protocol([string]$LauncherPath) {
    $template = Join-Path $InstallRoot "bin\src\deps\LumaTools.reg"
    if (-not (Test-Path $template)) {
        return
    }

    $escaped = $LauncherPath.Replace('\', '\\')
    $tempReg = Join-Path $env:TEMP "lumatools-register.reg"
    (Get-Content $template -Raw).Replace("[INSTALL_PATH]", $escaped) | Set-Content -Path $tempReg -Encoding UTF8
    Start-Process -FilePath "regedit.exe" -ArgumentList "/s `"$tempReg`"" -Wait
    Remove-Item $tempReg -Force -ErrorAction SilentlyContinue
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
Copy-Tree $SourceRoot $InstallRoot

$launcher = Join-Path $InstallRoot "Launch-LumaTools.cmd"
$desktop = [Environment]::GetFolderPath("Desktop")
$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcutDir = Join-Path $startMenu "LumaTools"
New-Item -ItemType Directory -Force -Path $shortcutDir | Out-Null

New-Shortcut -Path (Join-Path $shortcutDir "LumaTools.lnk") -Target $launcher
if (-not $NoDesktopShortcut) {
    New-Shortcut -Path (Join-Path $desktop "LumaTools.lnk") -Target $launcher
}

Register-Protocol $launcher
Write-Host "LumaTools instalado em $InstallRoot"
