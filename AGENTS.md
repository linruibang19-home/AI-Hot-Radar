# AI Hot Radar Agent Instructions

1. Read `README.md` and `docs/00-master-spec.md` completely before acting.
2. Read only the relevant domain spec next; do not invent requirements from memory.
3. Work on one task card from `docs/08-roadmap-ai-ide.md` at a time.
4. Preserve locked ADR decisions. Record material changes in `docs/adr/` first.
5. Inspect existing files and tests before editing. Preserve unrelated user changes.
6. Use Flyway for schema changes and generated contracts for Java/Python shared types.
7. External calls require timeouts, bounded retries, host rate limits, idempotency, and observability.
8. LLM output is untrusted until schema validation. RAG facts require original evidence passages.
9. Run task-specific tests and report commands/results. Do not claim completion without evidence.
10. Keep implementation within the active milestone; list later improvements separately.
11. Source work MUST read `docs/09-source-registry-fulltext.md`; RSS/search snippets never count as full text, and social watchlist entries stay disabled without authorization.
12. Adapter work MUST also read `docs/10-source-adapter-implementation.md` and `config/ingestion-profiles.yaml`; no source becomes ACTIVE without a replayable fixture and fulltext gate.
