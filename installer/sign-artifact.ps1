param(
    [Parameter(Mandatory = $true)]
    [string] $ArtifactPath,
    [Parameter(Mandatory = $true)]
    [string] $CertificateBase64,
    [Parameter(Mandatory = $true)]
    [string] $CertificatePassword,
    [string] $TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    $kitsRoot = "C:\Program Files (x86)\Windows Kits\10\bin"
    if (-not (Test-Path $kitsRoot)) {
        throw "signtool.exe was not found and Windows SDK is not installed."
    }

    $candidate = Get-ChildItem -Path $kitsRoot -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\signtool\.exe$" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1

    if (-not $candidate) {
        throw "signtool.exe was not found under $kitsRoot"
    }

    return $candidate.FullName
}

if (-not (Test-Path $ArtifactPath)) {
    throw "Artifact not found: $ArtifactPath"
}

$signTool = Find-SignTool
$certPath = Join-Path $env:RUNNER_TEMP "codesign-cert.pfx"
[IO.File]::WriteAllBytes($certPath, [Convert]::FromBase64String($CertificateBase64))

try {
    & $signTool sign `
        /fd SHA256 `
        /td SHA256 `
        /tr $TimestampUrl `
        /f $certPath `
        /p $CertificatePassword `
        $ArtifactPath

    if ($LASTEXITCODE -ne 0) {
        throw "signtool.exe failed with exit code $LASTEXITCODE"
    }
}
finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $certPath
}
