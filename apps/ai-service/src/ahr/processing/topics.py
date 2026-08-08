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
    # observability merged into inference: both are "running the model in
    # production", and it had 27 tags against inference's 364.
    "monitoring": "inference",
    "tracing": "inference",
    "observability": "inference",
    "serving_infra": "inference",
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
    # The language-ecosystem topics are gone (1, 1 and 0 tags between them);
    # what those items were actually about is writing code with AI.
    "java": "ai_coding",
    "java_ai": "ai_coding",
    "spring": "ai_coding",
    "spring_ai": "ai_coding",
    "python": "ai_coding",
    "python_ai": "ai_coding",
    "cloud_ai": "inference",
    # Embedding and reranking are RAG infrastructure, not separate subjects a
    # reader browses — 6 and 0 tags respectively.
    "embedding": "rag",
    "embeddings": "rag",
    "reranker": "rag",
    "reranking": "rag",
    # A group name is not a topic. See `known_slugs`.
    "business": "enterprise",
}


def load_vendors(path: str | Path = DEFAULT_TAXONOMY_PATH) -> list[dict[str, Any]]:
    """The curated company/model-family cards.

    Curated rather than "top N entities by frequency" because entities are
    extracted under the name that appeared, so one vendor is several rows —
    measured: `deepseek` and `deepseek-v4` are separate, as are `gpt-5.6`,
    `gpt-5.5` and `gpt-5.6-sol`. Ranking entities directly produces a wall of
    version numbers; a reader wants "what has DeepSeek been doing".
    """
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    return list(document.get("vendors") or [])


def load_content_type_display(
    path: str | Path = DEFAULT_TAXONOMY_PATH,
) -> dict[str, dict[str, Any]]:
    """Display metadata for `content_item.content_type`.

    Separate from the `content_types` list above on purpose: that list is a
    contract the LLM structuring step validates against, so adding a label there
    changes what the pipeline accepts. This only changes what the page says.
    """
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    return dict(document.get("content_type_display") or {})


def load_merges(path: str | Path = DEFAULT_TAXONOMY_PATH) -> dict[str, str | None]:
    """Retired slug -> where its historical tags go (None = drop the row).

    Read by the migration rather than applied at read time: a tag that silently
    resolves differently every time it is displayed is not a record of what was
    judged.
    """
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    return dict(document.get("topic_merges") or {})


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
    """The slugs an extracted label may resolve to — **leaves only**.

    Group keys used to be included, and the result was 23 items tagged
    `business`: a bucket the topic map renders as a section heading, not a card,
    so those items were reachable from nowhere. A parent in the hierarchy is a
    place to put topics, not a topic.
    """
    slugs: set[str] = set()
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


def seed_vendors(connection: Any, vendors: list[dict[str, Any]]) -> int:
    """Write the curated company/model-family cards and their entity members.

    Full replace of the membership rows rather than an upsert: removing a slug
    from the list in `taxonomy.yaml` must actually remove it from the card, and
    an upsert-only path would leave the old member behind counting items
    forever. The vendor rows themselves are upserted so a renamed card keeps
    its slug and therefore its URL.
    """
    written = 0
    with connection.cursor() as cursor:
        for order, vendor in enumerate(vendors):
            slug = str(vendor.get("slug") or "").strip()
            if not slug:
                continue
            cursor.execute(
                """
                INSERT INTO vendor (slug, name, description, display_order)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (slug) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    display_order = EXCLUDED.display_order
                """,
                (slug, vendor.get("name") or slug, vendor.get("description"), order),
            )
            cursor.execute("DELETE FROM vendor_entity WHERE vendor_slug = %s", (slug,))
            # Lower-cased and trimmed, *not* `normalize_slug`. These are joined
            # against `entity.slug`, which is minted elsewhere and keeps hyphens
            # and dots: `hugging-face`, `gpt-5.6`, `claude-opus-5`. Running them
            # through the topic normaliser turns those into `hugging_face` and
            # `gpt_5_6`, which match nothing — measured as Hugging Face showing
            # 32 items against the 156 its entity actually has.
            members = {str(e).strip().lower() for e in (vendor.get("entities") or [])}
            for member in sorted(m for m in members if m):
                cursor.execute(
                    "INSERT INTO vendor_entity (vendor_slug, entity_slug) VALUES (%s, %s)"
                    " ON CONFLICT DO NOTHING",
                    (slug, member),
                )
            written += 1
    return written


def seed_content_types(connection: Any, display: dict[str, dict[str, Any]]) -> int:
    """Write the display metadata for `content_item.content_type`."""
    written = 0
    with connection.cursor() as cursor:
        for key, entry in display.items():
            cursor.execute(
                """
                INSERT INTO content_type_meta (content_type, name, description, display_order)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (content_type) DO UPDATE SET
                    name = EXCLUDED.name,
                    description = EXCLUDED.description,
                    display_order = EXCLUDED.display_order
                """,
                (
                    key,
                    entry.get("name") or key,
                    entry.get("description"),
                    int(entry.get("order", 100)),
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
