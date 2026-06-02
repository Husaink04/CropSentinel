$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$project = Join-Path $PSScriptRoot "CropSentinel.AgentNative\CropSentinel.AgentNative.csproj"

Write-Host ""
Write-Host "=== CropSentinel Native Agent Build ===" -ForegroundColor Cyan
Write-Host "Project: $project"
Write-Host ""

dotnet publish $project -c Release
