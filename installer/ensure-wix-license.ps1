param(
    [string] $WixExePath,
    [string] $EulaId = "wix7",
    [switch] $Force
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Resolve-WixExe {
    param([string] $PreferredPath)

    if ($PreferredPath) {
        if (-not (Test-Path -LiteralPath $PreferredPath)) {
            throw "WiX executable not found at '$PreferredPath'."
        }

        return (Resolve-Path -LiteralPath $PreferredPath).Path
    }

    $command = Get-Command wix.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $commonPaths = @(
        "C:\Program Files\WiX Toolset v7.0\bin\wix.exe",
        "C:\Program Files (x86)\WiX Toolset v7.0\bin\wix.exe"
    )

    foreach ($path in $commonPaths) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }

    throw "Could not find wix.exe. Install WiX Toolset v7 or add it to PATH."
}

function Get-EulaFilePath {
    param([string] $AcceptedEulaId)

    $userProfile = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
    if ([string]::IsNullOrWhiteSpace($userProfile)) {
        throw "USERPROFILE could not be resolved for the current account."
    }

    return Join-Path $userProfile ".wix\$AcceptedEulaId-osmf-eula.txt"
}

$resolvedWixExe = Resolve-WixExe -PreferredPath $WixExePath
$eulaFilePath = Get-EulaFilePath -AcceptedEulaId $EulaId

Write-Host ""
Write-Host "=== WiX v7 EULA Provisioning ===" -ForegroundColor Cyan
Write-Host "Identity     : $([Security.Principal.WindowsIdentity]::GetCurrent().Name)"
Write-Host "USERPROFILE  : $([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile))"
Write-Host "wix.exe      : $resolvedWixExe"
Write-Host "EULA file    : $eulaFilePath"

if ((Test-Path -LiteralPath $eulaFilePath) -and -not $Force) {
    Write-Host "WiX EULA is already accepted for this account." -ForegroundColor Green
    exit 0
}

Write-Host "Accepting WiX OSMF EULA for the current runner identity..." -ForegroundColor Yellow
& $resolvedWixExe eula accept $EulaId

if ($LASTEXITCODE -ne 0) {
    throw "wix.exe eula accept failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path -LiteralPath $eulaFilePath)) {
    throw "WiX reported success but '$eulaFilePath' was not created."
}

Write-Host "WiX EULA accepted and persisted successfully." -ForegroundColor Green
