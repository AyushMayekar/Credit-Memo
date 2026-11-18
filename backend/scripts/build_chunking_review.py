from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def esc(value: Any) -> str:
    return html.escape(str(value or ""))


def badge(label: str, bad: bool = False) -> str:
    return f'<span class="badge {"bad" if bad else "ok"}">{esc(label)}</span>'


def build(data: dict[str, Any]) -> str:
    parents = data.get("parents") or []
    children = data.get("children") or []
    tables = data.get("tables") or []
    audit = data.get("audit") or {}
    child_by_parent = defaultdict(list)
    table_by_parent = defaultdict(list)
    for child in children:
        child_by_parent[child.get("parent_chunk_id")].append(child)
    for table in tables:
        table_by_parent[table.get("parent_chunk_id")].append(table)

    metrics = [
        ("Status", audit.get("status")), ("Parents", len(parents)),
        ("Narrative children", len(children)), ("Table children", len(tables)),
        ("Max parent tokens", audit.get("max_parent_tokens")),
        ("Max child tokens", audit.get("max_child_tokens")),
        ("Max table tokens", audit.get("max_table_tokens")),
    ]
    cards = ''.join(f'<div class="metric"><b>{esc(v)}</b><span>{esc(k)}</span></div>' for k,v in metrics)
    issues = []
    for key in ("missing_record_ids", "missing_table_ids", "broken_parent_links", "duplicate_chunk_ids", "children_over_hard_limit", "parents_over_hard_limit", "tables_over_hard_limit"):
        if audit.get(key):
            issues.append(f'<li><b>{esc(key)}</b>: {esc(audit[key])}</li>')
    sections = [f'<section class="card"><h2>Run summary</h2><div class="metrics">{cards}</div><ul>{"".join(issues) or "<li>No audit failures.</li>"}</ul></section>']

    for parent in parents:
        pid = parent.get("chunk_id")
        over = int(parent.get("token_count") or 0) > 2700
        section_path = " &gt; ".join(parent.get("heading_path") or [])
        body = [f'''<section class="card item" data-kind="parent" data-text="{esc(section_path)}">
        <div class="top"><div><p class="eyebrow">Parent {esc(parent.get('parent_part_index'))}/{esc(parent.get('parent_part_count'))}</p><h2>{esc(pid)}</h2><p>{esc(section_path)}</p></div>{badge(str(parent.get('token_count'))+' tokens', over)}</div>
        <p class="muted">Pages {esc(parent.get('page_start'))}-{esc(parent.get('page_end'))} | Group {esc(parent.get('parent_group_id'))}</p>
        <details open><summary>LLM evidence packet: selected metadata + parent content</summary><pre>{esc(json.dumps(parent.get('metadata',{}).get('llm_metadata',{}),indent=2,ensure_ascii=False))}</pre><pre>{esc(parent.get('content_text'))}</pre></details>
        <p><b>Related parents:</b> {esc(', '.join(parent.get('related_parent_ids') or []) or 'None')}</p>
        <div class="children">''']
        for child in child_by_parent.get(pid, []):
            child_over = int(child.get("token_count") or 0) > 600
            body.append(f'''<article class="child item" data-kind="child"><div class="top"><h3>{esc(child.get('chunk_id'))}</h3>{badge(str(child.get('token_count'))+' tokens',child_over)}</div>
            <p class="muted">Pages {esc(child.get('page_start'))}-{esc(child.get('page_end'))} | Child part {esc(child.get('metadata',{}).get('child_part_index'))}/{esc(child.get('metadata',{}).get('child_part_count'))}</p>
            <pre>{esc(child.get('content_text'))}</pre><details><summary>LLM metadata, embedding text, and internal metadata</summary><pre>{esc(json.dumps(child.get('metadata',{}).get('llm_metadata',{}),indent=2,ensure_ascii=False))}</pre><pre>{esc(child.get('embedding_text'))}</pre><pre>{esc(json.dumps(child.get('metadata'),indent=2,ensure_ascii=False))}</pre></details></article>''')
        for table in table_by_parent.get(pid, []):
            table_over = int(table.get("token_count") or 0) > 1800
            body.append(f'''<article class="table item" data-kind="table"><div class="top"><h3>TABLE_DATA: {esc(table.get('chunk_id'))}</h3>{badge(str(table.get('token_count'))+' tokens',table_over)}</div>
            <p class="muted">Original table {esc(table.get('table_id'))} | Part {esc(table.get('table_part_index'))}/{esc(table.get('table_part_count'))} | Page {esc(table.get('page_start'))}</p>
            <pre>{esc(table.get('content_text'))}</pre><details><summary>LLM metadata, embedding text, and internal metadata</summary><pre>{esc(json.dumps(table.get('metadata',{}).get('llm_metadata',{}),indent=2,ensure_ascii=False))}</pre><pre>{esc(table.get('embedding_text'))}</pre><pre>{esc(json.dumps(table.get('metadata'),indent=2,ensure_ascii=False))}</pre></details></article>''')
        body.append('</div><label class="review"><input type="checkbox"> Parent, children, tables, order and pages are correct</label><textarea placeholder="Reviewer note"></textarea></section>')
        sections.append(''.join(body))

    css='''
    :root{--bg:#f5f7fb;--card:#fff;--line:#d8deea;--ink:#172033;--muted:#667085;--blue:#2563eb;--red:#b42318;--green:#067647}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,Segoe UI,Arial}header{position:sticky;top:0;z-index:5;background:#111827;color:#fff;padding:14px 20px;display:flex;gap:12px;align-items:center}header h1{font-size:18px;margin:0}header input,header select{padding:7px 9px;border-radius:6px;border:0}main{max-width:1200px;margin:auto;padding:20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}.metric{border:1px solid var(--line);padding:10px;border-radius:7px}.metric b,.metric span{display:block}.metric b{font-size:20px}.metric span,.muted{color:var(--muted)}.top{display:flex;justify-content:space-between;gap:16px}.eyebrow{text-transform:uppercase;font-size:11px;color:var(--blue);font-weight:700}.badge{padding:3px 8px;border-radius:999px;font-size:12px;white-space:nowrap}.ok{background:#ecfdf3;color:var(--green)}.bad{background:#fef3f2;color:var(--red)}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;border:1px solid var(--line);padding:10px;border-radius:7px;max-height:360px;overflow:auto}.children{display:grid;grid-template-columns:1fr;gap:10px}.child,.table{border-left:4px solid var(--blue);padding:12px;background:#fbfdff}.table{border-left-color:#7e22ce}.review{display:block;margin-top:12px;font-weight:600}textarea{width:100%;min-height:60px;margin-top:8px;padding:8px}.hidden{display:none}summary{cursor:pointer;font-weight:600}@media(max-width:600px){header{align-items:stretch;flex-direction:column}.top{flex-direction:column}}
    '''
    js='''
    const q=document.getElementById('q'),kind=document.getElementById('kind');function apply(){const s=q.value.toLowerCase();document.querySelectorAll('.item').forEach(x=>{const a=!s||x.innerText.toLowerCase().includes(s);const b=!kind.value||x.dataset.kind===kind.value;x.classList.toggle('hidden',!(a&&b));});}q.addEventListener('input',apply);kind.addEventListener('change',apply);
    '''
    return f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Chunking manual review</title><style>{css}</style></head><body><header><h1>Chunking Manual Review</h1><input id="q" placeholder="Search section, text, value or ID"><select id="kind"><option value="">All types</option><option value="parent">Parents</option><option value="child">Narrative children</option><option value="table">Table children</option></select></header><main>{''.join(sections)}</main><script>{js}</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an HTML review from chunking_output.json")
    parser.add_argument("chunking_output", type=Path)
    parser.add_argument("--output", type=Path, default=Path("chunking_manual_review.html"))
    args = parser.parse_args()
    data = json.loads(args.chunking_output.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build(data), encoding="utf-8")
    print(json.dumps({"input":str(args.chunking_output.resolve()),"output":str(args.output.resolve()),"parents":len(data.get('parents') or []),"children":len(data.get('children') or []),"tables":len(data.get('tables') or [])},indent=2))


if __name__ == "__main__":
    main()
