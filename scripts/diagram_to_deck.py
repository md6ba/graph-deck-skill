#!/usr/bin/env python3
"""Stage 1-2 bridge: a base diagram becomes a deck.json.

Inputs (any of):
  --diagram-json   output of the `repo-to-architecture-diagram` skill
                   ({"graph": {nodes, edges, groups}, "title", "description"})
  --mermaid        a raw .mmd file (flowchart/graph) — nodes and edges are parsed
  --content        a content map ({"nodes": {id: {title, body, ...}}})
  --root           which node id starts the deck (default: the first node)
  --title/--lang   deck meta

Output: a deck.json accepted by scripts/build_deck.py.

Mapping (diagram -> deck):
  * the root node becomes kind=root
  * every group becomes kind=unit, its nodes kind=detail (parent = the group)
  * nodes without a group become kind=unit (so nothing is orphaned)
  * every edge becomes an edge (parent->child edges are added by the builder)
  * node `path` becomes `src` (evidence) and `description` becomes a text block
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ARROWS = ("-->", "---", "-.->", "==>", "-.-")
NODE_DECL_RE = re.compile(r"^\s*([A-Za-z][\w-]*)\s*[\[\{\(]")
EDGE_RE = re.compile(
    r"^\s*([A-Za-z][\w-]*)\s*(?:\|[^|]*\|)?\s*(-{2,3}>|={2,3}>|-\.->|-{2,3}|={2,3})"
    r"\s*(?:\|[^|]*\|)?\s*([A-Za-z][\w-]*)"
)
SUBGRAPH_RE = re.compile(r"^\s*(subgraph|end|classDef|class|style|linkStyle|click)\b")


class BridgeError(Exception):
    pass


# --------------------------------------------------------------------------- #
# inputs
# --------------------------------------------------------------------------- #
def parse_mermaid(source: str) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    labels: dict[str, str] = {}
    seen: set[str] = set()

    for raw in source.splitlines():
        line = "" if raw.lstrip().startswith("%%") else raw.split("%%")[0].rstrip()
        if not line.strip() or SUBGRAPH_RE.match(line):
            continue
        edge = EDGE_RE.match(line)
        if edge:
            left, arrow, right = edge.group(1), edge.group(2), edge.group(3)
            for endpoint in (left, right):
                if endpoint not in seen:
                    seen.add(endpoint)
                    nodes.append({"id": endpoint})
            edges.append({"from": left, "to": right,
                          "kind": "ref" if "-." in arrow else "flow"})
            continue
        decl = NODE_DECL_RE.match(line)
        if decl:
            node_id = decl.group(1)
            if node_id not in seen:
                seen.add(node_id)
                nodes.append({"id": node_id})
            label = re.search(r'["\[\{\(]([^"\]\}\)]{1,160})["\]\}\)]', line)
            if label:
                labels[node_id] = label.group(1).strip()

    return {"nodes": nodes, "edges": edges, "labels": labels}


def load_diagram_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalise a raw diagram-skill payload into the internal shape."""
    graph = payload.get("graph") or payload
    groups = {g["id"]: g.get("label") or g["id"] for g in graph.get("groups", [])}
    nodes = [{
        "id": n["id"],
        "label": n.get("label") or n["id"],
        "group": n.get("group") or "",
        "path": n.get("path") or "",
        "description": n.get("description") or "",
    } for n in graph.get("nodes", [])]
    return {
        "nodes": nodes,
        "edges": [{"from": e["from"], "to": e["to"],
                   "kind": "flow" if e.get("label") else "ref"}
                  for e in graph.get("edges", [])],
        "groups": groups,
        "labels": {n["id"]: n["label"] for n in nodes},
        "title": payload.get("title") or "Graph Presentation",
        "description": payload.get("description") or "",
    }


def load_diagram(args: argparse.Namespace) -> dict[str, Any]:
    """Return {nodes, edges, groups, labels, title, description}."""
    if args.diagram_json:
        payload = json.loads(Path(args.diagram_json).read_text(encoding="utf-8"))
        return load_diagram_payload(payload)
    if args.mermaid:
        parsed = parse_mermaid(Path(args.mermaid).read_text(encoding="utf-8"))
        return {"nodes": [{"id": n["id"], "label": parsed["labels"].get(n["id"], n["id"]),
                           "group": "", "path": "", "description": ""} for n in parsed["nodes"]],
                "edges": parsed["edges"], "groups": {},
                "labels": parsed["labels"],
                "title": args.title, "description": ""}
    raise BridgeError("give --diagram-json or --mermaid")


# --------------------------------------------------------------------------- #
# mapping
# --------------------------------------------------------------------------- #
def build_deck(diagram: dict[str, Any], args: argparse.Namespace,
               content: dict[str, Any] | None) -> dict[str, Any]:
    # accept a dict of options as well as an argparse.Namespace
    if isinstance(args, dict):
        args = argparse.Namespace(**{"root": None, "lang": "fa", "title": "T", **args})
    # accept both a loaded diagram and a raw diagram-skill payload ({"graph": ...})
    if "graph" in diagram:
        diagram = load_diagram_payload(diagram)
    nodes_raw = diagram["nodes"]
    if not nodes_raw:
        raise BridgeError("the diagram has no nodes")

    ids = [n["id"] for n in nodes_raw]
    if len(ids) != len(set(ids)):
        raise BridgeError("duplicate node ids in the diagram")
    id_set = set(ids)

    content_nodes = (content or {}).get("nodes") or {}
    root_id = args.root or ids[0]
    if root_id not in id_set:
        raise BridgeError(f"root {root_id!r} is not a node of the diagram")

    groups = diagram.get("groups") or {}
    used_groups = sorted({n["group"] for n in nodes_raw if n["group"]})

    # group nodes -> units; ungrouped nodes become units of their own
    unit_ids: list[str] = []
    if groups and used_groups:
        unit_ids = [g for g in groups if g in set(used_groups)]
    for n in nodes_raw:
        if n["id"] == root_id:
            continue
        if not n["group"] and n["id"] not in unit_ids:
            unit_ids.append(n["id"])

    deck_nodes: list[dict[str, Any]] = []
    # synthetic unit node per group, so every group is a real, clickable node
    for gid in unit_ids:
        if gid in id_set:
            continue
        label = groups.get(gid) or gid
        deck_nodes.append({
            "id": gid, "kind": "unit", "parent": root_id,
            "title": {"fa": label, "en": label},
            "sub": {"fa": "", "en": ""},
            "blocks": [], "src": [],
        })

    for n in nodes_raw:
        cid = content_nodes.get(n["id"]) or {}
        title = (cid.get("title") or n["label"] or n["id"])
        if n["id"] == root_id:
            kind, parent = "root", None
        elif n["id"] in unit_ids:
            kind, parent = "unit", root_id
        else:
            kind = "detail"
            parent = n["group"] if n["group"] in unit_ids else root_id

        blocks: list[dict[str, Any]] = []
        body = cid.get("body") or cid.get("markdown") or n.get("description") or ""
        if body:
            blocks.append({"type": "text", "text": {"fa": body, "en": body}})
        for item in cid.get("list") or []:
            blocks.append({"type": "list",
                           "items": {"fa": item if isinstance(item, list) else [item],
                                     "en": item if isinstance(item, list) else [item]}})
        if cid.get("code"):
            blocks.append({"type": "code", "code": str(cid["code"])})
        if cid.get("link", {}).get("url") if isinstance(cid.get("link"), dict) else cid.get("link"):
            link = cid.get("link")
            blocks.append({"type": "link",
                           "href": link if isinstance(link, str) else link.get("url", ""),
                           "label": {"fa": (link if isinstance(link, str) else link.get("label", "")) or "link",
                                     "en": (link if isinstance(link, str) else link.get("label", "")) or "link"}})
        if cid.get("image"):
            image = cid["image"]
            blocks.append({"type": "image",
                           "src": image if isinstance(image, str) else image.get("src", ""),
                           "alt": {"fa": "", "en": ""}})

        src = cid.get("src") or ([n["path"]] if n.get("path") else [])
        deck_nodes.append({
            "id": n["id"], "kind": kind, "title": {"fa": title, "en": title},
            "sub": {"fa": groups.get(n["group"], "") if n["group"] else "",
                    "en": groups.get(n["group"], "") if n["group"] else ""},
            "blocks": blocks,
            "src": src,
            **({"parent": parent} if parent else {}),
        })

    # every unit is a path; the tour walks root -> units -> their details
    order = {"root": 0, "unit": 1, "biz": 2, "detail": 3}
    deck_nodes.sort(key=lambda n: (order[n["kind"]], n["id"]))

    deck = {
        "meta": {"title": {"fa": args.title, "en": args.title},
                 "lang": args.lang,
                 **({"description": diagram.get("description", "")} if diagram.get("description") else {})},
        "nodes": deck_nodes,
        "edges": [e for e in diagram["edges"]
                  if e["from"] in id_set and e["to"] in id_set],
        "paths": [{"id": u, "title": {"fa": u, "en": u},
                   "nodes": [root_id, u] + [n["id"] for n in deck_nodes
                                            if n.get("parent") == u and n["kind"] == "detail"]}
                  for u in unit_ids],
        "tour": [n["id"] for n in deck_nodes if n["kind"] in ("root", "unit")],
    }
    return deck


# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Turn a base diagram into a deck.json")
    p.add_argument("--diagram-json", help="output of the repo-to-architecture-diagram skill")
    p.add_argument("--mermaid", help="raw .mmd source")
    p.add_argument("--content", help="content map JSON ({\"nodes\": {id: {...}}})")
    p.add_argument("--root", help="starting node id")
    p.add_argument("--lang", choices=("fa", "en"), default="fa")
    p.add_argument("--title", default="Graph Presentation")
    p.add_argument("-o", "--out", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        diagram = load_diagram(args)
        content = json.loads(Path(args.content).read_text(encoding="utf-8")) if args.content else None
        deck = build_deck(diagram, args, content)
    except (BridgeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"code": "bridge_failed", "message": str(exc)}), file=sys.stderr)
        return 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(deck, ensure_ascii=False, indent=1), encoding="utf-8")
    kinds = {k: sum(1 for n in deck["nodes"] if n["kind"] == k) for k in ("root", "unit", "biz", "detail")}
    print(f"OK  {out}  nodes={len(deck['nodes'])} {kinds} "
          f"edges={len(deck['edges'])} paths={len(deck['paths'])} tour={len(deck['tour'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
