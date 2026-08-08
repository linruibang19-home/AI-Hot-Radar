# AI Hot Radar Agent Instructions

**This file is the single source of these rules.** `CLAUDE.md` and
`.cursor/rules/ai-hot-radar.mdc` point here and add only what is specific to
their tool. Do not keep a second copy of a rule in either of them: all three
files used to hold overlapping rule sets and they had already begun to
disagree, which is the same "two copies of one state drift apart" failure this
project has hit repeatedly in its own code.

## Read this, in this order

1. Read `README.md` and `docs/spec/00-master-spec.md` completely before acting.
2. Read only the relevant domain spec next; do not invent requirements from memory.
3. Work on one task card from `docs/spec/08-roadmap-ai-ide.md` at a time.
4. Inspect existing files and tests before editing, then propose a compact plan
   naming the files and the validation commands, and implement that.

**If specifications conflict, stop and cite both document IDs.** Do not pick one.

## Do not change silently

5. Preserve locked ADR decisions. Record material changes in `docs/adr/` **first**.
   An ADR is required for: database/queue/search engine, service boundaries,
   authentication, RAG retrieval strategy, core data entities, and breaking
   public API changes.
6. The technology stack, core entities, API semantics and milestone boundaries
   are not yours to move.
7. **PostgreSQL is the source of truth; Redis is cache, rate limiting and
   short-lived state only** (ADR-0005).
8. Use Flyway for schema changes (`database/migrations/`) and generated
   contracts for Java/Python shared types.

## Engineering constraints

9. External calls require timeouts, bounded retries, per-host rate limits,
   idempotency and observability (trace ids).
10. **LLM output is untrusted until schema validation.** RAG facts require the
    original evidence passage — never an AI-written summary as the final evidence.
11. Preserve unrelated user changes; avoid broad refactors.
12. Keep implementation within the active milestone; list later improvements
    separately rather than pulling them forward.

## Ingestion and sources

13. Source work MUST read `docs/spec/09-source-registry-fulltext.md`. **An RSS or
    search excerpt is discovery metadata, never full text.** Social watchlist
    entries stay disabled without an authorized adapter.
14. Adapter work MUST also read `docs/spec/10-source-adapter-implementation.md`
    and `config/ingestion-profiles.yaml`; no source becomes ACTIVE without a
    replayable fixture and a fulltext gate.

## Delivery

15. Run task-specific tests and report the commands and their results. Do not
    claim completion without evidence. The final output must include: **changed
    files, test evidence, remaining risks, and the next task card.**
