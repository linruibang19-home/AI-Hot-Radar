[CmdletBinding()]
param(
    [ValidatePattern('^[1-9][0-9]*(MB|GB)$')]
    [string]$BuildCacheLimit = '5GB',

    [ValidateRange(24, 8760)]
    [int]$UnusedImageAgeHours = 168
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker CLI is not available on PATH'
}

docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Output 'Docker Desktop is not running; maintenance skipped.'
    exit 0
}

# BuildKit is the dominant growth source during repeated Compose builds. Keep
# its useful cache bounded instead of deleting all cache after every build.
docker buildx prune --force --max-used-space $BuildCacheLimit
if ($LASTEXITCODE -ne 0) {
    throw 'BuildKit cache pruning failed'
}

# Remove only images that are not referenced by a container and are older than
# the grace period. Named volumes are deliberately never pruned here because
# PostgreSQL is the source of truth.
docker image prune --all --force --filter "until=${UnusedImageAgeHours}h"
if ($LASTEXITCODE -ne 0) {
    throw 'Unused image pruning failed'
}

docker system df
