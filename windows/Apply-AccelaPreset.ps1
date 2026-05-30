param(
    [switch]$ForceDefaults
)

$ErrorActionPreference = "Stop"

$baseKey = "HKCU:\Software\Tachibana Labs\ACCELA"
if (-not (Test-Path $baseKey)) {
    New-Item -Path $baseKey -Force | Out-Null
}

function Set-AccelaSetting {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Type
    )

    $existing = Get-ItemProperty -Path $baseKey -Name $Name -ErrorAction SilentlyContinue
    if ($existing -and -not $ForceDefaults) {
        return
    }

    New-ItemProperty -Path $baseKey -Name $Name -Value $Value -PropertyType $Type -Force | Out-Null
}

Set-AccelaSetting -Name "github_updates_enabled" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "github_auto_update" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "github_signed_updates_only" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "github_updates_repo" -Value "Pedrohs1771/Accela-Compatible-Linux" -Type "String"
Set-AccelaSetting -Name "github_updates_branch" -Value "main" -Type "String"
Set-AccelaSetting -Name "discord_presence_enabled" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "discord_presence_large_image" -Value "accela_large" -Type "String"
Set-AccelaSetting -Name "discord_presence_small_image" -Value "" -Type "String"
Set-AccelaSetting -Name "play_etw" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "play_lall" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "play_50hz_hum" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "master_volume" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "effects_volume" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "hum_volume" -Value 0 -Type "DWord"
Set-AccelaSetting -Name "prompt_steam_restart" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "close_to_tray" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "auto_close_with_steam" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "gif_display_enabled" -Value 1 -Type "DWord"
Set-AccelaSetting -Name "titlebar_position" -Value "bottom" -Type "String"

Write-Host "ACCELA preset aplicado em HKCU\\Software\\Tachibana Labs\\ACCELA"
