#!/usr/bin/env python3
"""CI release gate: the published snapshot must be derived, and must pass.

`/eval` shows a verdict computed from `apps/web/src/data/eval-summary.json`, but
nothing that could fail a build ever looked at it — a failing snapshot would have
shipped with a red banner, and a hand-edited number would have shipped as green.
This makes the gate a check rather than a display. Two parts:

1. **Derived, not written.** The summary is rebuilt from `data/eval-runs/` with
   `build_eval_summary.build()` and must equal the committed file. Editing a
   number on the page without a run behind it fails here.
2. **Passing.** The release block is evaluated against
   `apps/web/src/data/release-gate.json` — the same thresholds the page uses.

What it does not do: rerun the evaluation. A generation run costs model calls
and about forty minutes, so it is run before a release (`ahr rag-eval`) and its
output committed; this checks what was committed.

    python scripts/check_release_gate.py
    python scripts/check_release_gate.py --summary other.json   # skip part 1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "apps" / "web" / "src" / "data" / "eval-summary.json"
GATE = ROOT / "apps" / "web" / "src" / "data" / "release-gate.json"


def evaluate(release: dict[str, Any], gate: dict[str, Any]) -> list[tuple[str, bool, str]]:
    """Each condition the page's `releasePassed` checks, with what it measured."""
    retrieval, generation = release["retrieval"], release["generation"]
    causes = generation.get("over_refusal_causes") or {}
    pipeline_causes = sorted(c for c in causes if c not in gate["stochastic_refusal_causes"])
    checks = [
        (
            "Recall@20",
            retrieval["recall@20"] >= gate["recall_at_20_min"],
            f"{retrieval['recall@20']:.4f} >= {gate['recall_at_20_min']}",
        ),
        (
            "citation coverage",
            generation["citation_coverage"] >= gate["citation_coverage_min"],
            f"{generation['citation_coverage']:.4f} >= {gate['citation_coverage_min']}",
        ),
        (
            "passage support",
            generation["support_supported"] >= gate["support_supported_min"],
            f"{generation['support_supported']:.4f} >= {gate['support_supported_min']}",
        ),
        (
            "false-premise assertions",
            generation["presupposition_asserted_rate"] <= gate["presupposition_asserted_rate_max"],
            f"{generation['presupposition_asserted_rate']} <= "
            f"{gate['presupposition_asserted_rate_max']}",
        ),
        (
            "over-refusal",
            generation["over_refusal_rate"] <= gate["over_refusal_rate_max"],
            f"{generation['over_refusal_rate']:.4f} <= {gate['over_refusal_rate_max']}",
        ),
        (
            "no pipeline-caused refusal",
            not pipeline_causes,
            ", ".join(pipeline_causes) or "only model-side causes",
        ),
    ]
    if gate.get("specialist_must_pass"):
        checks.append(
            (
                "specialist recall",
                bool(release["specialist"]["passed"]),
                f"entity Recall@20 {release['specialist']['entityRecall20']}",
            )
        )
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, help="check this file; skips the rebuild check")
    args = parser.parse_args(argv)

    ok = True
    if args.summary is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import build_eval_summary

        rebuilt = json.dumps(build_eval_summary.build(), ensure_ascii=False, indent=2) + "\n"
        committed = SUMMARY.read_text(encoding="utf-8").replace("\r\n", "\n")
        if rebuilt != committed:
            print(
                "FAIL eval-summary.json is not what data/eval-runs produces; "
                "run `python scripts/build_eval_summary.py` and commit the result"
            )
            ok = False
        else:
            print("ok   eval-summary.json matches data/eval-runs")
        summary = json.loads(committed)
    else:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))

    gate = json.loads(GATE.read_text(encoding="utf-8"))
    release = summary["release"]
    print(f"release snapshot: generation {release['generationRunId']}, "
          f"retrieval {release['retrievalRunId']}, specialist {release['specialistRunId']}")
    for name, passed, detail in evaluate(release, gate):
        print(f"{'ok  ' if passed else 'FAIL'} {name}: {detail}")
        ok = ok and passed

    print("RELEASE GATE PASSED" if ok else "RELEASE GATE FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
