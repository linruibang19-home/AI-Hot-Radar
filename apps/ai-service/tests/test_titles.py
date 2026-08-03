"""Title sanitising.

Every case here is a real row that was in the database, not a hypothetical.
"""

from __future__ import annotations

import pytest

from ahr.ingestion.titles import (
    is_usable,
    resolve_title,
    strip_listing_metadata,
    title_from_body,
)

# --- listing metadata -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "J-Space: Yet Another LLM Mind Reader? dlouapre • 20 days ago • 37",
            "J-Space: Yet Another LLM Mind Reader?",
        ),
        (
            "Code a simple RAG from scratch ngxson • Oct 29, 2024 • 371",
            "Code a simple RAG from scratch",
        ),
        (
            "LettucePrevent - Real-Time Prevention of Hallucinations lebe1 • 4 days ago • 6",
            "LettucePrevent - Real-Time Prevention of Hallucinations",
        ),
        # These listings say "about 3 hours ago"; without the qualifier every
        # item less than a day old kept its decoration.
        (
            "The Fast Gemma Challenge    FINAL-Bench • about 3 hours ago •  13",
            "The Fast Gemma Challenge",
        ),
        (
            "超越表层对齐：信念是新入口    Alibaba-VELLDEPTH • about 3 hours ago •  5",
            "超越表层对齐：信念是新入口",
        ),
        (
            "Scaling laws revisited someone • almost 2 years ago • 4",
            "Scaling laws revisited",
        ),
        # Multiple spaces around the separators, as the real rows have.
        (
            "Fine-tune video models with 🤗 Diffusers    nvidia • 16 days ago •  82",
            "Fine-tune video models with 🤗 Diffusers",
        ),
    ],
)
def test_author_date_upvote_suffix_is_stripped(raw: str, expected: str) -> None:
    assert strip_listing_metadata(raw) == expected


def test_a_clean_title_is_left_alone() -> None:
    title = "Mistral Small 4 发布：统一推理、多模态与编码的开源模型"
    assert strip_listing_metadata(title) == title


def test_a_bullet_inside_a_real_title_survives() -> None:
    """The pattern is anchored to the end so mid-title punctuation is safe."""
    title = "GPT-5 • the sequel: what changed"
    assert strip_listing_metadata(title) == title


# --- usability ------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "https://huggingface.co/papers/2607.23782",
        "http://example.com/post",
        "Read More",
        "read more",
        "阅读全文",
        "ab",
        "",
        "   ",
        None,
    ],
)
def test_unusable_titles_are_rejected(bad: str | None) -> None:
    assert is_usable(bad) is False


@pytest.mark.parametrize(
    "good",
    [
        "Mistral Small 4 发布",
        "b10229",
        "Welcome to Agents Week",
        "N_0-VTLA: Scaling Vision-Tactile-Language-Action Model",
    ],
)
def test_real_titles_are_accepted(good: str) -> None:
    assert is_usable(good) is True


# --- deriving a title from the body ---------------------------------------


def test_markdown_heading_wins() -> None:
    body = "# QQWorld: Quantile-Quantile Matching\n\nAbstract Latent world models…"
    assert title_from_body(body) == "QQWorld: Quantile-Quantile Matching"


def test_first_real_line_is_used_when_there_is_no_heading() -> None:
    body = "N_0-VTLA: Scaling Vision-Tactile-Language-Action Model\n\nAbstract We present…"
    assert title_from_body(body) == "N_0-VTLA: Scaling Vision-Tactile-Language-Action Model"


def test_yaml_front_matter_is_skipped() -> None:
    """Hugging Face model cards open with front matter; without skipping it the
    "title" would be "language: en license: mit"."""
    body = (
        "---\nlanguage: en\nlicense: mit\npipeline_tag: text-generation\n"
        "---\n\n# HackerNet Beta v2\n"
    )
    assert title_from_body(body) == "HackerNet Beta v2"


def test_code_fences_and_tables_are_skipped() -> None:
    body = "```\nsome code\n```\n\n| a | b |\n\n> quoted\n\nActual Article Title\n"
    assert title_from_body(body) == "Actual Article Title"


def test_empty_body_yields_nothing() -> None:
    assert title_from_body("") is None
    assert title_from_body(None) is None


def test_derived_title_is_length_capped() -> None:
    assert len(title_from_body("x" * 900) or "") <= 200


# --- resolution order -----------------------------------------------------


def test_a_good_candidate_is_never_overridden_by_the_body() -> None:
    resolved = resolve_title("Real Title Here", body_text="# Something Else", fallback="url")
    assert resolved == "Real Title Here"


def test_url_candidate_falls_through_to_the_body() -> None:
    resolved = resolve_title(
        "https://huggingface.co/papers/2607.28415",
        body_text="QQWorld: Quantile-Quantile Matching for World Model Regularization",
        fallback="https://huggingface.co/papers/2607.28415",
    )
    assert resolved == "QQWorld: Quantile-Quantile Matching for World Model Regularization"


def test_decorated_candidate_is_cleaned_rather_than_replaced() -> None:
    resolved = resolve_title(
        "Code a simple RAG from scratch ngxson • Oct 29, 2024 • 371",
        body_text="# A totally different heading",
    )
    assert resolved == "Code a simple RAG from scratch"


def test_fallback_is_used_when_nothing_else_works() -> None:
    """Never invent a title: the canonical URL at least identifies the item
    (AHR-INGEST-1000 §5 forbids fabricated metadata)."""
    assert resolve_title("Read More", body_text="", fallback="https://x.test/a") == (
        "https://x.test/a"
    )


def test_no_candidate_and_no_body_returns_the_fallback() -> None:
    assert resolve_title(None, body_text=None, fallback="fb") == "fb"
