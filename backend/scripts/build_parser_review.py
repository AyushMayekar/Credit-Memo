from __future__ import annotations
import argparse, html, json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

CSS = r'''
:root{--bg:#f4f7fb;--card:#fff;--text:#172033;--muted:#667085;--line:#d7deea;--blue:#2563eb;--green:#15803d;--amber:#b45309;--red:#b91c1c;--purple:#7e22ce}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 system-ui,Segoe UI,Arial;color:var(--text);background:var(--bg)}
header{position:sticky;top:0;z-index:10;background:#111827;color:white;padding:14px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}header h1{font-size:18px;margin:0}.grow{flex:1}.controls{display:flex;gap:8px;flex-wrap:wrap}input,select,button{font:inherit;padding:7px 9px;border:1px solid #94a3b8;border-radius:6px;background:white;color:#111827}button{cursor:pointer}.layout{display:grid;grid-template-columns:280px minmax(0,1fr);min-height:calc(100vh - 62px)}
aside{padding:14px;border-right:1px solid var(--line);background:#eef2f7;overflow:auto}.main{padding:18px;min-width:0}.nav a{display:block;padding:7px 8px;color:#1f2937;text-decoration:none;border-radius:5px}.nav a:hover{background:#dbeafe}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:0 0 14px;box-shadow:0 1px 2px #0000000a}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.metric{padding:12px;background:#f8fafc;border:1px solid var(--line);border-radius:8px}.metric b{font-size:22px;display:block}.muted{color:var(--muted)}.badge{display:inline-block;padding:2px 7px;border-radius:999px;font-size:12px;font-weight:650}.ok{background:#dcfce7;color:var(--green)}.review{background:#fef3c7;color:var(--amber)}.bad{background:#fee2e2;color:var(--red)}.table-owned{background:#ede9fe;color:var(--purple)}
h2,h3{scroll-margin-top:75px}.section-path{font-weight:650;color:#1d4ed8}.record{white-space:pre-wrap;background:#f8fafc;border-left:4px solid #60a5fa;padding:10px;margin-top:8px}.warning{background:#fff7ed;border:1px solid #fdba74;padding:9px;border-radius:7px;margin:6px 0}.check{display:flex;gap:8px;align-items:flex-start;padding:7px 0}.check input{margin-top:3px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:7px}.table-wrap table{border-collapse:collapse;min-width:720px;width:100%;background:white}.table-wrap th,.table-wrap td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}.table-wrap th{background:#eaf0f8;position:sticky;top:0}.table-wrap td:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}.source{font-family:ui-monospace,Consolas,monospace;font-size:12px;max-height:180px;overflow:auto;background:#111827;color:#e5e7eb;padding:9px;border-radius:6px}details{margin-top:8px}summary{cursor:pointer;font-weight:650}.hidden{display:none!important}.page{scroll-margin-top:75px}.page-head{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap}.review-note{width:100%;min-height:60px;margin-top:8px;padding:8px;border:1px solid #94a3b8;border-radius:6px}.status-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.empty-cell{background:#f8fafc;color:#cbd5e1}.footer{padding:16px;color:var(--muted);text-align:center}@media(max-width:850px){.layout{grid-template-columns:1fr}aside{border-right:0;border-bottom:1px solid var(--line);max-height:260px}}
@media print{header,aside,.no-print{display:none!important}.layout{display:block}.main{padding:0}.card{break-inside:avoid;box-shadow:none}}
'''

JS = r'''
(() => {
 const root=document.getElementById('review-root');
 const q=document.getElementById('search'); const pf=document.getElementById('page-filter'); const tf=document.getElementById('type-filter');
 function apply(){const term=(q.value||'').toLowerCase();const page=pf.value;const type=tf.value;root.querySelectorAll('[data-review-item]').forEach(el=>{const okTerm=!term||el.innerText.toLowerCase().includes(term);const okPage=!page||el.dataset.page===page;const okType=!type||el.dataset.type===type;el.classList.toggle('hidden',!(okTerm&&okPage&&okType));});}
 [q,pf,tf].forEach(x=>x.addEventListener('input',apply));
 document.getElementById('only-issues').addEventListener('change',e=>{root.querySelectorAll('[data-review-item]').forEach(el=>{if(e.target.checked)el.classList.toggle('hidden',el.dataset.issue!=='1');else el.classList.remove('hidden');});if(!e.target.checked)apply();});
 document.getElementById('export-review').addEventListener('click',()=>{const data={reviewed_at:new Date().toISOString(),items:{}};root.querySelectorAll('[data-review-key]').forEach(el=>{const k=el.dataset.reviewKey;data.items[k]=data.items[k]||{};if(el.type==='checkbox')data.items[k][el.dataset.field]=el.checked;else data.items[k][el.dataset.field]=el.value;});const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='manual_review_decisions.json';a.click();URL.revokeObjectURL(a.href);});
 document.getElementById('expand-all').addEventListener('click',()=>root.querySelectorAll('details').forEach(x=>x.open=true));
 document.getElementById('collapse-all').addEventListener('click',()=>root.querySelectorAll('details').forEach(x=>x.open=false));
})();
'''

def esc(v: Any) -> str: return html.escape(str(v or ""))
def badge(value: str) -> str:
    c='ok' if value in {'ACCEPTED','KEEP','COMPLETED','VALID'} else 'review' if 'REVIEW' in value else 'table-owned' if value=='TABLE_OWNED' else 'bad'
    return f"<span class='badge {c}'>{esc(value)}</span>"

def simple_table(rows: list[list[Any]]) -> str:
    if not rows:return "<p class='muted'>No normalized rows.</p>"
    width=max(len(r) for r in rows); padded=[r+[None]*(width-len(r)) for r in rows]
    out=["<div class='table-wrap'><table><thead><tr>"]+[f"<th>{esc(x)}</th>" for x in padded[0]]+["</tr></thead><tbody>"]
    for row in padded[1:]:
        out.append('<tr>')
        for value in row: out.append(f"<td class='{'empty-cell' if value in (None,'') else ''}'>{esc(value)}</td>")
        out.append('</tr>')
    out.append('</tbody></table></div>');return ''.join(out)

def reconstructed_rows(table: dict[str,Any]) -> list[list[Any]]:
    cols=table.get('columns') or []; n=int(table.get('column_count') or len(cols)); hdr=['Row label']
    for i,c in enumerate(cols): hdr.append(' / '.join(c.get('header_path') or []) or f"Column {i+1}")
    rows=[hdr]
    for r in table.get('body_rows') or []: rows.append([r.get('label','')]+list(r.get('cells') or [None]*n))
    return rows

def build(payload: dict[str,Any]) -> str:
    pages=payload.get('pages') or []; sections=payload.get('sections') or []; records=payload.get('records') or []; tables=payload.get('tables') or []; decisions=payload.get('item_decisions') or []; audit=payload.get('audit') or {}
    rec_by_page=defaultdict(list); tab_by_page=defaultdict(list); dec_by_page=defaultdict(list)
    for x in records: rec_by_page[int(x.get('page_start') or 0)].append(x)
    for x in tables: tab_by_page[int(x.get('page_number') or 0)].append(x)
    for x in decisions: dec_by_page[int(x.get('page_number') or 0)].append(x)
    page_numbers=sorted({int(x.get('page_number') or 0) for x in pages})
    nav=''.join(f"<a href='#page-{p}'>Page {p}</a>" for p in page_numbers)
    options=''.join(f"<option value='{p}'>{p}</option>" for p in page_numbers)
    metrics=[('Pages',len(pages)),('Sections',len(sections)),('Narrative records',len(records)),('Tables',len(tables)),('Table-owned items',audit.get('table_owned_count',0)),('Garbage removed',audit.get('garbage_removed',0)),('Duplicates removed',audit.get('duplicate_removed',0))]
    summary=''.join(f"<div class='metric'><b>{v}</b><span class='muted'>{esc(k)}</span></div>" for k,v in metrics)
    out=[f"""<div id='review-root'><section class='card'><h2>Run summary</h2><div class='grid'>{summary}</div></section>
<section class='card'><h2>Manual review checklist</h2><div class='grid'>
<div><b>Extraction</b><div>Headings and paragraphs readable</div><div>Garbage removed correctly</div></div>
<div><b>Tables</b><div>Boundaries correct</div><div>Columns and values aligned</div><div>No narrative absorbed</div></div>
<div><b>Parsing</b><div>Section hierarchy correct</div><div>Continuation connected correctly</div><div>No table duplication in text</div></div>
</div></section>"""]
    out.append("<section class='card'><h2>Section hierarchy</h2>")
    for s in sections:
        path=' &gt; '.join(s.get('heading_path') or [s.get('title')]); issue=1 if not s.get('title') else 0
        out.append(f"<div data-review-item data-page='{s.get('page_start')}' data-type='section' data-issue='{issue}'><span class='section-path'>L{s.get('heading_level')} · {esc(path)}</span> <span class='muted'>pages {s.get('page_start')}-{s.get('page_end')}</span></div>")
    out.append('</section>')
    for p in page_numbers:
        page=next((x for x in pages if int(x.get('page_number') or 0)==p),{})
        issue=1 if page.get('garbage_removed') or any(t.get('warnings') for t in tab_by_page[p]) else 0
        out.append(f"<section class='card page' id='page-{p}' data-review-item data-page='{p}' data-type='page' data-issue='{issue}'><div class='page-head'><h2>Page {p}</h2><div>{badge('REVIEW_REQUIRED' if issue else 'ACCEPTED')}</div></div>")
        out.append(f"<p class='muted'>Kept: {page.get('kept_item_count',0)} · Table-owned: {page.get('table_owned_item_count',0)} · Garbage: {page.get('garbage_removed',0)} · Duplicates: {page.get('duplicate_removed',0)} · Furniture: {page.get('furniture_removed',0)}</p>")
        for r in rec_by_page[p]:
            key=f"record:{r.get('record_id')}"; path=' > '.join(r.get('heading_path') or [])
            out.append(f"<article class='card' data-review-item data-page='{p}' data-type='record' data-issue='{'1' if r.get('warnings') else '0'}'><h3>Narrative: {esc(r.get('section_title'))}</h3><div class='section-path'>{esc(path)}</div><div class='record'>{esc(r.get('content_text'))}</div><details><summary>Source trace</summary><div class='source'>{esc(json.dumps({'source_item_ids':r.get('source_item_ids'),'warnings':r.get('warnings'),'quality':r.get('quality_classification')},indent=2))}</div></details><div class='check no-print'><input type='checkbox' data-review-key='{esc(key)}' data-field='verified' id='{esc(key)}'><label for='{esc(key)}'>Narrative and section assignment verified</label></div><textarea class='review-note no-print' data-review-key='{esc(key)}' data-field='note' placeholder='Reviewer note'></textarea></article>")
        for t in tab_by_page[p]:
            key=f"table:{t.get('table_id')}"; warnings=t.get('warnings') or []; diag=t.get('column_detection') or {}; path=' > '.join(t.get('heading_path') or [])
            out.append(f"<article class='card' data-review-item data-page='{p}' data-type='table' data-issue='{'1' if warnings else '0'}'><h3>Table {esc(t.get('table_id'))} {badge(t.get('quality_classification',''))}</h3><div class='section-path'>{esc(path)}</div><p class='muted'>Region {esc(t.get('source_region_id'))} · Reading order {t.get('reading_order_start')}-{t.get('reading_order_end')} · Columns {t.get('column_count')} · Detection {esc(diag.get('method','unknown'))}</p>")
            for w in warnings:out.append(f"<div class='warning'>{esc(w)}</div>")
            out.append(simple_table(reconstructed_rows(t)))
            out.append(f"<details><summary>Diagnostics and source IDs</summary><div class='source'>{esc(json.dumps({'column_detection':diag,'source_item_ids':t.get('source_item_ids'),'source_bbox':t.get('source_bbox')},indent=2))}</div></details><div class='check no-print'><input type='checkbox' data-review-key='{esc(key)}' data-field='boundary_ok' id='{esc(key)}-b'><label for='{esc(key)}-b'>Boundary is correct</label></div><div class='check no-print'><input type='checkbox' data-review-key='{esc(key)}' data-field='values_ok' id='{esc(key)}-v'><label for='{esc(key)}-v'>Headers, rows and values are correct</label></div><textarea class='review-note no-print' data-review-key='{esc(key)}' data-field='note' placeholder='Reviewer note'></textarea></article>")
        counts=Counter(x.get('decision') for x in dec_by_page[p])
        out.append(f"<details><summary>Item decisions ({len(dec_by_page[p])})</summary><p>{' · '.join(f'{esc(k)}: {v}' for k,v in counts.items())}</p><div class='source'>{esc(json.dumps(dec_by_page[p],indent=2))}</div></details></section>")
    out.append("</div>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Pipeline manual review</title><style>{CSS}</style></head><body><header><h1>Pipeline Manual Review</h1><div class='grow'></div><div class='controls'><input id='search' aria-label='Search' placeholder='Search text, value or section'><select id='page-filter' aria-label='Page'><option value=''>All pages</option>{options}</select><select id='type-filter' aria-label='Type'><option value=''>All types</option><option value='section'>Sections</option><option value='record'>Narrative</option><option value='table'>Tables</option><option value='page'>Page cards</option></select><label><input id='only-issues' type='checkbox'>Issues only</label><button id='expand-all' type='button'>Expand</button><button id='collapse-all' type='button'>Collapse</button><button id='export-review' type='button'>Export decisions</button></div></header><div class='layout'><aside><h3>Pages</h3><nav class='nav'>{nav}</nav><hr><p class='muted'>Use checkboxes and notes while reviewing. “Export decisions” downloads a JSON review log.</p></aside><main class='main'>{''.join(out)}<div class='footer'>Generated from parsed_document.json</div></main></div><script>{JS}</script></body></html>"""

def main():
    p=argparse.ArgumentParser(description='Build a user-friendly manual review from Parser v8 output.')
    p.add_argument('parsed_document',type=Path);p.add_argument('--output',type=Path,default=Path('pipeline_manual_review.html'))
    a=p.parse_args();data=json.loads(a.parsed_document.read_text(encoding='utf-8'));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(build(data),encoding='utf-8')
    print(json.dumps({'input':str(a.parsed_document.resolve()),'output':str(a.output.resolve()),'pages':len(data.get('pages') or []),'sections':len(data.get('sections') or []),'records':len(data.get('records') or []),'tables':len(data.get('tables') or [])},indent=2))
if __name__=='__main__':main()
