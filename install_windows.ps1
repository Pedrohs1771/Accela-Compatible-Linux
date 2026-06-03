param(
    [string]$SourceRoot = $(Split-Path -Parent $MyInvocation.MyCommand.Path),
    [string]$InstallRoot = $(Join-Path $env:LOCALAPPDATA "Programs\LumaTools"),
    [switch]$NoDesktopShortcut,
    [switch]$SkipVCRedist
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[LumaTools] $Message"
}

function Copy-Tree([string]$Source, [string]$Target) {
    if (-not (Test-Path $Target)) {
        New-Item -ItemType Directory -Force -Path $Target | Out-Null
    }
    Copy-Item -Path (Join-Path $Source '*') -Destination $Target -Recurse -Force
}

function Copy-FileIfExists([string]$Source, [string]$TargetDir) {
    if (Test-Path $Source) {
        New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
        Copy-Item -Path $Source -Destination $TargetDir -Force
    }
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

function Test-Python([string]$PythonExe) {
    if (-not $PythonExe) {
        return $false
    }
    try {
        $code = "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        & $PythonExe -c $code *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Find-Python {
    $candidates = @()
    if ($env:LUMATOOLS_PYTHON) {
        $candidates += $env:LUMATOOLS_PYTHON
    }
    $candidates += (Join-Path $InstallRoot "Python\python.exe")
    $candidates += "python"
    $candidates += "python3"

    foreach ($candidate in $candidates) {
        if (Test-Python $candidate) {
            return $candidate
        }
    }

    try {
        & py -3.12 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3.12"
        }
    } catch {
    }

    try {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return "py -3"
        }
    } catch {
    }

    return $null
}

function Invoke-Python([string]$PythonCommand, [string[]]$Arguments) {
    if ($PythonCommand -like "py -*") {
        $parts = $PythonCommand.Split(" ", 2)
        & $parts[0] $parts[1] @Arguments
    } else {
        & $PythonCommand @Arguments
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed: $PythonCommand $($Arguments -join ' ')"
    }
}

function Install-Python {
    $targetDir = Join-Path $InstallRoot "Python"
    $pythonExe = Join-Path $targetDir "python.exe"
    if (Test-Python $pythonExe) {
        return $pythonExe
    }

    Write-Step "Python 3.12+ não encontrado. Instalando Python local..."
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        try {
            & winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements --scope user
            $found = Find-Python
            if ($found) {
                return $found
            }
        } catch {
            Write-Step "Winget não conseguiu instalar Python; usando instalador oficial."
        }
    }

    $installer = Join-Path $env:TEMP "python-3.12.10-amd64.exe"
    $url = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    Invoke-WebRequest -Uri $url -OutFile $installer
    $args = @(
        "/quiet",
        "InstallAllUsers=0",
        "PrependPath=0",
        "Include_launcher=1",
        "Include_pip=1",
        "Include_test=0",
        "TargetDir=$targetDir"
    )
    Start-Process -FilePath $installer -ArgumentList $args -Wait
    Remove-Item $installer -Force -ErrorAction SilentlyContinue

    if (-not (Test-Python $pythonExe)) {
        throw "Python installation failed."
    }
    return $pythonExe
}

function Install-VCRedist {
    if ($SkipVCRedist) {
        return
    }
    Write-Step "Verificando Microsoft Visual C++ Runtime..."
    $installer = Join-Path $env:TEMP "vc_redist.x64.exe"
    try {
        Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $installer
        $process = Start-Process -FilePath $installer -ArgumentList "/install /quiet /norestart" -Wait -PassThru
        if ($process.ExitCode -notin @(0, 1638, 3010)) {
            Write-Step "VC++ Runtime retornou código $($process.ExitCode); continuando."
        }
    } catch {
        Write-Step "Não foi possível instalar VC++ Runtime automaticamente; continuando."
    } finally {
        Remove-Item $installer -Force -ErrorAction SilentlyContinue
    }
}

function Copy-LumaToolsPayload {
    $source = (Resolve-Path $SourceRoot).Path
    Write-Step "Preparando arquivos em $InstallRoot"

    if (Test-Path $InstallRoot) {
        Remove-Item $InstallRoot -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null

    $packageBin = Join-Path $source "bin"
    $repoBin = Join-Path $source "app\LumaTools\squashfs-root\bin"

    if ((Test-Path (Join-Path $packageBin "src\main.py")) -and (Test-Path (Join-Path $packageBin "requirements.txt"))) {
        Copy-Tree $source $InstallRoot
        Remove-Item (Join-Path $InstallRoot ".venv") -Recurse -Force -ErrorAction SilentlyContinue
    } elseif ((Test-Path (Join-Path $repoBin "src\main.py")) -and (Test-Path (Join-Path $repoBin "requirements.txt"))) {
        Copy-Tree $repoBin (Join-Path $InstallRoot "bin")
        Copy-FileIfExists (Join-Path $source "README.md") $InstallRoot
        Copy-FileIfExists (Join-Path $source "install_windows.ps1") $InstallRoot
        Copy-FileIfExists (Join-Path $source "windows\Launch-LumaTools.cmd") $InstallRoot
        Copy-FileIfExists (Join-Path $source "windows\Run-LumaTools.ps1") $InstallRoot
        if (Test-Path (Join-Path $source "release")) {
            Copy-Tree (Join-Path $source "release") (Join-Path $InstallRoot "release")
        }
    } else {
        throw "Pacote Windows inválido: não encontrei bin\src\main.py ou app\LumaTools\squashfs-root\bin."
    }

    if (-not (Test-Path (Join-Path $InstallRoot "Launch-LumaTools.cmd"))) {
        throw "Launch-LumaTools.cmd não encontrado no pacote."
    }
}

function New-LumaVenv([string]$PythonCommand) {
    $venv = Join-Path $InstallRoot ".venv"
    $requirements = Join-Path $InstallRoot "bin\requirements.txt"
    if (-not (Test-Path $requirements)) {
        throw "requirements.txt não encontrado em $requirements"
    }

    Write-Step "Criando ambiente Python..."
    Remove-Item $venv -Recurse -Force -ErrorAction SilentlyContinue
    Invoke-Python $PythonCommand @("-m", "venv", $venv)

    $venvPython = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "Falha ao criar venv em $venv"
    }

    Write-Step "Instalando dependências Python..."
    & $venvPython -m pip install --upgrade pip setuptools wheel
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao atualizar pip/setuptools/wheel."
    }

    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) {
        throw "Falha ao instalar requirements.txt."
    }
}

Copy-LumaToolsPayload
Install-VCRedist
$python = Find-Python
if (-not $python) {
    $python = Install-Python
}
New-LumaVenv $python

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
Write-Step "LumaTools instalado em $InstallRoot"
Write-Step "Abra pelo atalho ou execute: $launcher"
