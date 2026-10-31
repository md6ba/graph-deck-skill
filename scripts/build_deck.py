#!/usr/bin/env python3
"""graph-deck build: deck.json -> one standalone, offline, interactive HTML file.

usage: build.py deck.json -o out.html [--font Vazirmatn.woff2] [--strict]

deck.json (see SKILL.md for the full schema):
  meta   {title:{fa,en}, lang, logo}
  nodes  [{id,kind(root|unit|biz|detail),parent,title,sub,status,note,blocks,src,x?,y?}]
  edges  [{from,to,kind(ref|flow|branch),label?}]   # parent->child edges are automatic
  paths  [{id,title,nodes:[ids]}]
  tour   [ids]                                      # presentation order
"""
import argparse, base64, json, math, mimetypes, sys
from pathlib import Path

RANK = {"ok": 0, "partial": 1, "pending": 2}
HERE = Path(__file__).resolve().parent


def data_uri(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def layout(nodes):
    """Radial brand-map layout. root at (0,0); units on a hexagon ring; biz between
    units on an inner ring; details fan out behind their unit. Explicit x/y wins."""
    by = {n["id"]: n for n in nodes}
    units = [n for n in nodes if n["kind"] == "unit"]
    bizs = [n for n in nodes if n["kind"] == "biz"]
    R_UNIT, R_BIZ, R_DET = 300, 165, 520

    def put(n, ang, r):
        if "x" not in n:
            n["x"] = round(r * math.cos(math.radians(ang)), 1)
            n["y"] = round(r * math.sin(math.radians(ang)), 1)

    root = next(n for n in nodes if n["kind"] == "root")
    root.setdefault("x", 0)
    root.setdefault("y", 0)
    step = 360 / max(len(units), 1)
    for i, u in enumerate(units):
        ang = -90 + step * i
        put(u, ang, R_UNIT)
        u["_ang"] = ang
    bstep = 360 / max(len(bizs), 1)
    for i, b in enumerate(bizs):  # inner ring, between two units
        put(b, -90 + step / 2 + bstep * i, R_BIZ)
    for u in units:
        kids = [n for n in nodes if n.get("parent") == u["id"] and n["kind"] == "detail"]
        m = len(kids)
        for k, d in enumerate(kids):
            off = 0 if m == 1 else -25 + 50 * k / (m - 1)
            put(d, u["_ang"] + off, R_DET + (k % 2) * 112)
    for n in nodes:
        n.pop("_ang", None)
        if "x" not in n:
            sys.exit(f"layout: node '{n['id']}' has no position (orphan parent?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("deck")
    ap.add_argument("-o", "--out", default="deck.html")
    ap.add_argument("--font", help="woff2 file to embed (e.g. Vazirmatn)")
    ap.add_argument("--strict", action="store_true", help="treat warnings as errors")
    a = ap.parse_args()

    deck_path = Path(a.deck).resolve()
    base = deck_path.parent
    D = json.loads(deck_path.read_text(encoding="utf-8"))
    nodes, errs, warns = D["nodes"], [], []
    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        errs.append("duplicate node ids")
    by = {n["id"]: n for n in nodes}
    if sum(n["kind"] == "root" for n in nodes) != 1:
        errs.append("exactly one node of kind 'root' is required")

    # defaults + status roll-up (unit = worst child, capped at 'partial')
    for n in nodes:
        p = n.get("parent")
        if p and p not in by:
            errs.append(f"{n['id']}: unknown parent '{p}'")
        if n["kind"] != "root" and not p:
            n["parent"] = next(r["id"] for r in nodes if r["kind"] == "root")
    inv = {"ok", "partial", "pending"}
    for n in nodes:
        kids = [c for c in nodes if c.get("parent") == n["id"] and c.get("status")]
        if n["kind"] == "unit" and "status" not in n and kids:
            w = max(kids, key=lambda c: RANK[c["status"]])["status"]
            n["status"] = "partial" if w == "pending" else w
            if n["status"] != "ok" and not n.get("note"):
                n["note"] = {"fa": "این واحد دست‌کم یک زیرگرهٔ ناتمام یا در انتظار دارد؛ جزئیات را در زیرگره‌ها ببینید.",
                             "en": "This unit has at least one partial or pending sub-node; see its sub-nodes for details."}
        if n.get("status") and n["status"] not in inv:
            errs.append(f"{n['id']}: bad status '{n['status']}'")
        if n.get("status", "ok") != "ok" and n["kind"] != "root" and not n.get("note"):
            warns.append(f"{n['id']}: status '{n['status']}' without a 'note' explaining why")

    layout(nodes)

    # edges: automatic parent->child + declared
    edges = [{"from": n["parent"], "to": n["id"], "kind": "branch"} for n in nodes if n["kind"] != "root"]
    for e in D.get("edges", []):
        e.setdefault("kind", "ref")
        edges.append(e)
    for e in edges:
        for s in ("from", "to"):
            if e[s] not in by:
                errs.append(f"edge references unknown node '{e[s]}'")

    # reachability (no orphans)
    seen, stack = set(), [next(n["id"] for n in nodes if n["kind"] == "root")]
    adj = {}
    for e in edges:
        if e["from"] in by and e["to"] in by:
            adj.setdefault(e["from"], []).append(e["to"])
            adj.setdefault(e["to"], []).append(e["from"])
    while stack:
        i = stack.pop()
        if i not in seen:
            seen.add(i)
            stack.extend(adj.get(i, []))
    for i in ids:
        if i not in seen:
            errs.append(f"orphan node (unreachable from root): {i}")

    for p in D.get("paths", []):
        for i in p["nodes"]:
            if i not in by:
                errs.append(f"path '{p['id']}': unknown node '{i}'")
    D.setdefault("tour", [n["id"] for n in nodes if n["kind"] in ("root", "unit")])
    for i in D["tour"]:
        if i not in by:
            errs.append(f"tour: unknown node '{i}'")

    # assets -> data URIs
    def inline(rel):
        f = (base / rel).resolve()
        if not f.exists():
            errs.append(f"missing asset: {rel}")
            return ""
        return data_uri(f)

    meta = D.setdefault("meta", {})
    if meta.get("logo"):
        meta["logo"] = inline(meta["logo"])
    for n in nodes:
        for b in n.get("blocks", []):
            if b.get("type") == "image":
                b["src"] = inline(b["src"])
            if b.get("type") not in ("text", "list", "code", "image", "link"):
                errs.append(f"{n['id']}: unknown block type '{b.get('type')}'")
            if b.get("type") == "link" and str(b.get("href", "")).startswith("http") is False and not b.get("href"):
                errs.append(f"{n['id']}: link without href")
    D["edges"] = edges

    for w in warns:
        print("WARN ", w)
    if errs or (a.strict and warns):
        for e in errs:
            print("ERROR", e)
        sys.exit(1)

    font_css = ""
    if a.font:
        font_css = ("@font-face{font-family:Vazirmatn;font-display:swap;src:url(%s) format('woff2')}"
                    % data_uri(Path(a.font)))
    tpl = (HERE.parent / "viewer" / "viewer.template.html").read_text(encoding="utf-8")
    title = meta.get("title", {})
    title = title if isinstance(title, str) else title.get(meta.get("lang", "fa"), "")
    blob = json.dumps(D, ensure_ascii=False).replace("</", "<\\/")
    html = (tpl.replace("/*__FONT__*/", font_css).replace("__TITLE__", title)
            .replace("/*__DECK__*/", blob))
    out = Path(a.out)
    out.write_text(html, encoding="utf-8")
    print(f"OK  {out}  {out.stat().st_size/1024:.0f} KB  nodes={len(nodes)} edges={len(edges)} "
          f"paths={len(D.get('paths', []))} tour={len(D['tour'])}")


if __name__ == "__main__":
    main()
