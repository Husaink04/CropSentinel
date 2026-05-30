param(
    [string] $ArtifactPath,
    [string] $SourceDir,
    [Parameter(Mandatory = $true)]
    [ValidateSet("s3", "scp", "http-put")]
    [string] $Method,
    [string] $Destination,
    [string] $RemoteHost,
    [string] $Username,
    [string] $Port = "22",
    [string] $PrivateKey,
    [string] $UploadUrl
)

$ErrorActionPreference = "Stop"

if (-not $ArtifactPath -and -not $SourceDir) {
    throw "Provide either ArtifactPath or SourceDir."
}

if ($ArtifactPath -and -not (Test-Path $ArtifactPath)) {
    throw "Artifact not found: $ArtifactPath"
}

if ($SourceDir -and -not (Test-Path $SourceDir)) {
    throw "Source directory not found: $SourceDir"
}

function Get-UploadItems {
    if ($SourceDir) {
        return Get-ChildItem -Path $SourceDir -File | Sort-Object Name
    }
    return @(Get-Item -LiteralPath $ArtifactPath)
}

function Get-RunnerTempPath {
    $candidates = @(
        $env:RUNNER_TEMP,
        $env:TEMP,
        $env:TMP,
        [System.IO.Path]::GetTempPath()
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }

    foreach ($candidate in $candidates) {
        try {
            New-Item -ItemType Directory -Force -Path $candidate | Out-Null
            return (Resolve-Path -LiteralPath $candidate).Path
        }
        catch {
        }
    }

    throw "Could not resolve a writable temporary directory for the deploy key."
}

switch ($Method) {
    "s3" {
        if (-not $Destination) {
            throw "Destination is required for s3 uploads."
        }
        if ($SourceDir) {
            & aws s3 cp $SourceDir $Destination --recursive --only-show-errors
            if ($LASTEXITCODE -ne 0) {
                throw "aws s3 cp failed with exit code $LASTEXITCODE"
            }
        } else {
            & aws s3 cp $ArtifactPath $Destination --only-show-errors
            if ($LASTEXITCODE -ne 0) {
                throw "aws s3 cp failed with exit code $LASTEXITCODE"
            }
        }
    }
    "scp" {
        if (-not $RemoteHost -or -not $Username -or -not $Destination -or -not $PrivateKey) {
            throw "RemoteHost, Username, Destination, and PrivateKey are required for scp uploads."
        }
        $tempPath = Get-RunnerTempPath
        $keyPath = Join-Path $tempPath "cropsentinel_deploy_rsa"
        Set-Content -Path $keyPath -Value $PrivateKey -NoNewline -Encoding ASCII
        try {
            foreach ($item in (Get-UploadItems)) {
                & "$env:WINDIR\System32\OpenSSH\scp.exe" `
                    -i $keyPath `
                    -P $Port `
                    -o StrictHostKeyChecking=no `
                    $item.FullName `
                    "${Username}@${RemoteHost}:$Destination"
                if ($LASTEXITCODE -ne 0) {
                    throw "scp upload failed with exit code $LASTEXITCODE for $($item.Name)"
                }
            }
        }
        finally {
            Remove-Item -Force -ErrorAction SilentlyContinue $keyPath
        }
    }
    "http-put" {
        if ($SourceDir) {
            throw "http-put supports only a single ArtifactPath."
        }
        if (-not $UploadUrl) {
            throw "UploadUrl is required for http-put uploads."
        }
        Invoke-WebRequest -Method Put -Uri $UploadUrl -InFile $ArtifactPath | Out-Null
    }
}
