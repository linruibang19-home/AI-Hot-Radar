"""「成功但从未产出」——那个缺失了 37 天的信号。

openai-news 是 P0 一手源，上线首轮发现 1105 条、入库 0 条，此后每 15 分钟一次
SUCCESS + HTTP 200 + discovered 0，连续失败数 0，错误日志为空。所有常规检查全绿，
而库里一条内容都没有。

这个模块的判据刻意收得很窄：「最近没有新内容」会误伤真正更新慢的信源，也会误伤
github_repo_activity——那个档位一个仓库就是一条活文档，恰好 1 条是设计不是故障。
「成功采集了好几天、一条都没存下来」没有正当解释。
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from ahr.ingestion import health


class _Cursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def execute(self, sql, params):
        self.sql, self.params = sql, params

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self, rows):
        self._rows = rows
        self.last: _Cursor | None = None

    def cursor(self):
        self.last = _Cursor(self._rows)
        return self.last


NOW = datetime(2026, 9, 7, tzinfo=UTC)


def test_a_source_that_never_produced_is_reported() -> None:
    conn = _Connection([("openai-news", "P0", 3552, NOW - timedelta(days=37))])

    stalled = health.stalled_sources(conn, now=NOW)

    assert len(stalled) == 1
    assert stalled[0]["source_id"] == "openai-news"
    assert stalled[0]["priority"] == "P0"
    assert stalled[0]["days"] == 37.0


def test_nothing_stalled_reports_nothing() -> None:
    assert health.stalled_sources(_Connection([]), now=NOW) == []


def test_the_query_only_looks_at_sources_with_no_content_at_all() -> None:
    """「最近没新内容」会误伤更新慢的信源和 github_repo_activity（一个仓库一条
    活文档是设计）。判据必须是"一条都没有"。"""
    source = inspect.getsource(health)
    assert "NOT EXISTS (SELECT 1 FROM content_item ci WHERE ci.source_id = s.id)" in source


def test_a_newly_configured_source_is_given_time() -> None:
    """昨天刚配上、6 小时轮询一次的信源还没得到公平机会。"""
    conn = _Connection([])
    health.stalled_sources(conn, now=NOW)

    assert conn.last is not None
    assert conn.last.params["min_polls"] == health.NEVER_PRODUCED_MIN_POLLS
    assert conn.last.params["cutoff"] == NOW - health.NEVER_PRODUCED_AFTER


def test_the_signal_reaches_a_human() -> None:
    """记录下来但没人看，和没做是一样的——这个项目已经栽过一次。"""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    text = (root / "infra" / "scripts" / "monitor.py").read_text(encoding="utf-8")

    assert "/health/sources" in text, "monitor 必须真的去探这个端点"
    assert "_stalled_detail" in text, "告警里要写清是哪几个信源，别让人再去翻"


def test_it_never_restarts_a_container() -> None:
    """坏掉的 feed 是运维问题，不是重启健康进程的理由——所以它不能进
    /health/ready。"""
    from ahr import health as api_health

    ready = inspect.getsource(api_health.ready)
    assert "stalled" not in ready
