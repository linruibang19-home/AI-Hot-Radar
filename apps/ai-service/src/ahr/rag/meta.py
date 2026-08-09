"""Questions about the system, answered from the system (Phase B-2).

「现在有什么信源？」 was answered, before this module, with four llama.cpp release
notes and a confident summary of the download links in them. The corpus does not
contain a document describing the corpus, so retrieval had nothing to find and
found the nearest thing instead.

**Retrieval always returns a top-k.** That is the whole failure: there is no
"nothing matched" signal to fall back on, so a question the corpus cannot answer
comes back looking exactly like one it can. Refusing would be honest but poor —
the site *knows* how many sources it has, it is printed on the front page — so
the question is routed to that answer instead of into the index.

**Not generated.** These numbers come from `count(*)`, not from a model, and the
answer carries no citations because nothing here is a claim about the news. It is
therefore not a refusal either: `refused` means the corpus could not support an
answer, and this answer is fully supported by something that is not the corpus.
The response is labelled as its own kind so the page can render it as the site
telling you about itself rather than as an answer about AI news.

**Scoped by the absence of an entity.** 「有哪些信源」 is about the site;
「OpenAI 有哪些信源」 is about OpenAI and belongs in the index. The corpus already
knows which names are entities, so a meta pattern that also resolves an entity is
not treated as meta — reusing the same resolver the boosts use, rather than
inventing a second notion of "names a thing".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Deliberately narrow. A loose pattern here silently diverts real questions away
# from retrieval, which is a worse failure than the one being fixed: an answer
# about the corpus when the reader wanted news is confidently off-topic, and the
# reader has no way to tell it happened.
_META_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(有哪些|有什么|多少个?|哪些)\s*(信源|来源|数据源|站点|网站)"),
    re.compile(r"(收录|采集|抓取|索引)了?\s*(多少|哪些|什么)"),
    re.compile(r"(数据|内容|资讯|语料)\s*(从哪|来自哪|哪里来|有多少|多不多)"),
    re.compile(r"(多久|多长时间|什么频率|多频繁).{0,6}(更新|采集|抓取)"),
    re.compile(r"(更新|数据).{0,4}(到什么时候|到哪天|多新|新不新)"),
    re.compile(r"(你|系统|本站|这个网站|平台).{0,8}(能做什么|怎么工作|覆盖|范围)"),
    # 「现在信源情况是怎么样的」 fell through the patterns above and was answered
    # from the index with eight citations about AI industry news. Asking after
    # the *state* of something is as common a phrasing as asking what it
    # contains, and none of the first six covered it.
    re.compile(r"(信源|来源|数据源|语料|收录|索引|内容)(的)?(情况|状态|规模|覆盖|构成)"),
    re.compile(r"(信源|数据源|语料|收录).{0,5}(怎么样|如何|多不多|全不全)"),
)


@dataclass(frozen=True)
class CorpusFacts:
    items: int
    active_sources: int
    chunks: int
    enriched: int
    newest: Any | None
    oldest: Any | None


def looks_like_meta(question: str) -> bool:
    """Whether the wording asks about the site rather than about the news."""
    return any(pattern.search(question) for pattern in _META_PATTERNS)


def load_corpus_facts(connection: Any) -> CorpusFacts:
    """The same counts the front page shows, from the same tables.

    Reusing `ContentRepository.stats`'s definitions rather than inventing a
    second set: a reader who is told 1553 here and sees 1553 on the home page
    learns the two agree, and one that quietly counted duplicates would be a
    number nobody could reconcile.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT (SELECT count(*) FROM content_item WHERE duplicate_of_id IS NULL),
                   (SELECT count(*) FROM source WHERE runtime_state = 'ACTIVE'),
                   (SELECT count(*) FROM content_chunk),
                   (SELECT count(*) FROM content_item WHERE enrichment_state = 'ENRICHED'),
                   (SELECT max(COALESCE(published_at, observed_at)) FROM content_item),
                   (SELECT min(COALESCE(published_at, observed_at)) FROM content_item)
            """
        )
        row = cursor.fetchone() or (0, 0, 0, 0, None, None)

    return CorpusFacts(
        items=int(row[0] or 0),
        active_sources=int(row[1] or 0),
        chunks=int(row[2] or 0),
        enriched=int(row[3] or 0),
        newest=row[4],
        oldest=row[5],
    )


def top_sources(connection: Any, limit: int = 8) -> list[tuple[str, int]]:
    """The publishers behind most of the corpus, for 「有哪些信源」.

    A list of eight is an answer; a list of 107 is a database dump, and the
    admin page already exists for the reader who wants all of them.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT s.name, count(*) AS items
              FROM content_item ci
              JOIN source s ON s.id = ci.source_id
             WHERE ci.duplicate_of_id IS NULL
             GROUP BY s.name
             ORDER BY items DESC, s.name
             LIMIT %s
            """,
            (limit,),
        )
        return [(str(row[0]), int(row[1])) for row in cursor.fetchall()]


def compose(facts: CorpusFacts, sources: list[tuple[str, int]]) -> str:
    """Write the answer. Deterministic, so it cannot drift from the numbers."""
    lines = [
        f"本站目前收录 **{facts.items}** 条内容，来自 **{facts.active_sources}** 个活跃信源，"
        f"其中 **{facts.enriched}** 条已完成 AI 结构化，切分为 **{facts.chunks}** 个检索分块。"
    ]

    if facts.newest is not None and facts.oldest is not None:
        lines.append(
            f"\n内容时间范围为 {facts.oldest.date().isoformat()} 至 "
            f"{facts.newest.date().isoformat()}；采集每 2 分钟轮询一次，"
            "加工与精选每 15 分钟跑一轮。"
        )

    if sources:
        lines.append("\n收录量最大的信源：")
        lines.extend(f"- {name}（{count} 条）" for name, count in sources)
        lines.append("\n完整信源列表见「信源后台」页面。")

    return "\n".join(lines)


def answer_meta(connection: Any) -> tuple[str, list[str]]:
    """The composed answer plus what it does not cover, honestly stated."""
    facts = load_corpus_facts(connection)
    body = compose(facts, top_sources(connection))
    limitations = [
        "这是本站自身的运行数据，不是检索结果，因此没有引用来源。",
        "如果你想问的是某家厂商或某个产品的动态，请把它的名字写进问题。",
    ]
    return body, limitations
