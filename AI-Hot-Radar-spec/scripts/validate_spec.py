#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import yaml

try:
    import jsonschema
except ImportError:  # validation remains useful without the optional package
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relative: str):
    with (ROOT / relative).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_json(relative: str):
    with (ROOT / relative).open(encoding="utf-8") as handle:
        return json.load(handle)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    errors: list[str] = []
    registry = load_yaml("config/sources.yaml")
    social = load_yaml("config/social-watchlist.yaml")
    profiles_doc = load_yaml("config/ingestion-profiles.yaml")
    overrides_doc = load_yaml("config/site-overrides.yaml")
    schema = load_json("schemas/source-registry.schema.json")

    sources = registry.get("sources", [])
    profiles = profiles_doc.get("profiles", {})
    source_ids = [source.get("id") for source in sources]
    duplicate_ids = [key for key, value in Counter(source_ids).items() if value > 1]

    require(len(sources) == 140, f"expected 140 sources, got {len(sources)}", errors)
    require(not duplicate_ids, f"duplicate source ids: {duplicate_ids}", errors)
    require(all(source.get("profile") in profiles for source in sources), "unknown profile reference", errors)
    require(all(not source.get("enabled") for source in sources if source.get("verification") == "restricted"), "restricted source enabled", errors)

    if jsonschema:
        validator = jsonschema.Draft202012Validator(schema)
        for index, source in enumerate(sources):
            for error in validator.iter_errors(source):
                errors.append(f"sources[{index}] {source.get('id')}: {error.message}")

    overrides = overrides_doc.get("overrides", {})
    api_mappings = overrides_doc.get("api_mappings", {})
    unknown_overrides = sorted((set(overrides) | set(api_mappings)) - set(source_ids))
    require(not unknown_overrides, f"overrides reference unknown source ids: {unknown_overrides}", errors)

    watch_entries = []
    for value in social.values():
        if isinstance(value, list):
            watch_entries.extend(item for item in value if isinstance(item, dict))
    # The registry format may group watchlists under one mapping; recursively count ids.
    def collect_ids(node):
        found = []
        if isinstance(node, dict):
            if "id" in node:
                found.append(node["id"])
            for child in node.values():
                found.extend(collect_ids(child))
        elif isinstance(node, list):
            for child in node:
                found.extend(collect_ids(child))
        return found

    social_ids = collect_ids(social)
    require(len(social_ids) == len(set(social_ids)), "duplicate social watchlist ids", errors)

    required_files = [
        "README.md", "AGENTS.md", "CLAUDE.md", ".env.example",
        "database/V001__baseline.sql", "api/openapi.yaml",
        "docs/10-source-adapter-implementation.md", "docs/11-end-to-end-runbook.md",
        "schemas/source-registry.schema.json", "schemas/ingestion-event.schema.json",
    ]
    for relative in required_files:
        require((ROOT / relative).is_file(), f"missing required file: {relative}", errors)

    if errors:
        print("SPEC VALIDATION FAILED")
        for error in errors:
            print(f"- {error}")
        return 1

    counts = Counter(source["profile"] for source in sources)
    print("SPEC VALIDATION PASSED")
    print(f"sources={len(sources)} profiles={len(profiles)} social_ids={len(social_ids)}")
    print("profile_counts=" + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
