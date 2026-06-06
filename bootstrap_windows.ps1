$ErrorActionPreference = "Stop"

$Repo = "Pedrohs1771/Luma-Tools"
$InstallRoot = Join-Path $env:LOCALAPPDATA "Programs\LumaTools"
$DataRoot = Join-Path $env:LOCALAPPDATA "LumaTools"
$BackupRoot = Join-Path $DataRoot "backups"
$TempRoot = Join-Path $DataRoot "temp"

function Write-Step([string]$Message) {
    Write-Host "[LumaTools] $Message"
}

function New-Dir([string]$Path) {
    if (-not (Test-Path $Path)) {
        New-Item -ItemType Directory -Force -Path $Path | Out-Null
    }
}

function Get-LatestReleaseAsset {
    $api = "https://api.github.com/repos/$Repo/releases/latest"
    $release = Invoke-RestMethod -Uri $api -Headers @{ "User-Agent" = "LumaTools-Windows-Bootstrap" }
    $asset = $release.assets | Where-Object { $_.name -like "LumaTools-Windows-*.zip" } | Select-Object -First 1
    if (-not $asset) {
        throw "No Windows release zip found in latest GitHub release."
    }
    return $asset
}

function Add-ToUserPath([string]$PathToAdd) {
    $current = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($current -and ($current.Split(";") -contains $PathToAdd)) {
        return
    }
    $newPath = if ($current) { "$current;$PathToAdd" } else { $PathToAdd }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
}

if (-not [Environment]::Is64BitOperatingSystem) {
    throw "LumaTools Windows RC requires Windows x64."
}

New-Dir $DataRoot
New-Dir $BackupRoot
New-Dir $TempRoot
New-Dir (Split-Path -Parent $InstallRoot)

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
if (Test-Path $InstallRoot) {
    $backup = Join-Path $BackupRoot "$timestamp`__windows-install"
    Write-Step "Backing up previous install to $backup"
    Move-Item -Path $InstallRoot -Destination $backup -Force
}

$asset = Get-LatestReleaseAsset
$zipPath = Join-Path $TempRoot $asset.name
Write-Step "Downloading $($asset.browser_download_url)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath

$extractRoot = Join-Path $TempRoot "extract-$timestamp"
New-Dir $extractRoot
Expand-Archive -Path $zipPath -DestinationPath $extractRoot -Force

$payload = Join-Path $extractRoot "LumaTools"
if (-not (Test-Path $payload)) {
    throw "Invalid package: LumaTools directory missing."
}

Move-Item -Path $payload -Destination $InstallRoot -Force

$doctor = Join-Path $InstallRoot "LumaDoctor.exe"
if (Test-Path $doctor) {
    & $doctor --self-test | Write-Host
    if ($LASTEXITCODE -ne 0) {
        throw "LumaDoctor self-test failed."
    }
}

$startMenu = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
$shortcut = Join-Path $startMenu "LumaTools.lnk"
$exe = Join-Path $InstallRoot "LumaTools.exe"
if (Test-Path $exe) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($shortcut)
    $link.TargetPath = $exe
    $link.WorkingDirectory = $InstallRoot
    $link.IconLocation = $exe
    $link.Save()
    Add-ToUserPath $InstallRoot
}

Write-Host "INSTALLED_OK"
