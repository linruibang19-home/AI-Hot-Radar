# Claude Code Entry Point

**Read [`AGENTS.md`](AGENTS.md) first — the rules live there and only there.**
This file used to carry its own overlapping copy, and the two had already
drifted: only one of them said to stop and cite both IDs when specs conflict,
and only one of them said what a final report must contain.

This repository is governed by `README.md` and `docs/spec/00-master-spec.md`.

What belongs here is only what is specific to working in this repo with Claude
Code:

- **`docs/status/current/project-status.md` is the running record** — what was built,
  what broke, what the numbers were, and which hypotheses turned out wrong. Read
  it to pick up context in a fresh session; append a section when finishing a
  piece of work.
- **Evaluation evidence is in `docs/status/eval/`.** Read the README there before
  citing a number or regenerating the site summary
  (`python scripts/build_eval_summary.py`).
- **Java tests need JDK 21.** If the host JDK is older, run them in a container —
  the command is in `README.md` under 测试.
- For ingestion tasks the machine-readable configs matter as much as the specs:
  `config/sources.yaml`, `config/ingestion-profiles.yaml`,
  `config/social-watchlist.yaml`.
