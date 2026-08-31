$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$zipPath = Join-Path $projectRoot "runtime\build\Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-Dungeon-Version-B-DAT-Set.zip"
$expected = "0e14fdb102c58aa45ab3944ac8ede99eadb12ec6cfc2e971dedf2f43b1b1cb2a"

if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw "V20U ZIP not found: $zipPath"
}

$actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "V20U SHA-256 mismatch. Expected $expected but found $actual"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($archive.Entries.Count -eq 0) {
        throw "V20U ZIP contains no entries."
    }
    if ($archive.Entries.FullName -notcontains "Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-Dungeon-Version-B-DAT-Set/CGA4K20.COM") {
        throw "V20U ZIP is missing CGA4K20.COM."
    }
    if ($archive.Entries.FullName -notcontains "Prince-1.3-New-CGA-V20-Shared-P0-P2-Sword-Dungeon-Version-B-DAT-Set/P4KX20.EXE") {
        throw "V20U ZIP is missing P4KX20.EXE."
    }
    Write-Host "V20U ZIP verified: $($archive.Entries.Count) entries; SHA-256 $actual" -ForegroundColor Green
} finally {
    $archive.Dispose()
}
