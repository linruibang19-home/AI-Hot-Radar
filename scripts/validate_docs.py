#!/usr/bin/env python3
"""Validate the repository's documentation structure and local Markdown links."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?P<target>[^)]+)\)")

REQUIRED_HANDBOOK = [
    "README.md",
    *[
        f"{index:02d}-{slug}.md"
        for index, slug in enumerate(
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
                "llm-prompts-ranking-and-thresholds",
                "agent-orchestration-memory-and-cost",
                "performance-capacity-and-load-testing",
                "backend-layering-runtime-and-redis",
                "ingestion-evidence-and-chunking",
                "redis-cache-and-short-lived-state",
                "rag-golden-set-and-quality-page",
            ],
            start=1,
        )
    ],
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
    "13-project-challenges-and-tradeoffs.md",
    "14-agent-rag-interview-drill.md",
    "15-performance-load-testing-interview.md",
    "16-backend-layering-runtime-interview.md",
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


def require_fact(
    relative: str, required: list[str], forbidden: list[str], errors: list[str]
) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    for phrase in required:
        if phrase not in text:
            errors.append(f"{relative} is missing current fact: {phrase}")
    for phrase in forbidden:
        if phrase in text:
            errors.append(f"{relative} contains superseded current fact: {phrase}")


def require_pattern(
    relative: str, pattern: str, description: str, errors: list[str]
) -> None:
    """Require a dated/structured fact without freezing its numeric value."""
    text = (ROOT / relative).read_text(encoding="utf-8")
    if re.search(pattern, text) is None:
        errors.append(f"{relative} is missing current fact pattern: {description}")


def current_repository_facts() -> tuple[int, str, str, str]:
    """Read cheap, deterministic facts that canonical docs are allowed to repeat."""
    registry = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    source_count = len(registry.get("sources", []))

    package = json.loads((ROOT / "apps/web/package.json").read_text(encoding="utf-8"))
    next_version = package["dependencies"]["next"]

    pom = (ROOT / "apps/core-api/pom.xml").read_text(encoding="utf-8")
    spring_match = re.search(
        r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>([^<]+)</version>",
        pom,
    )
    if spring_match is None:
        raise ValueError("cannot determine Spring Boot version from pom.xml")

    migration_names = [path.name for path in (ROOT / "database/migrations").glob("V*.sql")]
    migration_versions = [
        (int(match.group(1)), name)
        for name in migration_names
        if (match := re.match(r"V(\d+)(?:_\d+)?__", name))
    ]
    if not migration_versions:
        raise ValueError("no Flyway migrations found")
    latest_migration = f"V{max(version for version, _ in migration_versions):03d}"
    return source_count, next_version, spring_match.group(1), latest_migration


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    require_files("docs/handbook", REQUIRED_HANDBOOK, errors)
    require_files("docs/interview", REQUIRED_INTERVIEW, errors)
    checked_links = validate_links(files, errors)
    source_count, next_version, spring_version, latest_migration = current_repository_facts()

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
        ["docs/handbook/README.md", f"Next.js {next_version}", f"Spring Boot {spring_version}"],
        ["docs/status/production/"],
        errors,
    )
    # 只要求「有日期 + 声明不是实时承诺」，不锁定标题措辞。此前的正则把整句话
    # 连同 <details> 摘要一起冻住了，README 改版时校验失败的原因是措辞变了，
    # 而不是这条约束真的被违反。
    require_pattern(
        "README.md",
        r"生产数据快照（\d{4}-\d{2}-\d{2}，历史快照，非实时承诺）",
        "dated production snapshot disclaimer",
        errors,
    )
    require_fact(
        "docs/status/current/production-baseline.md",
        [
            "截至：",
            f"| 登记信源 / 允许调度 / 运行态 ACTIVE | {source_count} /",
            f"Flyway {latest_migration}",
            "不是实时承诺",
        ],
        [],
        errors,
    )
    for canonical in [
        "DEVELOPMENT.md",
        "docs/README.md",
        "docs/archive-policy.md",
        "docs/handbook/README.md",
        "docs/interview/README.md",
        "docs/spec/12-delivery-index.md",
    ]:
        require_fact(
            canonical,
            [],
            ["status/production/", "handoff-20260812.md"],
            errors,
        )
    # 曾要求 README 写死 `Python **N passed / M skipped**`。这个数字每加一条测试
    # 就过期一次，而且没有任何机制会去更新它 —— README 里那份停在 935 时，实际
    # 已经涨过好几轮。改为要求指向 CI 的实时徽章：同样是「回归套件真实存在且是
    # 绿的」这个断言，但它自己会更新，也点得进去看。
    require_pattern(
        "README.md",
        r"actions/workflows/ci\.yml/badge\.svg",
        "live CI status badge",
        errors,
    )

    if errors:
        print("DOC VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    print("DOC VALIDATION PASSED")
    print(f"markdown_files={len(files)} local_links={checked_links}")
    print(
        f"handbook_files={len(REQUIRED_HANDBOOK)} interview_files={len(REQUIRED_INTERVIEW)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
