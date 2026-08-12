#!/usr/bin/env python3
"""Validate the repository's documentation structure and local Markdown links."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")

REQUIRED_HANDBOOK = [
    "README.md",
    *[f"{index:02d}-{slug}.md" for index, slug in enumerate(
        [
            "product-and-business",
            "end-to-end-flows",
            "runtime-and-services",
            "data-model-and-state",
            "source-ingestion",
            "content-story-selection",
            "reports-and-email",
            "rag-indexing-and-retrieval",
            "rag-generation-and-citations",
            "rag-evaluation",
            "java-core-api",
            "python-ai-service",
            "nextjs-web",
            "deployment-security-ops",
            "testing-tradeoffs-roadmap",
        ],
        start=1,
    )],
]

REQUIRED_INTERVIEW = [
    "README.md",
    "00-project-one-pager.md",
    "01-business-and-architecture.md",
    "02-ingestion-and-data-model.md",
    "03-rag-deep-dive.md",
    "04-backend-and-consistency.md",
    "05-frontend-product.md",
    "06-deployment-security-ops.md",
    "07-interview-question-bank.md",
    "08-resume-and-star-stories.md",
    "09-system-design-whiteboard.md",
    "10-demo-script.md",
    "11-code-walkthrough.md",
    "12-fourteen-day-study-plan.md",
]


def markdown_files() -> list[Path]:
    roots = [ROOT / "README.md", ROOT / "docs"]
    files: list[Path] = []
    for root in roots:
        if root.is_file():
            files.append(root)
        else:
            files.extend(root.rglob("*.md"))
    return sorted(files)


def local_target(raw_target: str) -> str | None:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        # Drop an optional Markdown title: (path "title"). Repository paths do
        # not contain spaces; escaped spaces remain valid after unquoting.
        target = target.split(maxsplit=1)[0]
    target = unquote(target.split("#", 1)[0].replace("\\ ", " "))
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    return target


def validate_links(files: list[Path], errors: list[str]) -> int:
    checked = 0
    for source in files:
        text = source.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = local_target(match.group("target"))
            if target is None:
                continue
            checked += 1
            destination = (
                ROOT / target.lstrip("/")
                if target.startswith("/")
                else source.parent / target
            )
            if not destination.resolve().exists():
                relative_source = source.relative_to(ROOT).as_posix()
                errors.append(f"broken local link: {relative_source} -> {target}")
    return checked


def require_files(directory: str, expected: list[str], errors: list[str]) -> None:
    base = ROOT / directory
    for name in expected:
        if not (base / name).is_file():
            errors.append(f"missing required documentation: {directory}/{name}")


def require_fact(relative: str, required: list[str], forbidden: list[str], errors: list[str]) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    for phrase in required:
        if phrase not in text:
            errors.append(f"{relative} is missing current fact: {phrase}")
    for phrase in forbidden:
        if phrase in text:
            errors.append(f"{relative} contains superseded current fact: {phrase}")


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    require_files("docs/handbook", REQUIRED_HANDBOOK, errors)
    require_files("docs/interview", REQUIRED_INTERVIEW, errors)
    checked_links = validate_links(files, errors)

    require_fact(
        "docs/spec/00-master-spec.md",
        ["ADR-007/0028", "ADR-009/0029"],
        [],
        errors,
    )
    require_fact(
        "docs/spec/02-system-architecture.md",
        ["Python Scheduler", "PostgreSQL"],
        ["Nginx/HTTPS", 'OUTBOX["Outbox Publisher"]'],
        errors,
    )
    require_fact(
        "docs/spec/11-end-to-end-runbook.md",
        ["Python Scheduler", "Python Pipeline"],
        ["Java Scheduler", "outbox 驱动"],
        errors,
    )
    require_fact(
        "README.md",
        ["Python 884", "docs/handbook/README.md"],
        [],
        errors,
    )

    if errors:
        print("DOC VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("DOC VALIDATION PASSED")
    print(f"markdown_files={len(files)} local_links={checked_links}")
    print(f"handbook_files={len(REQUIRED_HANDBOOK)} interview_files={len(REQUIRED_INTERVIEW)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
