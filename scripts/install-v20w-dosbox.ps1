$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$packageName = "Prince-1.3-New-CGA-V20W-Amir-Title-R54-Transparency-CDungeon-WIP"
$sourcePath = Join-Path $projectRoot "runtime\build\$packageName"
$targetPath = "C:\DOS\POP_CP"
$expectedExeHash = "a90508c271823ca182df83ad63a8d5c49a9971e2df7c68f8303691e4f2a0a3e5"
$expectedComHash = "88f211da85b5055634642a42de3337f69db7834c53ed9ae1629c2181e1336646"
$expectedTitleHash = "56e8fadd3b418bf2b73c2ca3233535fa936a8a910e8d253790f7b4af7fa04b62"
$expectedCDungeonHash = "ec74b03105f47cac467e8568490aa3993bef3f1a961cbf961484bdd549b65ea4"

if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "V20W package directory not found: $sourcePath"
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
    throw "Unexpected V20W package identity: $($manifest.package)"
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
    "P4KX2W.EXE" = $expectedExeHash
    "CGA4K2W.COM" = $expectedComHash
    "TITLE.DAT" = $expectedTitleHash
    "CDUNGEON.DAT" = $expectedCDungeonHash
}
foreach ($relative in $requiredHashes.Keys) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $requiredHashes[$relative]) {
        throw "V20W required-file hash mismatch: $relative"
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
    throw "DOSBox deployment file count differs from V20W package."
}
foreach ($relative in $sourceFiles.Keys) {
    if (-not $targetFiles.ContainsKey($relative)) {
        throw "DOSBox deployment is missing: $relative"
    }
    if ($targetFiles[$relative] -ne $sourceFiles[$relative]) {
        throw "DOSBox deployment hash mismatch: $relative"
    }
}

Write-Host "V20W installed exactly to $resolvedTarget" -ForegroundColor Green
Write-Host "$($targetFiles.Count) files verified; run CGA4K2W.COM in DOSBox." -ForegroundColor Green
