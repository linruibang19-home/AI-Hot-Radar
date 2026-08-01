"""Shared ingestion value objects.

Every adapter emits `DiscoveredDocument` so downstream stages never branch on
source type (AHR-INGEST-1000 §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourceConfig:
    """One entry from config/sources.yaml, resolved against its profile."""

    id: str
    name: str
    organization: str
    profile: str
    tier: str
    priority: str
    content_access: str
    verification: str
    enabled: bool
    discovery_url: str | None = None
    repository: str | None = None
    subject: str | None = None
    homepage_url: str | None = None
    region: str = "global"
    group: str = ""

    @property
    def requires_article_fetch(self) -> bool:
        """True when the discovery response is metadata, not the body.

        GitHub releases, changelogs and repo activity carry the full document in
        the discovery response; feeds and listings only carry a pointer.
        """
        return self.profile in {
            "rss_to_article",
            "author_feed_to_article",
            "static_listing_to_article",
            "dynamic_listing_to_article",
            "arxiv_feed_paper",
        }

    @property
    def is_release_like(self) -> bool:
        """True when the body is a complete release note rather than an article."""
        return self.profile in {"github_release_api", "github_repo_activity", "docs_changelog"}


@dataclass(frozen=True)
class SourceCursor:
    """Incremental position for one source.

    Advanced only after the batch and its outbox rows commit
    (AHR-INGEST-1000 §11).
    """

    etag: str | None = None
    last_modified: str | None = None
    newest_entry_time: datetime | None = None
    max_external_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveredDocument:
    """A candidate found by an adapter."""

    external_id: str
    candidate_url: str
    title_hint: str | None = None
    published_at_hint: datetime | None = None
    discovery_summary: str | None = None
    # Populated when discovery already carries the full document (GitHub, changelog).
    body_markdown: str | None = None
    requires_fetch: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoveryBatch:
    """Result of one discovery pass."""

    items: list[DiscoveredDocument] = field(default_factory=list)
    next_cursor: SourceCursor | None = None
    not_modified: bool = False
    http_status: int | None = None
    # An empty batch is normal (arXiv publishes nothing at weekends), so it must
    # be distinguishable from a failure.
    empty_reason: str | None = None

    @classmethod
    def unchanged(cls, cursor: SourceCursor | None = None) -> DiscoveryBatch:
        return cls(items=[], next_cursor=cursor, not_modified=True, http_status=304)
