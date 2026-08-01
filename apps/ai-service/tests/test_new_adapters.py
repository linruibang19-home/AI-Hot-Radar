"""Tests for the changelog, listing, repo-activity and public-API adapters.

All offline: responses come from MockTransport, per AHR-QSO-700 §1.
"""

from __future__ import annotations

import base64

import httpx
import pytest

from ahr.ingestion.adapters.changelog import (
    DocsChangelogAdapter,
    parse_heading_date,
    split_sections,
)
from ahr.ingestion.adapters.github_repo import GitHubRepoActivityAdapter
from ahr.ingestion.adapters.listing import HtmlListingAdapter
from ahr.ingestion.adapters.public_api import PublicJsonApiAdapter, reconstruct_abstract
from ahr.ingestion.models import SourceConfig

CHANGELOG_XML = """<doc><main>
<p>Breadcrumb furniture appearing before any heading.</p>
<head rend="h1">Changelog</head>
<p>Intro text belonging to the top-level heading.</p>
<head rend="h2">July 30, 2026</head>
<p>Added streaming support for long responses.</p>
<head rend="h2">2026-07-21</head>
<p>Fixed a retry bug affecting 429 responses.</p>
</main></doc>"""


def make_source(profile: str, **kwargs: object) -> SourceConfig:
    defaults: dict[str, object] = {
        "id": "test-source",
        "name": "Test",
        "organization": "Test Org",
        "profile": profile,
        "tier": "primary",
        "priority": "P0",
        "content_access": "full_release_text",
        "verification": "page_confirmed",
        "enabled": True,
    }
    defaults.update(kwargs)
    return SourceConfig(**defaults)  # type: ignore[arg-type]


# --- changelog -----------------------------------------------------------


def test_split_sections_pairs_heading_with_body() -> None:
    sections = split_sections(CHANGELOG_XML)
    headings = [heading for heading, _ in sections]
    assert "July 30, 2026" in headings
    assert "2026-07-21" in headings


def test_split_sections_drops_content_before_first_heading() -> None:
    """Breadcrumbs above the first heading belong to no section."""
    sections = split_sections(CHANGELOG_XML)
    assert all("Breadcrumb furniture" not in body for _, body in sections)


def test_split_sections_scopes_body_to_its_own_heading() -> None:
    """Each section holds only the text up to the next heading."""
    bodies = dict(split_sections(CHANGELOG_XML))
    assert "streaming support" in bodies["July 30, 2026"]
    assert "retry bug" not in bodies["July 30, 2026"]


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("July 30, 2026", (2026, 7, 30)),
        ("2026-07-21", (2026, 7, 21)),
        ("2026年7月6日", (2026, 7, 6)),
        ("v1.2.3 release", None),
    ],
)
def test_parse_heading_date(heading: str, expected: tuple[int, int, int] | None) -> None:
    parsed = parse_heading_date(heading)
    if expected is None:
        assert parsed is None
    else:
        assert parsed is not None
        assert (parsed.year, parsed.month, parsed.day) == expected


async def test_changelog_emits_section_documents(make_fetcher, monkeypatch) -> None:
    monkeypatch.setattr(
        "ahr.ingestion.adapters.changelog.trafilatura.extract", lambda *a, **k: CHANGELOG_XML
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>ignored</html>")

    source = make_source("docs_changelog", discovery_url="https://example.com/changelog")
    async with make_fetcher(handler) as fetcher:
        batch = await DocsChangelogAdapter(fetcher).discover(source)

    assert len(batch.items) >= 2
    # Section bodies are complete documents; nothing further to fetch.
    assert all(not item.requires_fetch for item in batch.items)
    assert any(item.published_at_hint is not None for item in batch.items)


async def test_changelog_skips_unchanged_sections(make_fetcher, monkeypatch) -> None:
    """A section whose hash is already in the cursor must not be re-emitted."""
    monkeypatch.setattr(
        "ahr.ingestion.adapters.changelog.trafilatura.extract", lambda *a, **k: CHANGELOG_XML
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>ignored</html>")

    source = make_source("docs_changelog", discovery_url="https://example.com/changelog")
    async with make_fetcher(handler) as fetcher:
        first = await DocsChangelogAdapter(fetcher).discover(source)
        second = await DocsChangelogAdapter(fetcher).discover(source, first.next_cursor)

    assert first.items
    assert second.items == []
    assert second.empty_reason == "NO_CHANGED_SECTIONS"


# --- listing -------------------------------------------------------------

LISTING_HTML = """<html><body>
<a href="/blog/first-post">First post</a>
<a href="/blog/second-post">Second post</a>
<a href="/blog/tag/ai">Tag page</a>
<a href="/pricing">Pricing</a>
<a href="https://external.example.org/blog/other">External</a>
</body></html>"""


async def test_listing_discovers_articles_only(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=LISTING_HTML.encode())

    source = make_source("static_listing_to_article", discovery_url="https://example.com/blog")
    async with make_fetcher(handler) as fetcher:
        batch = await HtmlListingAdapter(fetcher).discover(source)

    urls = {item.candidate_url for item in batch.items}
    assert "https://example.com/blog/first-post" in urls
    assert "https://example.com/blog/second-post" in urls
    # Navigation, off-listing paths and other domains are not articles.
    assert not any("/tag/" in url for url in urls)
    assert not any("/pricing" in url for url in urls)
    assert not any("external.example.org" in url for url in urls)


async def test_listing_always_requires_article_fetch(make_fetcher) -> None:
    """A listing teaser can never become body text."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=LISTING_HTML.encode())

    source = make_source("static_listing_to_article", discovery_url="https://example.com/blog")
    async with make_fetcher(handler) as fetcher:
        batch = await HtmlListingAdapter(fetcher).discover(source)

    assert batch.items
    assert all(item.requires_fetch for item in batch.items)
    assert all(item.body_markdown is None for item in batch.items)


# --- github repo activity ------------------------------------------------


async def test_repo_activity_emits_changed_doc(make_fetcher) -> None:
    readme = base64.b64encode(b"# Model card\n\nDetails about the model.").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        if "/commits" in str(request.url):
            path = request.url.params.get("path")
            if path != "README.md":
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json=[{"sha": "abc123", "commit": {"committer": {"date": "2026-07-31T10:00:00Z"}}}],
            )
        return httpx.Response(200, json={"content": readme})

    source = make_source("github_repo_activity", repository="octo/model")
    async with make_fetcher(handler) as fetcher:
        batch = await GitHubRepoActivityAdapter(fetcher).discover(source)

    assert len(batch.items) == 1
    assert batch.items[0].external_id == "octo/model:README.md"
    assert "Model card" in (batch.items[0].body_markdown or "")


async def test_repo_activity_skips_unchanged_sha(make_fetcher) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "/commits" in str(request.url):
            return httpx.Response(200, json=[{"sha": "abc123", "commit": {}}])
        return httpx.Response(200, json={"content": base64.b64encode(b"x").decode()})

    source = make_source("github_repo_activity", repository="octo/model")
    async with make_fetcher(handler) as fetcher:
        first = await GitHubRepoActivityAdapter(fetcher).discover(source)
        second = await GitHubRepoActivityAdapter(fetcher).discover(source, first.next_cursor)

    assert first.items
    assert second.items == []
    assert second.empty_reason == "NO_DOC_CHANGES"


# --- public json api -----------------------------------------------------


def test_reconstruct_abstract_restores_word_order() -> None:
    inverted = {"Large": [0], "language": [1], "models": [2], "scale": [3]}
    assert reconstruct_abstract(inverted) == "Large language models scale"


def test_reconstruct_abstract_handles_missing_index() -> None:
    assert reconstruct_abstract(None) == ""


async def test_huggingface_filters_low_download_models(make_fetcher) -> None:
    """AHR-INGEST-1000 §7: not every model change is news."""
    models = [
        {"id": "org/popular", "downloads": 50_000, "lastModified": "2026-07-31T10:00:00Z"},
        {"id": "org/obscure", "downloads": 3, "lastModified": "2026-07-31T10:00:00Z"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "/api/models" in str(request.url):
            return httpx.Response(200, json=models)
        return httpx.Response(200, content=b"# Model card\n\nSome documentation.")

    source = make_source("public_json_api", discovery_url="https://huggingface.co/api/models")
    async with make_fetcher(handler) as fetcher:
        batch = await PublicJsonApiAdapter(fetcher).discover(source)

    ids = [item.external_id for item in batch.items]
    assert "hf:org/popular" in ids
    assert "hf:org/obscure" not in ids


async def test_openalex_marks_results_metadata_only(make_fetcher) -> None:
    """§9: OpenAlex abstracts must never be presented as paper fulltext."""
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W123",
                "title": "A paper",
                "publication_date": "2026-07-30",
                "abstract_inverted_index": {"An": [0], "abstract": [1]},
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    source = make_source("public_json_api", discovery_url="https://api.openalex.org/works")
    async with make_fetcher(handler) as fetcher:
        batch = await PublicJsonApiAdapter(fetcher).discover(source)

    assert len(batch.items) == 1
    assert batch.items[0].attributes["is_metadata_only"] is True
    assert batch.items[0].discovery_summary == "An abstract"
