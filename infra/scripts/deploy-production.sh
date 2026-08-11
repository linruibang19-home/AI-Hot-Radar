#!/bin/sh
# Deterministic first/repeat deploy. Run only on the target Linux host after
# DNS, firewall, provider caps and infra/compose/.env are ready.

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
COMPOSE_FILE="$REPO_ROOT/infra/compose/docker-compose.prod.yml"
ENV_FILE=${AHR_ENV_FILE:-"$REPO_ROOT/infra/compose/.env"}

"$SCRIPT_DIR/preflight.sh" "$ENV_FILE"

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
	echo "deploy ERROR: checkout has uncommitted changes" >&2
	exit 1
fi

head_sha=$(git -C "$REPO_ROOT" rev-parse HEAD)
image_tag=$(awk -F= '$1 == "IMAGE_TAG" { sub(/^[^=]*=/, ""); found=$0 } END { print found }' "$ENV_FILE")
if [ "$image_tag" != "sha-$head_sha" ]; then
	echo "deploy ERROR: IMAGE_TAG does not match checkout HEAD" >&2
	exit 1
fi

export AHR_ENV_FILE="$ENV_FILE"
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" pull
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d \
	--remove-orphans --wait --wait-timeout 240

public_base=$(awk -F= '$1 == "PUBLIC_BASE_URL" { sub(/^[^=]*=/, ""); found=$0 } END { print found }' "$ENV_FILE")
"$SCRIPT_DIR/smoke-production.sh" "$public_base"

echo "deploy OK: sha=$head_sha"
echo "next: verify backup logs, run restore-verify, then restrict origin ingress to Cloudflare ranges"
