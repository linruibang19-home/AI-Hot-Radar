# Claude Code Entry Point

This repository is governed by `README.md` and `docs/00-master-spec.md`.

Before implementation:

1. Identify the active task ID from `docs/08-roadmap-ai-ide.md`.
2. Read the corresponding domain spec and machine-readable config.
3. Inspect the repository and existing tests.
4. Propose a compact plan with files and validation commands, then implement.

Do not replace locked architecture, broaden milestones, bypass source policies, or treat LLM output as trusted facts. If specifications conflict, stop and cite both document IDs. Final output must include changed files, test evidence, remaining risks, and the next task card.

For ingestion tasks, also read `docs/09-source-registry-fulltext.md`, `docs/10-source-adapter-implementation.md`, `config/sources.yaml`, `config/ingestion-profiles.yaml`, and `config/social-watchlist.yaml`. A feed/search excerpt is discovery metadata, not full text.
