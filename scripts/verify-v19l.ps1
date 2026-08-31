$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$zipPath = Join-Path $projectRoot "runtime\build\Prince-1.3-New-CGA-Phase-Aware-V19L-HP-Absolute-Phase-Fix-Dungeon-Version-B-DAT-Set.zip"
$expected = "b133c33e243c8695be96973a3b9eda3ff7e78a51c0fec0c97d55df1dd545ba5b"

if (-not (Test-Path $zipPath)) {
    throw "V19L ZIP not found: $zipPath"
}

$actual = (Get-FileHash -Algorithm SHA256 $zipPath).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "V19L SHA-256 mismatch. Expected $expected but found $actual"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($archive.Entries.Count -eq 0) {
        throw "V19L ZIP contains no entries."
    }
    Write-Host "V19L ZIP verified: $($archive.Entries.Count) entries; SHA-256 $actual" -ForegroundColor Green
} finally {
    $archive.Dispose()
}
