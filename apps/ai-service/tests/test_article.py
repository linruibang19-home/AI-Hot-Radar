"""Article metadata extraction regressions."""

from __future__ import annotations

from ahr.ingestion.article import extract_article
from ahr.ingestion.http import FetchResult


def _response(html: str) -> FetchResult:
    return FetchResult(
        url="https://publisher.example/p/1.html",
        final_url="https://publisher.example/p/1.html",
        status_code=200,
        headers={"content-type": "text/html; charset=utf-8"},
        body=html.encode(),
    )


def test_document_title_beats_extractor_author_label() -> None:
    extraction = extract_article(
        _response(
            """
            <html><head><title>真实文章标题 - 示例媒体</title></head>
            <body><article><h2>示例媒体（公众号：example）</h2>
            <p>这是足够长的真实文章正文，用来确认标题来自页面标题而不是作者署名。</p>
            </article></body></html>
            """
        ),
        source_id="example",
    )

    assert extraction.document.title == "真实文章标题"


def test_discovery_title_remains_first_choice() -> None:
    extraction = extract_article(
        _response(
            """
            <html><head><meta property="og:title" content="页面标题"></head>
            <body><article><p>正文内容用于回放测试。</p></article></body></html>
            """
        ),
        source_id="example",
        title_hint="RSS 已声明标题",
    )

    assert extraction.document.title == "RSS 已声明标题"


def test_open_graph_title_supports_attribute_reordering() -> None:
    extraction = extract_article(
        _response(
            """
            <html><head><meta content="开放图谱标题" property="og:title"></head>
            <body><article><p>正文内容用于回放测试。</p></article></body></html>
            """
        ),
        source_id="example",
    )

    assert extraction.document.title == "开放图谱标题"


def test_zhidx_replay_uses_article_title_not_public_account_label(fixture_bytes) -> None:
    extraction = extract_article(
        _response(fixture_bytes("zhidx_article.html").decode()),
        source_id="zhidx",
    )

    assert extraction.document.title == "稚晖君掌舵的公司，半年营收8亿"
    assert "公众号" in extraction.document.body_text


def test_bytedance_seed_replay_uses_open_graph_article_title(fixture_bytes) -> None:
    extraction = extract_article(
        _response(fixture_bytes("bytedance_seed_article.html").decode()),
        source_id="bytedance-seed-research",
    )

    assert extraction.document.title == (
        "One-take Creation, Flexible Referencing: Introducing Seedance 2.5"
    )
