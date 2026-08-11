"""Chunking, de-duplication and enrichment-contract tests (M2)."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import psycopg
import pytest
from pydantic import ValidationError

from ahr.processing.chunking import MAX_TOKENS, chunk_document, estimate_tokens
from ahr.processing.dedup import (
    from_signed_64,
    hamming_distance,
    is_near_duplicate,
    simhash,
    to_signed_64,
)
from ahr.processing.llm import (
    EnrichmentSchemaError,
    LlmClient,
    LlmConfig,
    LlmUnavailableError,
    build_client_from_env,
)
from ahr.processing.schemas import EnrichmentResult

PARAGRAPH = (
    "Retrieval augmented generation combines a retriever with a generator so "
    "answers stay grounded in retrieved evidence rather than model memory. "
)


# --- chunking ------------------------------------------------------------


def test_empty_document_yields_no_chunks() -> None:
    assert chunk_document("") == []
    assert chunk_document("   \n  ") == []


def test_chunks_respect_the_token_ceiling() -> None:
    document = "\n\n".join([PARAGRAPH * 3] * 30)
    chunks = chunk_document(document)
    assert chunks
    # Prose is split at block boundaries, so nothing should exceed the cap.
    assert all(chunk.token_count <= MAX_TOKENS for chunk in chunks)


def test_headings_are_recorded_as_path() -> None:
    document = (
        "# Guide\n\n"
        f"{PARAGRAPH * 3}\n\n"
        "## Retrieval\n\n"
        f"{PARAGRAPH * 3}\n\n"
        "### Hybrid search\n\n"
        f"{PARAGRAPH * 3}\n"
    )
    chunks = chunk_document(document)
    paths = [tuple(chunk.heading_path) for chunk in chunks]
    assert ("Guide",) in paths
    assert ("Guide", "Retrieval") in paths
    assert ("Guide", "Retrieval", "Hybrid search") in paths


def test_chunks_never_mix_two_sections() -> None:
    document = (
        "## Section A\n\n"
        f"{PARAGRAPH * 2}Alpha marker.\n\n"
        "## Section B\n\n"
        f"{PARAGRAPH * 2}Beta marker.\n"
    )
    for chunk in chunk_document(document):
        assert not ("Alpha marker" in chunk.text and "Beta marker" in chunk.text)


def test_code_block_is_not_split() -> None:
    code = "\n".join(f"line_{i} = compute(i)" for i in range(40))
    document = f"## Example\n\n{PARAGRAPH}\n\n```python\n{code}\n```\n"
    chunks = chunk_document(document)
    holder = [chunk for chunk in chunks if "line_0" in chunk.text]
    assert holder, "the code block should appear in some chunk"
    # Whichever chunk holds the fence must hold all of it.
    assert "line_39" in holder[0].text


def test_char_offsets_are_ordered() -> None:
    document = "\n\n".join([PARAGRAPH * 3] * 8)
    chunks = chunk_document(document)
    assert all(chunk.char_start <= chunk.char_end for chunk in chunks)


def test_token_estimate_accounts_for_cjk_density() -> None:
    """CJK packs more tokens per character than Latin text."""
    assert estimate_tokens("人工智能模型发布") > estimate_tokens("ai model")


# --- de-duplication ------------------------------------------------------


def test_identical_text_is_a_near_duplicate() -> None:
    text = PARAGRAPH * 5
    assert is_near_duplicate(simhash(text), simhash(text))


def test_lightly_edited_copy_is_a_near_duplicate() -> None:
    original = PARAGRAPH * 8
    syndicated = original + " Republished with permission."
    assert is_near_duplicate(simhash(original), simhash(syndicated))


def test_different_articles_are_not_near_duplicates() -> None:
    left = "OpenAI released a new reasoning model with a larger context window today."
    right = "Kubernetes 1.33 improves scheduler performance for large clusters."
    assert not is_near_duplicate(simhash(left), simhash(right))


def test_empty_text_is_never_a_duplicate() -> None:
    """Two empty bodies are missing data, not evidence of duplication."""
    assert not is_near_duplicate(simhash(""), simhash(""))
    assert not is_near_duplicate(0, simhash(PARAGRAPH))


def test_hamming_distance_is_symmetric() -> None:
    left, right = simhash("alpha beta gamma"), simhash("alpha beta delta")
    assert hamming_distance(left, right) == hamming_distance(right, left)


@pytest.mark.parametrize("value", [0, 1, 2**62, 2**63, 2**64 - 1])
def test_signed_64_roundtrip(value: int) -> None:
    """SimHash must survive storage in a PostgreSQL BIGINT."""
    signed = to_signed_64(value)
    assert -(2**63) <= signed < 2**63
    assert from_signed_64(signed) == value


# --- enrichment contract -------------------------------------------------


VALID_PAYLOAD = {
    "summary_zh": "OpenAI 发布了新的推理模型。",
    "zh_title": "OpenAI 发布新推理模型",
    "content_type": "model_release",
    "entities": [{"name": "OpenAI", "type": "company", "role": "subject", "confidence": 0.9}],
    "topics": [{"slug": "reasoning", "confidence": 0.8}],
    "quality_factors": {
        "relevance": 90,
        "information_gain": 70,
        "technical_depth": 60,
        "spam_penalty": 0,
    },
}


def test_valid_payload_parses() -> None:
    result = EnrichmentResult.model_validate(VALID_PAYLOAD)
    assert result.content_type == "model_release"
    assert result.entities[0].name == "OpenAI"


def test_unknown_content_type_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "content_type": "made_up_category"}
    with pytest.raises(ValidationError):
        EnrichmentResult.model_validate(payload)


def test_out_of_range_confidence_is_rejected() -> None:
    payload = {**VALID_PAYLOAD, "entities": [{"name": "X", "type": "company", "confidence": 4.2}]}
    with pytest.raises(ValidationError):
        EnrichmentResult.model_validate(payload)


def test_quality_score_is_bounded_and_penalised() -> None:
    result = EnrichmentResult.model_validate(VALID_PAYLOAD)
    clean = result.quality_score(source_authority=90)
    assert 0.0 <= clean <= 100.0

    spammy = EnrichmentResult.model_validate(
        {
            **VALID_PAYLOAD,
            "quality_factors": {**VALID_PAYLOAD["quality_factors"], "spam_penalty": 60},
        }
    )
    assert spammy.quality_score(source_authority=90) < clean


def _client(handler) -> LlmClient:
    return LlmClient(
        LlmConfig(base_url="https://llm.example", api_key="k", model="test-model", max_attempts=1),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def _completion(content: str) -> dict[str, object]:
    return {"choices": [{"message": {"content": content}}]}


async def test_enrich_parses_valid_response() -> None:
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_completion(json.dumps(VALID_PAYLOAD)))

    async with _client(handler) as client:
        result, usage = await client.enrich(title="t", body_text="body", source_name="s")

    assert result.zh_title == "OpenAI 发布新推理模型"
    # Usage must come from the provider so spend is auditable, not estimated.
    assert usage.attempts == 1


async def test_enrich_strips_markdown_code_fence() -> None:
    """Models wrap JSON in a fence despite being told not to."""
    import json

    def handler(request: httpx.Request) -> httpx.Response:
        fenced = f"```json\n{json.dumps(VALID_PAYLOAD)}\n```"
        return httpx.Response(200, json=_completion(fenced))

    async with _client(handler) as client:
        result, _usage = await client.enrich(title="t", body_text="body", source_name="s")

    assert result.content_type == "model_release"


async def test_enrich_repairs_once_then_succeeds() -> None:
    import json

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json=_completion("not json at all"))
        return httpx.Response(200, json=_completion(json.dumps(VALID_PAYLOAD)))

    async with _client(handler) as client:
        result, usage = await client.enrich(title="t", body_text="body", source_name="s")

    assert calls["n"] == 2
    assert result.summary_zh
    # The repair turn is billed too, so both attempts must be recorded.
    assert usage.attempts == 2


async def test_enrich_dead_letters_after_one_failed_repair() -> None:
    """AHR-SPEC-000 §8: at most one repair, then stop. Never store free text."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_completion("still not json"))

    async with _client(handler) as client:
        with pytest.raises(EnrichmentSchemaError):
            await client.enrich(title="t", body_text="body", source_name="s")

    assert calls["n"] == 2


async def test_provider_error_raises_unavailable_not_schema_error() -> None:
    """A down provider must be distinguishable from a bad response."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "overloaded"})

    async with _client(handler) as client:
        with pytest.raises(LlmUnavailableError):
            await client.enrich(title="t", body_text="body", source_name="s")


async def test_v4_explicitly_disables_thinking() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_completion("{}"))

    client = LlmClient(
        LlmConfig(
            base_url="https://api.deepseek.example",
            api_key="k",
            model="deepseek-v4-flash",
            max_attempts=1,
        ),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    async with client:
        await client.summarize(system_prompt="s", user_prompt="u")

    assert seen["thinking"] == {"type": "disabled"}


def test_running_client_reads_model_and_prices_from_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = MagicMock()
    connection.__enter__.return_value = connection
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchone.return_value = ("deepseek-v4-pro", 7, 3, 0.025, 6)

    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.example")
    monkeypatch.setenv("LLM_API_KEY", "secret")
    monkeypatch.setenv("LLM_MODEL", "legacy-must-not-win")
    monkeypatch.setenv("DATABASE_URL", "postgresql://db/example")
    monkeypatch.setattr(psycopg, "connect", lambda *_args, **_kwargs: connection)

    client = build_client_from_env()

    assert client.model_name == "deepseek-v4-pro"
    assert client.model_config_version == 7
    assert client.price_snapshot == (3.0, 0.025, 6.0)
