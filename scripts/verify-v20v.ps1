$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$packageName = "Prince-1.3-New-CGA-V20V-Command-Tail-Sword-Dungeon-Version-B-DAT-Set"
$zipPath = Join-Path $projectRoot "runtime\build\$packageName.zip"
$expected = "c1fcf28ab2af1341025368bd4270a76368a7faf6c1dfe5c89d531eb3d50631b2"

if (-not (Test-Path -LiteralPath $zipPath -PathType Leaf)) {
    throw "V20V ZIP not found: $zipPath"
}

$actual = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) {
    throw "V20V SHA-256 mismatch. Expected $expected but found $actual"
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
try {
    if ($archive.Entries.Count -eq 0) {
        throw "V20V ZIP contains no entries."
    }
    if ($archive.Entries.FullName -notcontains "$packageName/CGA4K2V.COM") {
        throw "V20V ZIP is missing CGA4K2V.COM."
    }
    if ($archive.Entries.FullName -notcontains "$packageName/P4KX2V.EXE") {
        throw "V20V ZIP is missing P4KX2V.EXE."
    }
    Write-Host "V20V ZIP verified: $($archive.Entries.Count) entries; SHA-256 $actual" -ForegroundColor Green
} finally {
    $archive.Dispose()
}
