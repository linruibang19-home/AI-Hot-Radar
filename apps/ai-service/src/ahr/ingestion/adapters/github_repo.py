"""GitHub repository activity adapter.

AHR-INGEST-1000 §4 and AHR-DATA-300 §4.4: for model repos that ship no formal
Releases, watch README/CHANGELOG changes instead. Ordinary commits are not news,
so only the watched documentation paths are tracked.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

from ahr.ingestion.errors import ParseFailedError
from ahr.ingestion.models import DiscoveredDocument, DiscoveryBatch, SourceConfig, SourceCursor

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"

WATCHED_PATHS = ("README.md", "CHANGELOG.md", "releases.md")


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GitHubRepoActivityAdapter:
    """Tracks documentation changes in a repository."""

    name = "github_repo_activity"

    def __init__(self, fetcher: Any, *, token: str | None = None) -> None:
        self._fetcher = fetcher
        self._token = token

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def discover(
        self, source: SourceConfig, cursor: SourceCursor | None = None
    ) -> DiscoveryBatch:
        if not source.repository:
            raise ParseFailedError(f"source {source.id} has no repository")

        cursor = cursor or SourceCursor()
        last_shas: dict[str, str] = dict((cursor.extra or {}).get("last_sha_by_path", {}))
        items: list[DiscoveredDocument] = []
        new_shas = dict(last_shas)
        http_status: int | None = None

        for path in WATCHED_PATHS:
            commits_url = f"{API_ROOT}/repos/{source.repository}/commits?path={path}&per_page=1"
            try:
                response = await self._fetcher.fetch(commits_url, headers=self._headers())
            except ParseFailedError:
                continue
            except Exception:  # noqa: BLE001 - a missing file must not fail the source
                continue

            http_status = response.status_code
            try:
                commits = json.loads(response.text())
            except json.JSONDecodeError:
                continue
            if not isinstance(commits, list) or not commits:
                continue

            head = commits[0]
            sha = head.get("sha")
            if not sha or last_shas.get(path) == sha:
                continue

            content_url = f"{API_ROOT}/repos/{source.repository}/contents/{path}?ref={sha}"
            try:
                content_response = await self._fetcher.fetch(content_url, headers=self._headers())
                payload = json.loads(content_response.text())
                encoded = payload.get("content", "")
                body = base64.b64decode(encoded).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue

            new_shas[path] = sha
            commit_meta = head.get("commit", {}) or {}
            committed_at = _parse_iso8601((commit_meta.get("committer") or {}).get("date"))

            items.append(
                DiscoveredDocument(
                    # Identity is repo+path: a later commit updates the same
                    # document rather than creating a duplicate.
                    external_id=f"{source.repository}:{path}",
                    candidate_url=f"https://github.com/{source.repository}/blob/{sha}/{path}",
                    title_hint=f"{source.repository} {path}",
                    published_at_hint=committed_at,
                    body_markdown=body,
                    requires_fetch=False,
                    attributes={"path": path, "sha": sha, "repository": source.repository},
                )
            )

        return DiscoveryBatch(
            items=items,
            next_cursor=SourceCursor(
                newest_entry_time=cursor.newest_entry_time,
                extra={"last_sha_by_path": new_shas},
            ),
            http_status=http_status,
            empty_reason="NO_DOC_CHANGES" if not items else None,
        )
