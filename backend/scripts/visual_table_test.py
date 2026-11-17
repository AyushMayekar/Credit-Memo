"""Run reconstruction and create a visual HTML inspection page.

This is the test/visualization companion to layout_table_reconstructor.py.
It supports nested extraction JSON, page selection, reading-order filtering,
optional bbox filtering, JSON/Markdown/HTML outputs, and browser preview.
"""
from __future__ import annotations
import argparse
import html
import json
import webbrowser
from pathlib import Path
from typing import Any
import layout_table_reconstructor as core


def get_page_items(payload: Any, page: int | None) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        raise ValueError("Unsupported JSON root; expected an object or list.")
    pages = payload.get("pages")
    if isinstance(pages, list):
        if page is None:
            if len(pages) != 1:
                raise ValueError("This file has multiple pages; provide --page.")
            selected = pages[0]
        else:
            selected = next((p for p in pages if int(p.get("page_number", -1)) == page), None)
            if selected is None:
                raise ValueError(f"Page {page} was not found.")
        return selected.get("items", [])
    for key in ("items", "elements", "content", "blocks"):
        if isinstance(payload.get(key), list):
            return payload[key]
    raise ValueError("Could not find pages[].items or an items/elements/content/blocks list.")


def filter_items(items: list[dict[str, Any]], start: int | None, end: int | None,
                 bbox: tuple[float, float, float, float] | None) -> list[dict[str, Any]]:
    selected = []
    for item in items:
        order = int(item.get("reading_order", 0) or 0)
        if start is not None and order < start:
            continue
        if end is not None and order > end:
            continue
        if bbox is not None:
            b = item.get("bbox") or item.get("bounding_box") or {}
            if not all(k in b for k in ("left", "right", "top", "bottom")):
                continue
            left, right = sorted((float(b["left"]), float(b["right"])))
            bottom, top = sorted((float(b["bottom"]), float(b["top"])))
            ql, qb, qr, qt = bbox
            # Keep items whose bounding boxes intersect the requested rectangle.
            if right < ql or left > qr or top < qb or bottom > qt:
                continue
        selected.append(item)
    return sorted(selected, key=lambda x: int(x.get("reading_order", 0) or 0))


def render_html(table: dict[str, Any], title: str) -> str:
    cols = table["columns"]
    n = len(cols)
    out = ["""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Table reconstruction review</title><style>
body{font:14px/1.45 system-ui,Arial,sans-serif;margin:24px;color:#20242a;background:#fafafa}h1,h2{margin:0 0 12px}.meta{color:#596273;margin-bottom:18px}.wrap{overflow:auto;background:white;border:1px solid #ccd2da;border-radius:9px}table{border-collapse:collapse;width:100%;min-width:850px}th,td{border:1px solid #d8dde4;padding:8px 10px;vertical-align:top}th{background:#edf1f6;position:sticky;top:0}td:first-child{text-align:left;min-width:240px}td:not(:first-child){text-align:right;min-width:90px;font-variant-numeric:tabular-nums}.section td{background:#f4f5f7;font-weight:700;text-align:left}.total td{font-weight:700;background:#f8fafc}.warnings{margin:18px 0;padding:12px 16px;background:#fff4d7;border:1px solid #e4c66e;border-radius:8px}.small{font-size:12px;color:#667085}.debug{margin-top:22px}details{margin:8px 0;background:white;border:1px solid #d8dde4;border-radius:7px;padding:10px}pre{overflow:auto;white-space:pre-wrap;word-break:break-word}
</style></head><body>"""]
    out.append(f"<h1>{html.escape(title)}</h1>")
    out.append(f"<div class='meta'>Detected {n} numeric columns · {len(table['body_rows'])} reconstructed rows · {table.get('metadata', {}).get('element_count', sum(len(r.get('source_item_ids', [])) for r in table.get('body_rows', [])))} source elements</div>")
    out.append("<div class='wrap'><table><thead><tr><th>Row label</th>")
    for c in cols:
        out.append(f"<th>Column {c['column_id']+1}<div class='small'>right edge x={c['x_center']}</div></th>")
    out.append("</tr></thead><tbody>")
    for header in table.get("header_rows", []):
        vals = list(header.get("cells") or [None] * n)
        for span in header.get("spans", []):
            indices = span.get("column_indices", [])
            if indices and 0 <= indices[0] < n and not vals[indices[0]]:
                vals[indices[0]] = span.get("text")
        vals = [header.get("label", "")] + vals
        out.append("<tr class='head'>" + "".join(f"<td>{html.escape(str(v or ''))}</td>" for v in vals[:n+1]) + "</tr>")
    for row in table["body_rows"]:
        typ = row.get("row_type", "data")
        out.append(f"<tr class='{html.escape(typ)}'><td>{html.escape(row.get('label',''))}</td>")
        for value in row.get("cells", []):
            out.append(f"<td>{html.escape('' if value is None else str(value))}</td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    out.append("<div class='warnings'><b>Warnings</b><ul>")
    if table.get("warnings"):
        out.extend(f"<li>{html.escape(w)}</li>" for w in table["warnings"])
    else:
        out.append("<li>None reported by automated checks. Visual verification is still required.</li>")
    out.append("</ul></div>")
    out.append("<div class='debug'><h2>Reconstruction diagnostics</h2>")
    out.append(f"<details><summary>Header/source elements ({sum(len(r.get('source_item_ids', [])) for r in table.get('header_rows', []))})</summary><pre>{html.escape(json.dumps(table.get('header_rows', []), indent=2, ensure_ascii=False))}</pre></details>")
    out.append(f"<details><summary>Cell assignments ({len(table.get('cell_assignments', []))})</summary><pre>{html.escape(json.dumps(table.get('cell_assignments') or [a for r in table.get('body_rows', []) for a in r.get('assignments', [])], indent=2, ensure_ascii=False))}</pre></details>")
    out.append("</div></body></html>")
    return "".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Reconstruct a table and create an HTML visual review.")
    p.add_argument("input_json", type=Path)
    p.add_argument("--page", type=int)
    p.add_argument("--reading-start", type=int)
    p.add_argument("--reading-end", type=int)
    p.add_argument("--bbox", nargs=4, type=float, metavar=("LEFT", "BOTTOM", "RIGHT", "TOP"))
    p.add_argument("--x-tolerance", type=float, default=7.0)
    p.add_argument("--y-tolerance", type=float)
    p.add_argument("--output-dir", type=Path, default=Path("table-review"))
    p.add_argument("--name", default="table")
    p.add_argument("--open", action="store_true", help="Open generated HTML in the default browser.")
    a = p.parse_args()

    payload = json.loads(a.input_json.read_text(encoding="utf-8"))
    items = get_page_items(payload, a.page)
    selected = filter_items(items, a.reading_start, a.reading_end, tuple(a.bbox) if a.bbox else None)
    if not selected:
        raise SystemExit("No items remain after applying the filters.")

    table = core.reconstruct_table(selected, x_tolerance=a.x_tolerance, y_tolerance=a.y_tolerance)
    md = core.markdown_table(table)
    outdir = a.output_dir
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {
        "selected_items": outdir / f"{a.name}_selected.json",
        "json": outdir / f"{a.name}.json",
        "markdown": outdir / f"{a.name}.md",
        "html": outdir / f"{a.name}.html",
    }
    paths["selected_items"].write_text(json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["json"].write_text(json.dumps(table, indent=2, ensure_ascii=False), encoding="utf-8")
    paths["markdown"].write_text(md, encoding="utf-8")
    paths["html"].write_text(render_html(table, a.name), encoding="utf-8")
    summary = {"input": str(a.input_json.resolve()), "page": a.page,
               "selected_item_count": len(selected),
               "reading_order_range": [min(int(x.get('reading_order',0)) for x in selected), max(int(x.get('reading_order',0)) for x in selected)],
               "column_count": table["column_count"], "row_count": len(table["body_rows"]),
               "warning_count": len(table["warnings"]),
               "outputs": {k: str(v.resolve()) for k,v in paths.items()}}
    (outdir / f"{a.name}_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if a.open:
        webbrowser.open(paths["html"].resolve().as_uri())

if __name__ == "__main__":
    main()
