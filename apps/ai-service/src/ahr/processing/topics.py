"""Topic normalisation against the controlled vocabulary.

AHR-DATA-300 §7 requires extracted labels to be normalised through an alias
dictionary before storage. Without that step the LLM invents a new slug for
every phrasing ("retrieval-augmented-generation", "RAG", "rag-pipeline") and the
topic pages fragment into near-duplicates.

`config/taxonomy.yaml` is the authority: a slug that cannot be mapped onto it is
dropped rather than silently creating a new topic.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import yaml

DEFAULT_TAXONOMY_PATH = Path("/app/config/taxonomy.yaml")

# Common phrasings the model returns for canonical topics. Keys are compared
# after slug normalisation, so "Retrieval Augmented Generation" and
# "retrieval_augmented_generation" both resolve here.
ALIASES = {
    "retrieval_augmented_generation": "rag",
    "retrieval": "rag",
    "vector_search": "rag",
    "agents": "agent",
    "agentic": "agent",
    "ai_agent": "agent",
    "tool_use": "agent",
    "large_language_model": "llm",
    "language_model": "llm",
    "llms": "llm",
    "foundation_model": "llm",
    "model_context_protocol": "mcp",
    "vision": "multimodal",
    "vlm": "multimodal",
    "text_to_image": "image",
    "text_to_video": "video",
    "speech": "audio",
    "tts": "audio",
    "asr": "audio",
    "finetuning": "fine_tuning",
    "sft": "fine_tuning",
    "rlhf": "fine_tuning",
    "training": "fine_tuning",
    "serving": "inference",
    "deployment": "inference",
    "quantization": "inference",
    "benchmark": "evaluation",
    "benchmarks": "evaluation",
    "eval": "evaluation",
    "alignment": "safety",
    "security": "safety",
    "guardrails": "safety",
    "monitoring": "observability",
    "tracing": "observability",
    "coding": "ai_coding",
    "code_generation": "ai_coding",
    "copilot": "ai_coding",
    "opensource": "open_source",
    "oss": "open_source",
    "investment": "funding",
    "funding_round": "funding",
    "policy": "regulation",
    "compliance": "regulation",
    "gpu": "chips",
    "hardware": "chips",
    "semiconductor": "chips",
    "paper": "research",
    "papers": "research",
    "java": "java_ai",
    "spring": "spring_ai",
    "python": "python_ai",
}


def normalize_slug(raw: str) -> str:
    """Lowercase, collapse separators, strip noise."""
    slug = re.sub(r"[^a-z0-9]+", "_", raw.strip().lower()).strip("_")
    return slug


def load_taxonomy(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, list[str]]:
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    topics: dict[str, list[str]] = document.get("topics", {})
    return topics


def load_display(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, dict[str, Any]]:
    """Read the presentation metadata for the topic map.

    Optional by design: `topics` alone is enough to normalise labels, so a
    taxonomy without this section still seeds correctly, just with slug-derived
    names.
    """
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    return {
        "groups": document.get("topic_groups", {}) or {},
        "topics": document.get("topic_display", {}) or {},
    }


def display_name(slug: str, display: dict[str, dict[str, Any]]) -> str:
    """Human-facing name, falling back to a titlecased slug.

    The fallback is deliberately kept: a slug added to `topics` without a display
    entry should still appear on the site rather than vanish.
    """
    entry = display.get("topics", {}).get(slug) or {}
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return slug.replace("_", " ").title()


def known_slugs(taxonomy: dict[str, list[str]]) -> set[str]:
    slugs = set(taxonomy.keys())
    for children in taxonomy.values():
        slugs.update(children)
    return slugs


def resolve(raw: str, vocabulary: set[str]) -> str | None:
    """Map a model-produced label onto the vocabulary, or None if unknown."""
    slug = normalize_slug(raw)
    if not slug:
        return None
    if slug in vocabulary:
        return slug
    aliased = ALIASES.get(slug)
    if aliased and aliased in vocabulary:
        return aliased
    # Singular/plural is the most common near-miss.
    if slug.endswith("s") and slug[:-1] in vocabulary:
        return slug[:-1]
    return None


def seed_topics(
    connection: Any,
    taxonomy: dict[str, list[str]],
    display: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Insert the taxonomy into the topic table, parents before children.

    Re-running this is the only way display metadata reaches the database, so
    every column it owns is refreshed on conflict. Editing a name in
    `taxonomy.yaml` and re-seeding must actually change the site.
    """
    meta = display or {"groups": {}, "topics": {}}
    groups = meta.get("groups", {})
    written = 0

    with connection.cursor() as cursor:
        for parent_slug, children in taxonomy.items():
            group = groups.get(parent_slug) or {}
            group_order = int(group.get("order", 100))

            cursor.execute(
                """
                INSERT INTO topic (id, slug, name, parent_id, description,
                                   display_group, display_order)
                VALUES (%s, %s, %s, NULL, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    display_group = EXCLUDED.display_group,
                    display_order = EXCLUDED.display_order
                RETURNING id
                """,
                (
                    uuid.uuid4(),
                    parent_slug,
                    group.get("label") or display_name(parent_slug, meta),
                    group.get("description"),
                    parent_slug,
                    group_order,
                ),
            )
            parent_id = cursor.fetchone()[0]
            written += 1

            for index, child_slug in enumerate(children):
                entry = meta.get("topics", {}).get(child_slug) or {}
                cursor.execute(
                    """
                    INSERT INTO topic (id, slug, name, parent_id, description,
                                       display_group, display_order)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE SET
                        name = EXCLUDED.name,
                        parent_id = EXCLUDED.parent_id,
                        description = EXCLUDED.description,
                        display_group = EXCLUDED.display_group,
                        display_order = EXCLUDED.display_order
                    """,
                    (
                        uuid.uuid4(),
                        child_slug,
                        display_name(child_slug, meta),
                        parent_id,
                        entry.get("description"),
                        parent_slug,
                        # Keep the taxonomy's own ordering rather than sorting by
                        # item count: the map should read the same every visit.
                        group_order * 100 + index,
                    ),
                )
                written += 1
    return written


def link_topics(
    connection: Any,
    item_id: uuid.UUID,
    labels: list[tuple[str, float]],
    vocabulary: set[str],
) -> int:
    """Attach resolved topics to an item. Unknown labels are dropped."""
    linked = 0
    with connection.cursor() as cursor:
        for raw, confidence in labels:
            slug = resolve(raw, vocabulary)
            if slug is None:
                continue
            cursor.execute("SELECT id FROM topic WHERE slug = %s", (slug,))
            row = cursor.fetchone()
            if not row:
                continue
            cursor.execute(
                """
                INSERT INTO item_topic (content_item_id, topic_id, confidence)
                VALUES (%s, %s, %s)
                ON CONFLICT (content_item_id, topic_id)
                DO UPDATE SET confidence = EXCLUDED.confidence
                """,
                (item_id, row[0], confidence),
            )
            linked += 1
    return linked
