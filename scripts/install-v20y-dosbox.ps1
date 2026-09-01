$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$packageName = "Prince-1.3-New-CGA-V20Y-Chomper-Blood-Stencils"
$sourcePath = Join-Path $projectRoot "runtime\build\$packageName"
$targetPath = "C:\DOS\POP_CP"
$expectedExeHash = "7c557c3c844e44f01bcbb26ddc13f7ed963acd201fc4961549965a81b6bcf9dc"
$expectedComHash = "782c79cbc58ca22a94f5d51432883ab768fd8f439b686e89d4ec85b560c4f3d2"
$expectedTitleHash = "56e8fadd3b418bf2b73c2ca3233535fa936a8a910e8d253790f7b4af7fa04b62"
$expectedCDungeonHash = "b5459688c0d4618208fe6a3d233b0eaea18f51153b861195940fe940ea4d8536"

if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "V20Y package directory not found: $sourcePath"
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
    throw "Unexpected V20Y package identity: $($manifest.package)"
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

$requiredHashes = @{
    "P4KX2Y.EXE" = $expectedExeHash
    "CGA4K2Y.COM" = $expectedComHash
    "TITLE.DAT" = $expectedTitleHash
    "CDUNGEON.DAT" = $expectedCDungeonHash
}
foreach ($relative in $requiredHashes.Keys) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $requiredHashes[$relative]) {
        throw "V20Y required-file hash mismatch: $relative"
    }
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
    throw "DOSBox deployment file count differs from V20Y package."
}
foreach ($relative in $sourceFiles.Keys) {
    if (-not $targetFiles.ContainsKey($relative)) {
        throw "DOSBox deployment is missing: $relative"
    }
    if ($targetFiles[$relative] -ne $sourceFiles[$relative]) {
        throw "DOSBox deployment hash mismatch: $relative"
    }
}

Write-Host "V20Y installed exactly to $resolvedTarget" -ForegroundColor Green
Write-Host "$($targetFiles.Count) files verified; run CGA4K2Y.COM in DOSBox." -ForegroundColor Green
