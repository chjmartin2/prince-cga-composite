$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$packageName = "Prince-1.3-New-CGA-Phase-Aware-V19L-HP-Absolute-Phase-Fix-Dungeon-Version-B-DAT-Set"
$sourcePath = Join-Path $projectRoot "runtime\build\$packageName"
$targetPath = "C:\DOS\POP_CP"
$expectedExeHash = "1b92a8f4138bffd58b62ecff4d56b708a733da51c1554e6fee52fdfb457b018c"
$expectedComHash = "c35bf4aa374dcbb29aa5bb514eb31ff84c6150f5524172b4a6529c655a160777"

if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "V19L package directory not found: $sourcePath"
}

$source = (Resolve-Path -LiteralPath $sourcePath).Path.TrimEnd('\')
$expectedTarget = [System.IO.Path]::GetFullPath("C:\DOS\POP_CP").TrimEnd('\')
$target = [System.IO.Path]::GetFullPath($targetPath).TrimEnd('\')
if (-not $target.Equals($expectedTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing unexpected DOSBox target: $target"
}
if ($target -eq [System.IO.Path]::GetPathRoot($target)) {
    throw "Refusing to deploy to a filesystem root."
}

$manifestPath = Join-Path $source "PACKAGE-MANIFEST.JSON"
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
if ($manifest.package -ne $packageName) {
    throw "Unexpected V19L package identity: $($manifest.package)"
}
foreach ($property in $manifest.files.PSObject.Properties) {
    $relative = $property.Name.Replace('/', '\')
    $path = Join-Path $source $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Package manifest file missing: $relative"
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $property.Value.sha256) {
        throw "Package manifest hash mismatch: $relative"
    }
}

$exeHash = (Get-FileHash -LiteralPath (Join-Path $source "P4KX1L.EXE") -Algorithm SHA256).Hash.ToLowerInvariant()
$comHash = (Get-FileHash -LiteralPath (Join-Path $source "CGA4K1L.COM") -Algorithm SHA256).Hash.ToLowerInvariant()
if ($exeHash -ne $expectedExeHash -or $comHash -ne $expectedComHash) {
    throw "V19L executable or launcher hash mismatch."
}

if (-not (Test-Path -LiteralPath $target -PathType Container)) {
    New-Item -ItemType Directory -Path $target | Out-Null
}
$resolvedTarget = (Resolve-Path -LiteralPath $target).Path.TrimEnd('\')
if (-not $resolvedTarget.Equals($expectedTarget, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Resolved DOSBox target changed unexpectedly: $resolvedTarget"
}
$targetPrefix = $resolvedTarget + '\'

foreach ($child in Get-ChildItem -LiteralPath $resolvedTarget -Force) {
    $childPath = [System.IO.Path]::GetFullPath($child.FullName)
    if (-not $childPath.StartsWith($targetPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing unsafe cleanup path: $childPath"
    }
    Remove-Item -LiteralPath $childPath -Recurse -Force
}

foreach ($child in Get-ChildItem -LiteralPath $source -Force) {
    Copy-Item -LiteralPath $child.FullName -Destination $resolvedTarget -Recurse -Force
}

$sourceFiles = @{}
foreach ($file in Get-ChildItem -LiteralPath $source -Recurse -File -Force) {
    $relative = $file.FullName.Substring($source.Length).TrimStart('\')
    $sourceFiles[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
$targetFiles = @{}
foreach ($file in Get-ChildItem -LiteralPath $resolvedTarget -Recurse -File -Force) {
    $relative = $file.FullName.Substring($resolvedTarget.Length).TrimStart('\')
    $targetFiles[$relative] = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
}
if ($sourceFiles.Count -ne $targetFiles.Count) {
    throw "DOSBox deployment file count differs from V19L package."
}
foreach ($relative in $sourceFiles.Keys) {
    if (-not $targetFiles.ContainsKey($relative)) {
        throw "DOSBox deployment is missing: $relative"
    }
    if ($targetFiles[$relative] -ne $sourceFiles[$relative]) {
        throw "DOSBox deployment hash mismatch: $relative"
    }
}

Write-Host "V19L installed exactly to $resolvedTarget" -ForegroundColor Green
Write-Host "$($targetFiles.Count) files verified; run CGA4K1L.COM in DOSBox." -ForegroundColor Green
