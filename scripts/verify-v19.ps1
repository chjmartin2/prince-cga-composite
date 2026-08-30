$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$zipPath = Join-Path $projectRoot "runtime\build\Prince-1.3-New-CGA-Phase-Aware-V19-PHASE3-All-219-KID-Dungeon-Version-B-DAT-Set.zip"
$expected = "864cd0f9147549f37d5d4c01b4c36b96512e32c7b599520b398d0500b370973a"

if (-not (Test-Path $zipPath)) {
    throw "V19K ZIP not found: $zipPath"
}

$actual = (Get-FileHash -Algorithm SHA256 $zipPath).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "V19K SHA-256 mismatch. Expected $expected but found $actual"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($archive.Entries.Count -eq 0) {
        throw "V19K ZIP contains no entries."
    }
    Write-Host "V19K ZIP verified: $($archive.Entries.Count) entries; SHA-256 $actual" -ForegroundColor Green
} finally {
    $archive.Dispose()
}

