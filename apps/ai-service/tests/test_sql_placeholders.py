"""Every literal SQL string sent with parameters must parse as psycopg placeholders.

2026-09-24: a comment inside the sparse channel's SQL read "about 12% faster".
psycopg scans the whole query text for `%` — comments included — so every
keyword query failed with `incomplete placeholder`, while the fake cursors the
unit tests use accepted it. This mirrors psycopg's rule over the source instead
of trusting a fake to reproduce it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import ahr

# What psycopg accepts after `%` when parameters are passed: a positional
# placeholder (`%s`, `%b`, `%t`), a named one (`%(name)s`), or an escaped `%%`.
_ALLOWED = re.compile(r"%(?:[sbt%]|\([A-Za-z_][A-Za-z0-9_]*\)[sbt])")


def _literal_parts(node: ast.expr) -> list[str] | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.JoinedStr):
        return [v.value for v in node.values if isinstance(v, ast.Constant)]
    return None


def _parameterised_sql() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in sorted(Path(ahr.__file__).parent.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in {"execute", "executemany"}
                and node.args
            ):
                continue
            # Without parameters psycopg sends the text untouched, so `%` is fine.
            if len(node.args) < 2 and not any(k.arg == "params" for k in node.keywords):
                continue
            for part in _literal_parts(node.args[0]) or []:
                found.append((path.name, node.lineno, part))
    return found


def test_the_scan_sees_the_retrieval_queries() -> None:
    """Guards the guard: an AST change that matched nothing would pass vacuously."""
    names = {name for name, _, _ in _parameterised_sql()}
    assert "retrieval.py" in names
    assert len(_parameterised_sql()) > 100


def test_no_stray_percent_in_parameterised_sql() -> None:
    stray = [
        f"{name}:{line}"
        for name, line, text in _parameterised_sql()
        if _ALLOWED.sub("", text).count("%")
    ]
    assert stray == []
