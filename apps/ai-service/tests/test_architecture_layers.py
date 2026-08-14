"""Cheap, executable dependency rules for the Python modular service.

The project is intentionally package-by-capability rather than a four-folder
framework.  These tests protect the important direction of travel without
forcing every pure function behind an interface:

* ingestion is the upstream adapter/domain and cannot call processing or RAG;
* RAG may reuse the provider client from processing, but cannot reach back into
  ingestion or create a second crawler path;
* FastAPI is confined to the composition/transport modules.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "ahr"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _python_files(relative: str) -> list[Path]:
    return list((PACKAGE_ROOT / relative).rglob("*.py"))


def test_ingestion_does_not_depend_on_downstream_processing_or_rag() -> None:
    violations: list[str] = []
    for path in _python_files("ingestion"):
        for module in _imports(path):
            if module.startswith(("ahr.processing", "ahr.rag")):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} -> {module}")
    assert violations == []


def test_rag_does_not_depend_on_ingestion_adapters() -> None:
    violations: list[str] = []
    for path in _python_files("rag"):
        for module in _imports(path):
            if module.startswith("ahr.ingestion"):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} -> {module}")
    assert violations == []


def test_fastapi_stays_in_transport_modules() -> None:
    allowed = {Path("main.py"), Path("health.py"), Path("rag/api.py")}
    violations: list[str] = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        relative = path.relative_to(PACKAGE_ROOT)
        if (
            any(module == "fastapi" or module.startswith("fastapi.") for module in _imports(path))
            and relative not in allowed
        ):
            violations.append(str(relative))
    assert violations == []
