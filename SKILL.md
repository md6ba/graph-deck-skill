---
name: mermaid-graph-presentation
description: Turn a Mermaid diagram (or repo-to-architecture-diagram output) into a single self-contained, interactive, offline HTML deck with progressive reveal, audience paths, and present mode. Use when the user wants a "graph/mind-map/node presentation", a non-linear deck, or says "mermaid-graph-presentation" / "graph-deck".
version: 1.0.0
---

# mermaid-graph-presentation

Converts a base diagram (Mermaid or the `repo-to-architecture-diagram` skill output) into a
single self-contained HTML file: an interactive SVG graph with pan/zoom, progressive reveal,
audience paths, present mode, FA/EN toggle, RTL/LTR, light/dark. No runtime dependencies,
no network, works offline.

## Pipeline

1. **Base diagram** — produce a Mermaid `flowchart`/`graph` (or run `repo-to-architecture-diagram`).
2. **Bridge** — `python3 scripts/diagram_to_deck.py --mermaid X.mmd -o deck.json`
   (or `--diagram-json <skill output>`). Maps groups→units, nodes→details, edges→edges.
3. **Enrich (optional)** — `python3 scripts/enrich_deck.py deck.json --content content.json`
   to add bilingual titles/blocks/sources per node.
4. **Build** — `python3 scripts/build_deck.py deck.json -o out.html [--font Vazirmatn.woff2] [--strict]`.
5. **Smoke test** — open in a browser; click a node, a path button, enter present mode, press arrows; assert no console errors.

## CLI

- `scripts/diagram_to_deck.py` — diagram → deck.json
- `scripts/build_deck.py` — deck.json → HTML (validates: duplicate ids, unknown parents/edges/paths, orphans, missing assets, bad block types; `--strict` also fails on warnings)
- `scripts/enrich_deck.py` — merge a content map into deck.json

## deck.json schema (summary)

`meta {title:{fa,en}, lang, logo}`, `nodes [{id, kind(root|unit|biz|detail), parent, title, sub, status, note, blocks[], src[], x?, y?}]`,
`edges [{from, to, kind(ref|flow|branch), label?}]`, `paths [{id, title, nodes:[ids]}]`, `tour [ids]`.

Block types: `text`, `list`, `code`, `image`, `link` (non-http href renders as a path chip).

## Honesty rules

- Status must come from source docs; use `partial`/`pending` + `note` when something is "implemented but not wired".
- Quote security properties with their stated scope.
- Never include price/valuation unless the user supplies them.
- If sources contradict, omit the number and report the contradiction.

## Pitfalls

- `meta.logo` (and image block `src`) MUST be a relative file path, not a data URI — `build_deck.py` runs `inline()` on them and treats a data URI as a missing file.
- When improving an already-built deck, prefer **surgical edits** to the embedded JSON over a full rebuild: parse `<script id="deck">`, modify, `json.dumps(...).replace("</", "<\\/")`, replace the block, rewrite. Then verify: JSON parses, no invisible Unicode (U+200B/C/D, U+2060, U+FEFF, U+0654), HTML tag balance clean, browser smoke test.
- Non-http `link` hrefs render as path chips — use them for source traceability (one chip per unique evidence file). When deriving the chip label from the href, **strip a trailing slash first** (`href.rstrip('/').split('/')[-1]`); otherwise directory paths like `00-Deal-Readiness/` yield an empty label.
- `build_deck.py` looks for `viewer/viewer.template.html` relative to `scripts/` (`HERE.parent / "viewer"`). Keep that layout when vendoring.
- A deck with zero `root`-kind nodes crashes the builder (`StopIteration`); always ensure exactly one root.
- **Completeness check before shipping:** verify every node appears in at least one `path` (a deck with 21/36 nodes in no path leaves most of the graph unreachable via audience routes). Also verify the `tour` covers the units you want in present mode, and that partial/pending units carry a *specific* note (not the auto-generated boilerplate "این واحد دست‌کم یک زیرگره ناتمام…") when a more informative one is available.

## Viewer / present-mode pitfalls (learned in production)

- **Wrap, don't clamp, at the last slide.** `step()` must wrap around (`if (pi >= len) pi = 0`) instead of `Math.min(len-1, ...)`. Clamping makes the deck appear to "stop" at the final tour entry with no visible feedback — users read it as a freeze.
- **Do not RTL-flip arrow keys.** In RTL decks the tempting `fw = ArrowRight !== rtl` makes the right arrow go *backward*, which contradicts the user's muscle memory. Make Right/Space always advance and Left always go back; rely on the on-screen hint instead.
- **Make the hint unambiguous.** "← → برای حرکت" is ambiguous in RTL. Use "→/Space جلو · Esc خروج" (or the EN equivalent) so the forward key is explicit.
- **Rapid key presses during the 0.6s camera animation may be coalesced** — advise pressing once per step. Not a bug, but a UX caveat.

## Rotating the entire graph (learned in production)

When the user wants the whole graph to rotate so a selected node moves to a side (e.g. right),
rotate ALL node positions around the graph center (0,0) — do not just pan the camera.

- **Store original positions** at load: `n.ox = n.x; n.oy = n.y;` (do this once, before any mutation).
- **Compute the rotation angle** from the selected node's *original* angle: `angle = atan2(n.oy, n.ox) * 180 / PI`; then `rot = -angle` (to bring it to 0°/right). Normalize to [-180, 180].
- **Apply rotation to every node**: `rx = ox*cos - oy*sin; ry = ox*sin + oy*cos;` then set `node.x=rx; node.y=ry;` and update the DOM transform attribute (`node._g.setAttribute('transform', 'translate(rx ry)')`).
- **Rebuild every edge's `d`** from the new node positions (Bezier control points depend on endpoints). Edges will snap (no CSS transition on `d`); nodes animate via CSS `transition: transform`.
- **Add CSS transition** on `.nd`: `transition: transform 0.6s cubic-bezier(.3,.7,.2,1), opacity .45s;` so the rotation is smooth.
- **Reset on "Fit"**: restore `node.x = node.ox; node.y = node.oy;` and rebuild edges, so the overview returns to the original layout.
- **Counter-rotate text if needed**: if text becomes unreadable after rotation, apply `transform: rotate(-rot)` to `.nd .in` (the inner group). In practice, since the graph rotates but the panel stays fixed, text may need counter-rotation for readability.
- **Position the selected node at 50% of available width (centered)**, not at 72%. The user preferred exact centering over right-side positioning. Centering keeps the selected node and its children fully visible with balanced spacing on both sides. Use `cam.x = (w[0]-pw)/2 - cam.k * n.x` for centering. Only use 72% right-side positioning if the user explicitly requests it.
- **Panel always on the right (both languages).** The side panel must stay on the right side regardless of language (FA or EN). Do NOT use `inset-inline-end` (which flips with RTL/LTR). Use `right: 14px` explicitly. The camera calculations must account for the panel on the right for BOTH languages — do NOT add RTL-specific `cam.x += pw` adjustments. The available graph area is always `W - pw` (panel on right, graph on left). Camera center: `cam.x = (W - pw)/2 - k * node.x`.
- **Text overflow on panel.** Add `word-wrap: break-word; overflow-wrap: break-word` to `#panel` to prevent long text from overflowing the container.

- **Status tags: all or none.** Either every node has a `status` field (ok/partial/pending) with a `note`, or none do. Mixing tagged and untagged nodes looks inconsistent. If the user says "remove verified tags", delete `status` and `note` from ALL nodes. If they say "add to all", every node must get a status + specific note (not boilerplate). Never leave a mix.

## Focus zoom and camera (learned in production)

- **Edge structure: 6 main units only.** Only the 6 main units (core, identity, key, protocol, guard, recovery) connect to root with normal-thickness lines (kind: branch). All other nodes connect to their parent with thinner lines (kind: thin, stroke-width: 1, opacity: 0.45). Remove ALL cross-cutting edges (ref, flow) — they clutter the graph. Detail nodes connect ONLY to their parent unit, never to other units or each other.
- **Column layout on main-unit selection.** When a main unit is selected: rotate graph so unit is at center, then reposition its children into a vertical column beside it. Children positions are relative to the main node's rotated position: `child.x = mainNode.x + 180` (not just 180 — the main node is at (r, 0) after rotation, not at (0, 0)). Equal spacing = 70px: `child.y = (i - (n-1)/2) * 70`. Non-main nodes: just center them (no rotation, no column). When a **child node** is selected (not a main unit): find its parent main unit (`N[id].parent` if it's in MAIN_UNITS), rotate THAT parent to center, column ITS children, and center the camera on the parent — do NOT rotate for the child itself. This avoids extra rotation when clicking sub-nodes.

**Important (user preference):** The user's preference depends on node type. For **detail nodes**: default to **centering** — do NOT rotate the graph, just center the selected node. For **main units** (core, identity, key, protocol, guard, recovery): **rotate + column layout** — rotate so the unit is at center, then reposition its children into a vertical column beside it. When they say "چیزی که سلکت میکنیم باید دقیقا وسط باشه" (selected should be exactly in center), they mean the selected node should be centered on screen regardless of type. Keep the rotation technique documented above for main units; use centering-only for detail nodes.

- **Default focus zoom is often too aggressive.** `go()` calling `focus(id, 1.25)` for detail nodes zooms in too close, hiding neighboring nodes. Use lower values: `focus(id, 0.85)` for detail nodes and `0.65` for units. This keeps the selected node visible with its children and siblings in frame.
- **fit() ("Fit" button) must reset rotation.** When the graph has been rotated (see above), fit() should restore all nodes to original positions (ox, oy), rebuild edges, and reset `cam.rot = 0` before computing the bounding box. Otherwise the overview shows a rotated, off-center graph.

## Node placement best practices (learned in production)

- **Check for overlaps** after adding nodes: compute bounding-box intersections; target 0 overlaps.
- **Compute min distance** to existing nodes; aim for >90px between detail nodes (hexagon radius ~68px).
- **Iterate positions**: propose a position, check min distance, adjust if <90px.
- **Detail nodes** at radius 500-720 from center; **biz nodes** at radius 100-180; **unit nodes** at radius ~300.
- **When adding cross-cutting edges** (ref/flow), ensure they represent real relationships (audit, monitoring, deployment) — not decorative connections. Each new edge should have a clear semantic reason.

## Files

- `scripts/build_deck.py` — builder (vendored from graph-deck engine)
- `viewer/viewer.template.html` — viewer engine (vanilla JS/SVG, offline)
- `examples/sample_presentation.html` — minimal build output
