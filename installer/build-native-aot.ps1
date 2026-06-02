$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$RepoRoot = Resolve-Path ..
$WorkerProjectPath = Join-Path $RepoRoot "agent\native\CropSentinel.AgentNative\CropSentinel.AgentNative.csproj"
$ServiceProjectPath = Join-Path $RepoRoot "agent\native\CropSentinel.AgentNativeService\CropSentinel.AgentNativeService.csproj"
$PublishDir = Join-Path $RepoRoot "agent\native\publish\win-x64"

function Find-Dotnet {
    $candidates = @(
        'dotnet',
        'C:\Program Files\dotnet\dotnet.exe',
        'C:\Program Files (x86)\dotnet\dotnet.exe'
    )

    foreach ($candidate in $candidates) {
        try {
            & $candidate --info *> $null
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        }
        catch {
        }
    }

    throw "dotnet SDK was not found. Install .NET 8 SDK and ensure dotnet is available."
}

$Dotnet = Find-Dotnet

Write-Host ""
Write-Host "=== CropSentinel Native Agent Preview Build ===" -ForegroundColor Cyan
Write-Host "Worker : $WorkerProjectPath"
Write-Host "Service: $ServiceProjectPath"
Write-Host "Output : $PublishDir"
Write-Host ""

if (-not (Test-Path $WorkerProjectPath)) {
    throw "Native worker project not found: $WorkerProjectPath"
}
if (-not (Test-Path $ServiceProjectPath)) {
    throw "Native service project not found: $ServiceProjectPath"
}

$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$linkerCandidates = @(
    "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC",
    "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
    "C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
    "C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
    "C:\Program Files (x86)\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC"
)

$hasMsvc = $false

if (Test-Path $vswhere) {
    try {
        $instancesJson = & $vswhere -products * -requires Microsoft.VisualStudio.Workload.VCTools -format json
        if ($instancesJson) {
            $instances = $instancesJson | ConvertFrom-Json
            foreach ($instance in @($instances)) {
                $vcToolsPath = Join-Path $instance.installationPath "VC\Tools\MSVC"
                if (Test-Path $vcToolsPath) {
                    $hasMsvc = $true
                    break
                }
            }
        }
    }
    catch {
    }
}

if (-not $hasMsvc) {
    foreach ($candidate in $linkerCandidates) {
        if (Test-Path $candidate) {
            $hasMsvc = $true
            break
        }
    }
}

if (-not $hasMsvc) {
    throw @"
Native AOT prerequisites are missing.
Install Visual Studio 2022 Build Tools with the Desktop development with C++ workload,
then rerun this script. The .NET SDK alone is not enough for Native AOT linking on Windows.
"@
}

Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $PublishDir
New-Item -ItemType Directory -Force -Path $PublishDir | Out-Null

& $Dotnet publish $WorkerProjectPath `
    -c Release `
    -r win-x64 `
    -o $PublishDir

if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed for native worker with exit code $LASTEXITCODE"
}

& $Dotnet publish $ServiceProjectPath `
    -c Release `
    -r win-x64 `
    -o $PublishDir

if ($LASTEXITCODE -ne 0) {
    throw "dotnet publish failed for native service with exit code $LASTEXITCODE"
}

$workerExe = Join-Path $PublishDir "cropsentinel-agent-native.exe"
$serviceExe = Join-Path $PublishDir "cropsentinel-agent-service.exe"
if (-not (Test-Path $workerExe)) {
    throw "Native worker executable missing after publish: $workerExe"
}
if (-not (Test-Path $serviceExe)) {
    throw "Native service executable missing after publish: $serviceExe"
}

Write-Host ""
Write-Host "Native worker output : $workerExe" -ForegroundColor Green
Write-Host "Native service output: $serviceExe" -ForegroundColor Green
