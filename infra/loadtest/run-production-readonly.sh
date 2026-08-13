#!/usr/bin/env sh
set -eu

# Deliberately bounded, read-only verification for the live 2C4G Compose host.
# It does not call the public domain or any paid provider and does not create
# application rows or Redis benchmark keys.
ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
COMPOSE_FILE=${COMPOSE_FILE:-$ROOT_DIR/infra/compose/docker-compose.prod.yml}
ENV_FILE=${ENV_FILE:-$ROOT_DIR/infra/compose/.env}
K6_IMAGE=${K6_IMAGE:-grafana/k6:0.55.0}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

if [ -z "${AHR_NETWORK:-}" ]; then
  WEB_CONTAINER=$(compose ps -q web)
  AHR_NETWORK=$(docker inspect -f \
    '{{range $name, $_ := .NetworkSettings.Networks}}{{$name}}{{end}}' "$WEB_CONTAINER")
fi

echo "[1/6] health"
compose ps

echo "[2/6] endpoint cache cold/hot"
compose exec -T redis redis-cli DEL ahr:rag:v1:ops-stats:30 >/dev/null
compose exec -T ai-service python -c \
  'import time,urllib.request; s=time.perf_counter(); r=urllib.request.urlopen("http://127.0.0.1:8000/rag/stats?days=30", timeout=10); r.read(); print(f"cold status={r.status} seconds={time.perf_counter()-s:.6f}")'
compose exec -T ai-service python -c \
  'import time,urllib.request; s=time.perf_counter(); r=urllib.request.urlopen("http://127.0.0.1:8000/rag/stats?days=30", timeout=10); r.read(); print(f"hot status={r.status} seconds={time.perf_counter()-s:.6f}")'

echo "[3/6] low-risk internal k6"
docker run --rm --network "$AHR_NETWORK" \
  -e PROFILE=production-safe \
  -e BASE_URL=http://web:3000 \
  -e CORE_URL=http://core-api:8080 \
  -e AI_URL=http://ai-service:8000 \
  -v "$ROOT_DIR/infra/loadtest:/scripts:ro" \
  "$K6_IMAGE" run /scripts/read-paths.js

echo "[4/6] PostgreSQL read-only components"
compose cp "$ROOT_DIR/infra/loadtest/postgres-feed.sql" postgres:/tmp/postgres-feed.sql
compose cp "$ROOT_DIR/infra/loadtest/postgres-rag-stats.sql" postgres:/tmp/postgres-rag-stats.sql
compose exec -T postgres sh -c \
  'pgbench -n -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 5 -j 2 -T 30 -f /tmp/postgres-feed.sql'
compose exec -T postgres sh -c \
  'pgbench -n -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 5 -j 2 -T 30 -f /tmp/postgres-rag-stats.sql'

echo "[5/6] Redis protocol and application-cache observations"
compose exec -T redis redis-benchmark -q -n 50000 -c 10 -t ping
compose exec -T redis redis-cli INFO stats | \
  grep -E 'keyspace_(hits|misses)|evicted_keys|expired_keys' || true
compose exec -T redis redis-cli INFO memory | \
  grep -E 'used_memory_human|maxmemory_human|maxmemory_policy|mem_fragmentation_ratio' || true
compose exec -T redis redis-cli TTL ahr:rag:v1:ops-stats:30

echo "[6/6] resource snapshot"
docker stats --no-stream --format \
  'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}'
