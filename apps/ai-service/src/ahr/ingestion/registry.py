"""Source registry loading.

`config/sources.yaml` is the authority for which sources exist; code must not
hardcode site URLs, priorities or intervals (AHR-DATA-300 §4).

Loading is idempotent: it upserts by `id` and never clears runtime state such as
`runtime_state`, `last_success_at` or cursors, so re-running the loader after a
config edit does not reset a healthy source's history.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ahr.ingestion.models import SourceConfig

# AHR-SOURCE-900 §5: restricted targets stay off until an authorised adapter
# exists. This is enforced here as well as in the schema so a config edit
# cannot silently enable scraping of a login-walled platform.
RESTRICTED_VERIFICATION = "restricted"


@dataclass(frozen=True)
class RegistrySummary:
    total: int
    enabled: int
    disabled: int
    by_profile: dict[str, int]
    restricted_forced_off: list[str]


def _to_source(entry: dict[str, Any]) -> SourceConfig:
    enabled = bool(entry.get("enabled", False))
    if entry.get("verification") == RESTRICTED_VERIFICATION:
        enabled = False

    return SourceConfig(
        id=entry["id"],
        name=entry["name"],
        organization=entry.get("organization", ""),
        profile=entry["profile"],
        tier=entry.get("tier", "secondary"),
        priority=entry.get("priority", "P2"),
        content_access=entry.get("content_access", "discovery_only"),
        verification=entry.get("verification", "page_confirmed"),
        enabled=enabled,
        discovery_url=entry.get("discovery_url"),
        repository=entry.get("repository"),
        subject=entry.get("subject"),
        homepage_url=entry.get("homepage_url"),
        region=entry.get("region", "global"),
        group=entry.get("group", ""),
    )


def load_sources(path: str | Path) -> list[SourceConfig]:
    """Parse `config/sources.yaml` into SourceConfig objects."""
    with Path(path).open(encoding="utf-8") as handle:
        document = yaml.safe_load(handle)

    entries = document.get("sources", [])
    sources = [_to_source(entry) for entry in entries]

    ids = [source.id for source in sources]
    duplicates = {value for value in ids if ids.count(value) > 1}
    if duplicates:
        raise ValueError(f"duplicate source ids in registry: {sorted(duplicates)}")

    for source in sources:
        if not (source.discovery_url or source.repository or source.subject):
            raise ValueError(f"source {source.id} has no discovery_url, repository or subject")

    return sources


def summarize(sources: list[SourceConfig]) -> RegistrySummary:
    by_profile: dict[str, int] = {}
    for source in sources:
        by_profile[source.profile] = by_profile.get(source.profile, 0) + 1

    return RegistrySummary(
        total=len(sources),
        enabled=sum(1 for source in sources if source.enabled),
        disabled=sum(1 for source in sources if not source.enabled),
        by_profile=dict(sorted(by_profile.items())),
        restricted_forced_off=[
            source.id for source in sources if source.verification == RESTRICTED_VERIFICATION
        ],
    )


UPSERT_SQL = """
INSERT INTO source (
    id, name, organization, source_group, region, source_tier, priority,
    profile, homepage_url, discovery_url, repository, subject,
    content_access, verification, configured_enabled, config_version, public_render
) VALUES (
    %(id)s, %(name)s, %(organization)s, %(group)s, %(region)s, %(tier)s, %(priority)s,
    %(profile)s, %(homepage_url)s, %(discovery_url)s, %(repository)s, %(subject)s,
    %(content_access)s, %(verification)s, %(enabled)s, %(config_version)s, %(public_render)s
)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    organization = EXCLUDED.organization,
    source_group = EXCLUDED.source_group,
    region = EXCLUDED.region,
    source_tier = EXCLUDED.source_tier,
    priority = EXCLUDED.priority,
    profile = EXCLUDED.profile,
    homepage_url = EXCLUDED.homepage_url,
    discovery_url = EXCLUDED.discovery_url,
    repository = EXCLUDED.repository,
    subject = EXCLUDED.subject,
    content_access = EXCLUDED.content_access,
    verification = EXCLUDED.verification,
    configured_enabled = EXCLUDED.configured_enabled,
    config_version = EXCLUDED.config_version,
    updated_at = now()
"""
# runtime_state, last_success_at, consecutive_failures and cursors are
# deliberately absent from the UPDATE list: a config edit must not erase
# observed runtime history.


def sync_sources(connection: Any, sources: list[SourceConfig], *, config_version: str) -> int:
    """Upsert sources into PostgreSQL. Returns the row count written."""
    rows = [
        {
            "id": source.id,
            "name": source.name,
            "organization": source.organization,
            "group": source.group or source.profile,
            "region": source.region,
            "tier": source.tier,
            "priority": source.priority,
            "profile": source.profile,
            "homepage_url": source.homepage_url,
            "discovery_url": source.discovery_url,
            "repository": source.repository,
            "subject": source.subject,
            "content_access": source.content_access,
            "verification": source.verification,
            "enabled": source.enabled,
            "config_version": config_version,
            "public_render": "excerpt_link",
        }
        for source in sources
    ]

    with connection.cursor() as cursor:
        cursor.executemany(UPSERT_SQL, rows)
    return len(rows)
