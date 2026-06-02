# CropSentinel Agent EXE build pipeline
#
# Usage:
#     cd installer
#     .\build.ps1
#
# What it does:
#     1) Publishes the native Windows worker and native session-supervisor service.
#     2) Builds installer\bootstrapper.py into a single EXE that bundles the native payload.
#     3) Copies the resulting EXE and ZIP bundle into backend\dist\installers\ for portal delivery.

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$Version = '1.3.0'
$InstallerBaseName = "cropsentinel-agent-$Version-setup"
$InstallerName = "$InstallerBaseName.exe"
$BundleName = "cropsentinel-agent-$Version-windows.zip"
$BundleDir = Join-Path $env:TEMP "cropsentinel-agent-bundle-$Version"
$RepoRoot = Resolve-Path ..
$PortalInstallersDir = Join-Path $RepoRoot 'backend\dist\installers'
$AssetsDir = Join-Path $PSScriptRoot 'assets'
$AppIcon = Join-Path $AssetsDir 'app.ico'
$PayloadManifestName = 'payload-manifest.json'

Write-Host ''
Write-Host '=== CropSentinel Agent EXE Build ===' -ForegroundColor Cyan
Write-Host "Version: $Version"
Write-Host ''

function Find-PythonCommand {
    $commands = @(
        @{ Exe = 'python'; Prefix = @() },
        @{ Exe = 'py'; Prefix = @('-3.11') }
    )

    $commonPythonPaths = @(
        'C:\Python311\python.exe',
        'C:\Python312\python.exe',
        'C:\Program Files\Python311\python.exe',
        'C:\Program Files\Python312\python.exe',
        'C:\Users\husai\AppData\Local\Python\bin\python.exe',
        'C:\Users\husai\AppData\Local\Programs\Python\Python311\python.exe',
        'C:\Users\husai\AppData\Local\Programs\Python\Python312\python.exe'
    )

    foreach ($path in $commonPythonPaths) {
        if (Test-Path $path) {
            $commands += @{ Exe = $path; Prefix = @() }
        }
    }

    foreach ($candidate in $commands) {
        try {
            & $candidate.Exe @($candidate.Prefix + @('--version')) *> $null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]$candidate
            }
        }
        catch {
        }
    }

    return $null
}

function Find-PyInstaller {
    $directExecutables = @(
        'pyinstaller',
        'C:\Python311\Scripts\pyinstaller.exe',
        'C:\Python312\Scripts\pyinstaller.exe',
        'C:\Program Files\Python311\Scripts\pyinstaller.exe',
        'C:\Program Files\Python312\Scripts\pyinstaller.exe',
        'C:\Users\husai\AppData\Local\Python\bin\pyinstaller.exe',
        'C:\Users\husai\AppData\Local\Programs\Python\Python311\Scripts\pyinstaller.exe',
        'C:\Users\husai\AppData\Local\Programs\Python\Python312\Scripts\pyinstaller.exe'
    )

    foreach ($exe in $directExecutables) {
        try {
            & $exe --version *> $null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{
                    Exe    = $exe
                    Prefix = @()
                }
            }
        }
        catch {
        }
    }

    $python = Find-PythonCommand
    if ($python) {
        try {
            & $python.Exe @($python.Prefix + @('-m', 'PyInstaller', '--version')) *> $null
            if ($LASTEXITCODE -eq 0) {
                return [pscustomobject]@{
                    Exe    = $python.Exe
                    Prefix = @($python.Prefix + @('-m', 'PyInstaller'))
                }
            }
        }
        catch {
        }
    }

    if (Get-Command pyinstaller -ErrorAction SilentlyContinue) {
        return [pscustomobject]@{
            Exe    = 'pyinstaller'
            Prefix = @()
        }
    }

    return $null
}

function Clean-PreviousArtifacts {
    Write-Host '[1/4] Cleaning previous build artifacts...' -ForegroundColor Yellow
    $procNames = @(
        'cropsentinel-agent-native',
        'cropsentinel-agent-service',
        'cropsentinel-agent',
        'agent'
    )
    foreach ($name in $procNames) {
        Get-Process -Name $name -ErrorAction SilentlyContinue | ForEach-Object {
            try {
                Stop-Process -Id $_.Id -Force -ErrorAction Stop
                Write-Host "Stopped process $($_.ProcessName) (PID $($_.Id))" -ForegroundColor DarkYellow
            } catch {
                Write-Host "Could not stop process $($_.ProcessName) (PID $($_.Id)): $($_.Exception.Message)" -ForegroundColor DarkYellow
            }
        }
    }
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue `
        dist, build, `
        cropsentinel-agent-*.exe, cropsentinel-agent-*.zip
}

function New-PayloadManifest {
    param(
        [Parameter(Mandatory = $true)]
        [string] $PayloadRoot,
        [Parameter(Mandatory = $true)]
        [string] $ManifestPath
    )

    $root = (Resolve-Path $PayloadRoot).Path
    $entries = Get-ChildItem -Path $root -Recurse -File | Where-Object {
        $_.Name -ne $PayloadManifestName
    } | ForEach-Object {
        $relativePath = $_.FullName.Substring($root.Length).TrimStart('\').Replace('\', '/')
        [pscustomobject]@{
            path   = $relativePath
            sha256 = (Get-FileHash -Algorithm SHA256 -Path $_.FullName).Hash.ToLowerInvariant()
            size   = $_.Length
        }
    }

    $manifest = [pscustomobject]@{
        version      = $Version
        generated_at = (Get-Date).ToUniversalTime().ToString('o')
        files        = $entries
    }

    $manifest | ConvertTo-Json -Depth 4 | Set-Content -Path $ManifestPath -Encoding UTF8
}

$pyinstallerCmd = Find-PyInstaller
if (-not $pyinstallerCmd) {
    Write-Error 'pyinstaller not found. Run: pip install pyinstaller'
    exit 1
}
Write-Host "Using: $($pyinstallerCmd.Exe) $($pyinstallerCmd.Prefix -join ' ')" -ForegroundColor DarkGray

if (-not (Test-Path $AppIcon)) {
    Write-Error "Expected Windows app icon at $AppIcon"
    exit 1
}

Clean-PreviousArtifacts
Remove-Item -Force -ErrorAction SilentlyContinue `
    (Join-Path $PortalInstallersDir 'cropsentinel-agent-*.exe'), `
    (Join-Path $PortalInstallersDir 'cropsentinel-agent-*.zip')

Write-Host '[2/4] Publishing native agent payload...' -ForegroundColor Yellow
& powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'build-native-aot.ps1')
if ($LASTEXITCODE -ne 0) {
    Write-Error "Native publish failed with exit code $LASTEXITCODE"
    exit 1
}

$agentBundleDir = Join-Path $RepoRoot 'agent\native\publish\win-x64'
$agentExe = Join-Path $agentBundleDir 'cropsentinel-agent-native.exe'
$agentServiceExe = Join-Path $agentBundleDir 'cropsentinel-agent-service.exe'
if (-not (Test-Path $agentExe)) {
    Write-Error "Native publish finished but $agentExe is missing."
    exit 1
}
if (-not (Test-Path $agentServiceExe)) {
    Write-Error "Native publish finished but $agentServiceExe is missing."
    exit 1
}

$payloadManifestPath = Join-Path $agentBundleDir $PayloadManifestName
Write-Host 'Generating payload integrity manifest...' -ForegroundColor DarkGray
New-PayloadManifest -PayloadRoot $agentBundleDir -ManifestPath $payloadManifestPath

Write-Host '[3/4] Building the standalone installer EXE...' -ForegroundColor Yellow
$installerArgs = @(
    '--noconfirm'
    '--onefile'
    '--windowed'
    '--uac-admin'
    '--clean'
    '--noupx'
    '--name', $InstallerBaseName
    '--distpath', (Join-Path $PSScriptRoot 'dist\setup')
    '--workpath', (Join-Path $PSScriptRoot 'build\installer')
    '--specpath', $PSScriptRoot
    '--icon', $AppIcon
    '--add-data', "$agentBundleDir;cropsentinel-agent"
    '--add-data', "$(Join-Path $PSScriptRoot 'config.env.example');."
    '--add-data', "$AppIcon;."
    (Join-Path $PSScriptRoot 'bootstrapper.py')
)
& $pyinstallerCmd.Exe @($pyinstallerCmd.Prefix + $installerArgs)
if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller installer build failed with exit code $LASTEXITCODE"
    exit 1
}

$installerFull = Join-Path $PSScriptRoot "dist\setup\$InstallerName"
if (-not (Test-Path $installerFull)) {
    Write-Error "PyInstaller finished but $installerFull is missing."
    exit 1
}

Write-Host '[4/4] Packaging portal ZIP bundle...' -ForegroundColor Yellow
New-Item -ItemType Directory -Path $PortalInstallersDir -Force | Out-Null
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $BundleDir
New-Item -ItemType Directory -Path $BundleDir -Force | Out-Null

Copy-Item $installerFull -Destination $BundleDir -Force
Copy-Item (Join-Path $PSScriptRoot 'config.env.example') -Destination $BundleDir -Force

$bundleReadme = @"
CropSentinel Agent installation bundle

Files in this folder:
  - $InstallerName
  - config.env.example

How to use:
  1. For portal downloads, use the tenant-specific config.env that is already included.
  2. For manual testing, copy config.env.example to config.env and edit the values.
  3. Double-click the EXE and follow the consent/install wizard.
  4. The installer will copy the agent binaries, write config.env, harden ACLs,
     and create the machine-level Windows services automatically.

This bundle is generic. The portal download endpoint will generate a tenant-
specific config.env for the selected tenant.
"@
Set-Content -Path (Join-Path $BundleDir 'README.txt') -Value $bundleReadme -Encoding ASCII

$bundleZip = Join-Path $PortalInstallersDir $BundleName
Remove-Item -Force -ErrorAction SilentlyContinue $bundleZip
Compress-Archive -Path (Join-Path $BundleDir '*') -DestinationPath $bundleZip -Force
Copy-Item $installerFull -Destination $PortalInstallersDir -Force

$size = [math]::Round((Get-Item $installerFull).Length / 1MB, 1)
Write-Host ''
Write-Host '=== Build complete ===' -ForegroundColor Green
Write-Host "Output : $installerFull  ($size MB)" -ForegroundColor Green
Write-Host "Bundle : $bundleZip" -ForegroundColor Green
Write-Host ''
Write-Host 'The installer EXE was also copied into backend\dist\installers for the' -ForegroundColor Cyan
Write-Host "platform portal's 'Download Agent Bundle' endpoint." -ForegroundColor Cyan
Write-Host ''
