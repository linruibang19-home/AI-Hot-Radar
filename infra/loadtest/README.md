# Local layered load test

This folder measures the local Docker Compose stack without turning a developer
laptop into a claim about the production 2C4G host. It never targets the public
domain by default and the standard profile does not call an LLM, embedding or
reranking provider. The Python leg reads `/rag/stats`, so it exercises the RAG
service's local PostgreSQL/control path without generating an answer.

Run from the repository root after the local stack is healthy:

```powershell
docker compose -f infra/compose/docker-compose.yml ps
docker run --rm `
  -e BASE_URL=http://host.docker.internal:3000 `
  -e CORE_URL=http://host.docker.internal:8080 `
  -e AI_URL=http://host.docker.internal:8000 `
  -v "${PWD}/infra/loadtest:/scripts:ro" `
  grafana/k6:0.55.0 run /scripts/read-paths.js
```

On Linux use the Compose network rather than host networking:

```bash
docker run --rm --network ai-hot-radar_default \
  -e BASE_URL=http://web:3000 -e CORE_URL=http://core-api:8080 \
  -e AI_URL=http://ai-service:8000 \
  -v "$PWD/infra/loadtest:/scripts:ro" grafana/k6:0.55.0 \
  run /scripts/read-paths.js
```

The baseline profile uses four stages: warm-up, ten virtual users, twenty
virtual users, then ramp-down. `PROFILE=smoke` performs a short two-user
validation. Add a separately named profile to the versioned script rather than
silently overriding the stages, so every reported result stays reproducible.

Database and Redis are measured separately so an HTTP result is not falsely
attributed to a single component:

```powershell
docker compose -f infra/compose/docker-compose.yml exec -T postgres `
  pg_isready -U ai_hot_radar -d ai_hot_radar
docker compose -f infra/compose/docker-compose.yml cp `
  infra/loadtest/postgres-feed.sql postgres:/tmp/postgres-feed.sql
docker compose -f infra/compose/docker-compose.yml exec -T postgres `
  pgbench -U ai_hot_radar -d ai_hot_radar -c 10 -j 2 -T 30 `
  -f /tmp/postgres-feed.sql
docker compose -f infra/compose/docker-compose.yml exec -T redis `
  redis-benchmark -q -n 100000 -c 20 -t ping
```

`postgres-feed.sql` is a read-only representative query, so the reported TPS is
the database throughput of that one query shape. The Redis command uses PING
only: it measures the local connection/event-loop ceiling without inserting
benchmark keys into the application's cache. Neither number is end-to-end QPS.

The full procedure, SQL inspection and interpretation are documented in
`docs/handbook/18-performance-capacity-and-load-testing.md`.
