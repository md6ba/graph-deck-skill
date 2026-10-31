"""Tests for the diagram -> deck bridge and the deck builder."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.diagram_to_deck import build_deck, load_diagram, parse_mermaid  # noqa: E402

DIAGRAM = {
    "title": "Widget",
    "description": "A small service.",
    "graph": {
        "groups": [{"id": "backend", "label": "Backend"}],
        "nodes": [
            {"id": "root", "label": "Widget", "path": "README.md", "group": "", "description": ""},
            {"id": "api", "label": "API", "path": "src/api.py", "group": "backend", "description": "HTTP entry"},
            {"id": "db", "label": "DB", "path": "src/db.py", "group": "backend", "description": "Storage"},
        ],
        "edges": [{"from": "root", "to": "api", "label": ""},
                  {"from": "api", "to": "db", "label": "queries"}],
    },
}


def args(**over):
    base = {"diagram_json": None, "mermaid": None, "root": None, "lang": "fa",
            "title": "T", "content": None}
    base.update(over)
    return base


def test_parse_mermaid_extracts_nodes_and_edges():
    parsed = parse_mermaid("flowchart TD\n  a[\"A\"]\n  b[B]\n  a --> b\n  b -.-> a\n")
    assert [n["id"] for n in parsed["nodes"]] == ["a", "b"]
    assert parsed["labels"]["a"] == "A"
    assert len(parsed["edges"]) == 2
    assert parsed["edges"][0]["kind"] == "flow"
    assert parsed["edges"][1]["kind"] == "ref"


def test_parse_mermaid_ignores_comments_and_subgraphs():
    parsed = parse_mermaid("%% a comment\nflowchart TD\n  subgraph g[G]\n    a[A]\n  end\n  a --> b\n")
    assert [n["id"] for n in parsed["nodes"]] == ["a", "b"]


def test_bridge_marks_one_root_and_groups_units(tmp_path):
    deck = build_deck(DIAGRAM, args(), None)
    kinds = {n["id"]: n["kind"] for n in deck["nodes"]}
    assert kinds["root"] == "root"
    assert kinds["backend"] == "unit"
    assert kinds["api"] == "detail"
    assert kinds["db"] == "detail"


def test_bridge_keeps_only_real_edges_and_adds_no_orphans():
    deck = build_deck(DIAGRAM, args(), None)
    ids = {n["id"] for n in deck["nodes"]}
    assert all(e["from"] in ids and e["to"] in ids for e in deck["edges"])
    assert {"root", "backend", "api", "db"} <= ids


def test_bridge_turns_paths_into_evidence():
    deck = build_deck(DIAGRAM, args(), None)
    api = next(n for n in deck["nodes"] if n["id"] == "api")
    assert api["src"] == ["src/api.py"]


def test_bridge_descriptions_become_text_blocks():
    deck = build_deck(DIAGRAM, args(), None)
    api = next(n for n in deck["nodes"] if n["id"] == "api")
    assert api["blocks"][0]["type"] == "text"
    assert "HTTP entry" in api["blocks"][0]["text"]["fa"]


def test_bridge_paths_cover_every_unit():
    deck = build_deck(DIAGRAM, args(), None)
    assert [p["id"] for p in deck["paths"]] == ["backend"]
    assert deck["paths"][0]["nodes"] == ["root", "backend", "api", "db"]


def test_bridge_rejects_an_unknown_root():
    with pytest.raises(Exception):
        build_deck(DIAGRAM, args(root="nope"), None)


def test_bridge_rejects_duplicate_ids():
    bad = json.loads(json.dumps(DIAGRAM))
    bad["graph"]["nodes"].append(dict(bad["graph"]["nodes"][1]))
    with pytest.raises(Exception):
        build_deck(bad, args(), None)


def test_build_deck_produces_a_standalone_page(tmp_path):
    deck = build_deck(DIAGRAM, args(), None)
    deck_path = tmp_path / "deck.json"
    deck_path.write_text(json.dumps(deck, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.html"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_deck.py"), str(deck_path), "-o", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    html = out.read_text(encoding="utf-8")
    assert "<!doctype html>" in html
    assert "deck" in html
    assert '"nodes"' in html


def test_build_deck_fails_on_a_broken_deck(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"nodes": [{"id": "x", "kind": "detail"}]}), encoding="utf-8")
    out = tmp_path / "out.html"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_deck.py"), str(bad), "-o", str(out)],
        capture_output=True, text=True)
    assert result.returncode == 1
    assert ("ERROR" in result.stdout) or ("Error" in result.stderr) or ("StopIteration" in result.stderr)
