param(
    [string] $Version,
    [string] $SetupExePath,
    [string] $OutputDir = (Join-Path $PSScriptRoot "dist\msi"),
    [string] $PortalInstallersDir = (Join-Path (Split-Path $PSScriptRoot -Parent) "backend\dist\installers")
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-AgentVersion {
    $bootstrapperPath = Join-Path $PSScriptRoot "bootstrapper.py"
    $match = Select-String -Path $bootstrapperPath -Pattern 'VERSION = "([^"]+)"' | Select-Object -First 1
    if (-not $match) {
        throw "Could not determine installer version from $bootstrapperPath"
    }
    return $match.Matches[0].Groups[1].Value
}

function Find-WixBinary {
    param([Parameter(Mandatory = $true)][string] $Name)

    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $commonPaths = @(
        "C:\Program Files (x86)\WiX Toolset v3.11\bin\$Name",
        "C:\Program Files\WiX Toolset v3.11\bin\$Name"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    throw "Could not find $Name. Install WiX Toolset 3.11 or ensure it is on PATH."
}

function Find-WixCli {
    $cmd = Get-Command "wix.exe" -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $commonPaths = @(
        "C:\Program Files\WiX Toolset v7.0\bin\wix.exe",
        "C:\Program Files (x86)\WiX Toolset v7.0\bin\wix.exe"
    )
    foreach ($path in $commonPaths) {
        if (Test-Path $path) {
            return $path
        }
    }

    return $null
}

if (-not $Version) {
    $Version = Get-AgentVersion
}

if (-not $SetupExePath) {
    $SetupExePath = Join-Path $PSScriptRoot "dist\setup\cropsentinel-agent-$Version-setup.exe"
}

if (-not (Test-Path $SetupExePath)) {
    throw "Setup EXE not found: $SetupExePath"
}

$wxsPath = Join-Path $PSScriptRoot "wix\CropSentinelAgent.wxs"
$buildDir = Join-Path $PSScriptRoot "build\msi"
$generatedWxsPath = Join-Path $buildDir "CropSentinelAgent.generated.wxs"
$msiName = "cropsentinel-agent-$Version.msi"
$msiOutputPath = Join-Path $OutputDir $msiName
$wixCli = Find-WixCli
$candle = $null
$light = $null

if (-not $wixCli) {
    $candle = Find-WixBinary -Name "candle.exe"
    $light = Find-WixBinary -Name "light.exe"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
New-Item -ItemType Directory -Force -Path $PortalInstallersDir | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $buildDir "*"), $msiOutputPath

Write-Host ""
Write-Host "=== CropSentinel Agent MSI Build ===" -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host "Setup EXE: $SetupExePath"
Write-Host ""

$wxsTemplate = Get-Content -Path $wxsPath -Raw
$wxsRendered = $wxsTemplate.Replace('$(var.ProductVersion)', $Version).Replace('$(var.SetupExePath)', $SetupExePath)
Set-Content -Path $generatedWxsPath -Value $wxsRendered -Encoding UTF8

if ($wixCli) {
    Write-Host "Using WiX CLI: $wixCli" -ForegroundColor DarkGray

    & $wixCli build `
        -nologo `
        -acceptEula wix7 `
        -arch x64 `
        -o $msiOutputPath `
        $generatedWxsPath

    if ($LASTEXITCODE -ne 0) {
        throw "WiX CLI build failed with exit code $LASTEXITCODE"
    }
}
else {
    Write-Host "Using WiX v3 toolchain: $candle / $light" -ForegroundColor DarkGray

    & $candle `
        -nologo `
        -arch x64 `
        -out (Join-Path $buildDir "CropSentinelAgent.wixobj") `
        $generatedWxsPath

    if ($LASTEXITCODE -ne 0) {
        throw "WiX candle.exe failed with exit code $LASTEXITCODE"
    }

    & $light `
        -nologo `
        -sice:ICE61 `
        -out $msiOutputPath `
        (Join-Path $buildDir "CropSentinelAgent.wixobj")

    if ($LASTEXITCODE -ne 0) {
        throw "WiX light.exe failed with exit code $LASTEXITCODE"
    }
}

Copy-Item $msiOutputPath -Destination (Join-Path $PortalInstallersDir $msiName) -Force

Write-Host ""
Write-Host "MSI output : $msiOutputPath" -ForegroundColor Green
Write-Host "Portal copy : $(Join-Path $PortalInstallersDir $msiName)" -ForegroundColor Green
