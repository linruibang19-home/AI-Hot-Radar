[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Apply,
    [switch]$IncludeBuildOutputs
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

# Only directories whose contents can be recreated from tracked source are
# allowed here. Dependency environments and user/runtime data are deliberately
# absent: .venv, node_modules, .env, Docker volumes, fixtures and eval evidence.
$cacheNames = @(
    '.pytest_cache',
    '.ruff_cache',
    '.mypy_cache',
    '__pycache__'
)
$cacheFilePatterns = @('*.tsbuildinfo', '.coverage', 'coverage.xml')

if ($IncludeBuildOutputs) {
    $cacheNames += @('.next', 'target', 'test-results', 'playwright-report')
}

$allTargets = @(Get-ChildItem -LiteralPath $repositoryRoot -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $cacheNames -contains $_.Name -and
        $_.FullName -notlike '*\node_modules\*' -and
        $_.FullName -notlike '*\.venv\*' -and
        $_.FullName -notlike '*\venv\*'
    } |
    Sort-Object FullName -Unique)

# If a build output contains another allowlisted directory (for example
# `.next/standalone/.next`), delete only the outermost target. This keeps a
# later Resolve-Path from touching a child that its parent already removed.
$targets = @($allTargets | Where-Object {
    $candidate = $_
    -not ($allTargets | Where-Object {
        $_.FullName -ne $candidate.FullName -and
        $candidate.FullName.StartsWith(($_.FullName.TrimEnd('\') + '\'), [StringComparison]::OrdinalIgnoreCase)
    } | Select-Object -First 1)
})

$fileTargets = @(Get-ChildItem -LiteralPath $repositoryRoot -File -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $file = $_
        ($cacheFilePatterns | Where-Object { $file.Name -like $_ } | Select-Object -First 1) -and
        $file.FullName -notlike '*\node_modules\*' -and
        $file.FullName -notlike '*\.venv\*' -and
        $file.FullName -notlike '*\venv\*'
    } |
    Sort-Object FullName -Unique)

$rows = @(foreach ($target in $targets) {
    $bytes = (Get-ChildItem -LiteralPath $target.FullName -File -Recurse -Force -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum
    if ($null -eq $bytes) {
        $bytes = 0
    }
    [PSCustomObject]@{
        Path = $target.FullName.Substring($repositoryRoot.Length + 1)
        Bytes = [int64]$bytes
    }
})
foreach ($target in $fileTargets) {
    $rows += [PSCustomObject]@{
        Path = $target.FullName.Substring($repositoryRoot.Length + 1)
        Bytes = [int64]$target.Length
    }
}

if (-not $Apply) {
    Write-Output 'Dry run only. Re-run with -Apply to delete the allowlisted directories.'
    $rows | Format-Table -AutoSize
    $total = ($rows | Measure-Object -Property Bytes -Sum).Sum
    if ($null -eq $total) {
        $total = 0
    }
    Write-Output ("Targets: {0}; reclaimable: {1:N2} MiB" -f @($rows).Count, ($total / 1MB))
    exit 0
}

foreach ($target in $targets) {
    # Resolve again immediately before deletion and prove that the target is a
    # descendant of this repository. Never delete a computed broad path.
    $resolved = (Resolve-Path -LiteralPath $target.FullName).Path
    $prefix = $repositoryRoot.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete a path outside the repository: $resolved"
    }
    if ($PSCmdlet.ShouldProcess($resolved, 'Remove regenerable cache directory')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

foreach ($target in $fileTargets) {
    $resolved = (Resolve-Path -LiteralPath $target.FullName).Path
    $prefix = $repositoryRoot.TrimEnd('\') + '\'
    if (-not $resolved.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to delete a path outside the repository: $resolved"
    }
    if ($PSCmdlet.ShouldProcess($resolved, 'Remove regenerable cache file')) {
        Remove-Item -LiteralPath $resolved -Force
    }
}

Write-Output ("Deleted {0} allowlisted cache directories and {1} cache files." -f $targets.Count, $fileTargets.Count)
