# Interactive Graph Deck Skill

A skill for building interactive HTML graph decks — node-based visual presentations with rotation, centering, column layout, and bilingual support.

## Contents

- `SKILL.md` — Full skill documentation
- `scripts/` — Python build pipeline
  - `build_deck.py` — Build deck from JSON data
  - `diagram_to_deck.py` — Convert Mermaid diagrams to deck format
  - `enrich_deck.py` — Enrich deck with additional metadata
- `viewer/viewer.template.html` — Viewer template
- `tests/` — Pipeline tests

## Usage

See `SKILL.md` for full documentation.

## Sample

See `examples/sample/` for a minimal working deck:
- `sample_deck.json` — input data
- `sample_deck.html` — rendered interactive deck

