$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$packageName = "Prince-1.3-New-CGA-V20X-Floor-Overlay-Occlusion"
$sourcePath = Join-Path $projectRoot "runtime\build\$packageName"
$targetPath = "C:\DOS\POP_CP"
$expectedExeHash = "65bf68df56af4a69c529debda085a66ca57447b144555ddc83ffcf9c11aaab5c"
$expectedComHash = "3be21aa08ec9f1acaad2085cfc97a2053a11126e4df5c4e66ae94e5e9c80c57f"
$expectedTitleHash = "56e8fadd3b418bf2b73c2ca3233535fa936a8a910e8d253790f7b4af7fa04b62"
$expectedCDungeonHash = "1466914150b8f66494240e20486b236d3b7b648ec0a3d1cbb093223614569a14"

if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) {
    throw "V20X package directory not found: $sourcePath"
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
    throw "Unexpected V20X package identity: $($manifest.package)"
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
    "P4KX2X.EXE" = $expectedExeHash
    "CGA4K2X.COM" = $expectedComHash
    "TITLE.DAT" = $expectedTitleHash
    "CDUNGEON.DAT" = $expectedCDungeonHash
}
foreach ($relative in $requiredHashes.Keys) {
    $actual = (Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $requiredHashes[$relative]) {
        throw "V20X required-file hash mismatch: $relative"
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
    throw "DOSBox deployment file count differs from V20X package."
}
foreach ($relative in $sourceFiles.Keys) {
    if (-not $targetFiles.ContainsKey($relative)) {
        throw "DOSBox deployment is missing: $relative"
    }
    if ($targetFiles[$relative] -ne $sourceFiles[$relative]) {
        throw "DOSBox deployment hash mismatch: $relative"
    }
}

Write-Host "V20X installed exactly to $resolvedTarget" -ForegroundColor Green
Write-Host "$($targetFiles.Count) files verified; run CGA4K2X.COM in DOSBox." -ForegroundColor Green
