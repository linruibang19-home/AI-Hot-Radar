"""Public JSON API adapter.

Covers two very different endpoints (AHR-INGEST-1000 §7, §9):

* Hugging Face Hub - the model card README is real fulltext.
* OpenAlex - metadata and a reconstructed abstract only. §9 is explicit that
  this must never be presented as paper fulltext, so those documents are
  emitted with a short body and settle as METADATA_ONLY at the gate.

Not every model change is news; §7 requires a relevance filter, applied here as
a download threshold plus recency.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

HF_API = "https://huggingface.co/api/models"
HF_RAW = "https://huggingface.co/{model_id}/raw/main/README.md"

# §7: only notable models qualify as news.
HF_MIN_DOWNLOADS = 5000


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Rebuild OpenAlex's `abstract_inverted_index` into readable text."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        positions.extend((index, word) for index in indexes)
    positions.sort()
    return " ".join(word for _, word in positions)


class PublicJsonApiAdapter:
    """Dispatches to the right public API based on the source's endpoint."""

    name = "public_json_api"

    def __init__(self, fetcher: Any, *, max_items: int = 20) -> None:
        self._fetcher = fetcher
        self._max_items = max_items

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        if not source.discovery_url:
            raise ParseFailedError(f"source {source.id} has no discovery_url")

        cursor = cursor or SourceCursor()
        if "huggingface.co" in source.discovery_url:
            return await self._discover_huggingface(source, cursor)
        if "openalex.org" in source.discovery_url:
            return await self._discover_openalex(source, cursor)
        raise ParseFailedError(f"no public API handler for {source.discovery_url}")

    async def _discover_huggingface(
        self, source: SourceConfig, cursor: SourceCursor
    ) -> DiscoveryBatch:
        url = f"{HF_API}?sort=lastModified&direction=-1&limit=50&full=true"
        response = await self._fetcher.fetch(url, etag=cursor.etag)
        if response.not_modified:
            return DiscoveryBatch.unchanged(cursor)

        try:
            models = json.loads(response.text())
        except json.JSONDecodeError as exc:
            raise ParseFailedError(f"invalid JSON from {url}: {exc}") from exc

        items: list[DiscoveredDocument] = []
        newest = cursor.newest_entry_time

        for model in models:
            if len(items) >= self._max_items:
                break
            model_id = model.get("id") or model.get("modelId")
            if not model_id:
                continue
            if (model.get("downloads") or 0) < HF_MIN_DOWNLOADS:
                continue

            modified = _parse_iso8601(model.get("lastModified"))
            if cursor.newest_entry_time and modified and modified <= cursor.newest_entry_time:
                continue
            if modified and (newest is None or modified > newest):
                newest = modified

            # The model card README is the fulltext for this source.
            body = ""
            try:
                card = await self._fetcher.fetch(HF_RAW.format(model_id=model_id))
                body = card.text()
            except Exception:  # noqa: BLE001 - a missing card leaves metadata only
                body = ""

            items.append(
                DiscoveredDocument(
                    external_id=f"hf:{model_id}",
                    candidate_url=f"https://huggingface.co/{model_id}",
                    title_hint=model_id,
                    published_at_hint=modified,
                    body_markdown=body,
                    requires_fetch=False,
                    attributes={
                        "downloads": model.get("downloads"),
                        "likes": model.get("likes"),
                        "pipeline_tag": model.get("pipeline_tag"),
                    },
                )
            )

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(etag=response.etag, newest_entry_time=newest),
            http_status=response.status_code,
            empty_reason="NO_NEW_MODELS" if not items else None,
        )

    async def _discover_openalex(
        self, source: SourceConfig, cursor: SourceCursor
    ) -> DiscoveryBatch:
        import os

        mailto = os.environ.get("OPENALEX_MAILTO") or ""
        url = (
            f"{source.discovery_url}?filter=concepts.id:C154945302"
            f"&sort=publication_date:desc&per-page=25"
        )
        if mailto:
            url += f"&mailto={mailto}"

        response = await self._fetcher.fetch(url)
        try:
            payload = json.loads(response.text())
        except json.JSONDecodeError as exc:
            raise ParseFailedError(f"invalid JSON from OpenAlex: {exc}") from exc

        items: list[DiscoveredDocument] = []
        for work in payload.get("results", [])[: self._max_items]:
            work_id = work.get("id")
            if not work_id:
                continue
            abstract = reconstruct_abstract(work.get("abstract_inverted_index"))
            items.append(
                DiscoveredDocument(
                    external_id=str(work_id),
                    candidate_url=work.get("doi") or work_id,
                    title_hint=work.get("title") or work.get("display_name"),
                    published_at_hint=_parse_iso8601(work.get("publication_date")),
                    # §9: metadata and abstract only. Never claimed as fulltext.
                    discovery_summary=abstract,
                    body_markdown=abstract,
                    requires_fetch=False,
                    attributes={"openalex_id": work_id, "is_metadata_only": True},
                )
            )

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(newest_entry_time=cursor.newest_entry_time),
            http_status=response.status_code,
            empty_reason="NO_RESULTS" if not items else None,
        )
