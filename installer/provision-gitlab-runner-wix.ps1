param(
    [string] $RunnerServiceName = "gitlab-runner",
    [string] $WixExePath,
    [string] $EulaId = "wix7"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-EulaFilePath {
    param(
        [Parameter(Mandatory = $true)]
        [string] $UserProfilePath,
        [Parameter(Mandatory = $true)]
        [string] $AcceptedEulaId
    )

    return Join-Path $UserProfilePath ".wix\$AcceptedEulaId-osmf-eula.txt"
}

$service = Get-CimInstance Win32_Service -Filter "Name = '$RunnerServiceName'" -ErrorAction SilentlyContinue
if (-not $service) {
    throw "Windows service '$RunnerServiceName' was not found."
}

$ensureScript = Join-Path $PSScriptRoot "ensure-wix-license.ps1"
if (-not (Test-Path -LiteralPath $ensureScript)) {
    throw "Required script missing: $ensureScript"
}

Write-Host ""
Write-Host "=== GitLab Runner WiX Provisioning ===" -ForegroundColor Cyan
Write-Host "Runner service : $RunnerServiceName"
Write-Host "Start account  : $($service.StartName)"

if ($service.StartName -eq "LocalSystem") {
    if (-not (Test-IsAdministrator)) {
        throw "This script must be run from an elevated PowerShell session when the runner service uses LocalSystem."
    }

    Write-Host "Accepting WiX EULA for the current elevated account and copying it into the LocalSystem profile..." -ForegroundColor Yellow
    & $ensureScript -WixExePath $WixExePath -EulaId $EulaId

    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the WiX acceptance marker for the current account."
    }

    $currentUserProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    $currentEulaPath = Get-EulaFilePath -UserProfilePath $currentUserProfile -AcceptedEulaId $EulaId
    if (-not (Test-Path -LiteralPath $currentEulaPath)) {
        throw "Current-account EULA file was not created: $currentEulaPath"
    }

    $systemProfile = Join-Path $env:WINDIR "System32\config\systemprofile"
    $systemEulaPath = Get-EulaFilePath -UserProfilePath $systemProfile -AcceptedEulaId $EulaId
    $systemEulaDir = Split-Path -Parent $systemEulaPath
    New-Item -ItemType Directory -Force -Path $systemEulaDir | Out-Null
    Copy-Item -LiteralPath $currentEulaPath -Destination $systemEulaPath -Force

    if (-not (Test-Path -LiteralPath $systemEulaPath)) {
        throw "Expected LocalSystem EULA file was not created: $systemEulaPath"
    }

    Write-Host "LocalSystem WiX acceptance is now persisted at $systemEulaPath" -ForegroundColor Green
    exit 0
}

if ($service.StartName -eq [Security.Principal.WindowsIdentity]::GetCurrent().Name) {
    & $ensureScript -WixExePath $WixExePath -EulaId $EulaId
    exit $LASTEXITCODE
}

throw @"
The runner service is configured for '$($service.StartName)', but this shell is '$([Security.Principal.WindowsIdentity]::GetCurrent().Name)'.
Run this script while logged in as the runner service account, or reconfigure the runner to use a dedicated build account and then execute:

powershell -ExecutionPolicy Bypass -File `"$ensureScript`" -WixExePath `"$WixExePath`" -EulaId $EulaId
"@
