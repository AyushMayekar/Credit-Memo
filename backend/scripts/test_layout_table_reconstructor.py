from __future__ import annotations
import argparse, html, json, webbrowser
from pathlib import Path
from typing import Any
import layout_table_reconstructor as core

def extract_items(payload: Any, page: int | None):
    if isinstance(payload,list): return payload
    if isinstance(payload,dict) and isinstance(payload.get('pages'),list):
        if page is None and len(payload['pages']) != 1: raise ValueError('Provide --page for a multi-page extraction.')
        selected=payload['pages'][0] if page is None else next((p for p in payload['pages'] if int(p.get('page_number',0))==page),None)
        if selected is None: raise ValueError(f'Page {page} not found.')
        return selected.get('items') or []
    if isinstance(payload,dict):
        for key in ('items','elements','content','blocks'):
            if isinstance(payload.get(key),list): return payload[key]
    raise ValueError('Unsupported input JSON structure.')

def filter_items(items, start, end, level, bbox):
    out=[]
    for item in items:
        order=int(item.get('reading_order',0)); h=int(item.get('hierarchy_level',0) or 0)
        if start is not None and order<start: continue
        if end is not None and order>end: continue
        if level is not None and h<level: continue
        if bbox:
            b=item.get('bbox') or {}; required={'left','right','top','bottom'}
            if not required.issubset(b): continue
            left,right=float(b['left']),float(b['right']); lo,hi=sorted((float(b['top']),float(b['bottom'])))
            rl,rb,rr,rt=bbox
            if right<rl or left>rr or hi<rb or lo>rt: continue
        out.append(item)
    return sorted(out,key=lambda x:int(x.get('reading_order',0)))

def render_html(table, markdown, title):
    count=int(table.get('column_count',0)); rows=[]
    for row in (table.get('header_rows') or []):
        cells=[row.get('label'),*(row.get('cells') or [])]; cells += [None]*max(0,count+1-len(cells))
        rows.append('<tr class="head">'+''.join('<td>'+html.escape(str(v or ''))+'</td>' for v in cells[:count+1])+'</tr>')
    for row in (table.get('body_rows') or []):
        cells=[row.get('label'),*(row.get('cells') or [])]; cells += [None]*max(0,count+1-len(cells))
        klass='section' if row.get('row_type')=='section' else 'body'
        rows.append('<tr class="'+klass+'">'+''.join('<td>'+html.escape(str(v or ''))+'</td>' for v in cells[:count+1])+'</tr>')
    heads=['Row label']+[f'Column {i+1}<br><small>x={table["columns"][i]["x_center"]}</small>' for i in range(count)]
    warns=''.join('<li>'+html.escape(str(w))+'</li>' for w in table.get('warnings',[])) or '<li>None</li>'
    css='body{font-family:Arial;margin:24px;color:#222}.wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;min-width:850px}th,td{border:1px solid #999;padding:7px}th{background:#e9eef5}td:first-child{text-align:left;min-width:260px}td:not(:first-child){text-align:right;min-width:100px}.head td{background:#f4f6f8;font-weight:600}.section td:first-child{font-weight:700;background:#f8f8f8}.warning{background:#fff5cc;padding:12px;border:1px solid #d6ba55}pre{white-space:pre-wrap;background:#f6f6f6;padding:12px;border:1px solid #ddd}'
    return '<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>'+css+'</style><h1>'+html.escape(title)+'</h1><p>Columns: '+str(count)+' | Body rows: '+str(len(table.get('body_rows') or []))+'</p><div class="wrap"><table><thead><tr>'+''.join('<th>'+h+'</th>' for h in heads)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div><h2>Warnings</h2><div class="warning"><ul>'+warns+'</ul></div><h2>Markdown</h2><pre>'+html.escape(markdown)+'</pre>'

def main():
    p=argparse.ArgumentParser(description='Test the unchanged layout table reconstruction algorithm.')
    p.add_argument('input_json',type=Path); p.add_argument('--page',type=int); p.add_argument('--reading-start',type=int); p.add_argument('--reading-end',type=int); p.add_argument('--min-hierarchy',type=int)
    p.add_argument('--bbox',nargs=4,type=float,metavar=('LEFT','BOTTOM','RIGHT','TOP')); p.add_argument('--x-tolerance',type=float,default=13.0); p.add_argument('--y-tolerance',type=float,default=None)
    p.add_argument('--output-dir',type=Path,default=Path('table-test-output')); p.add_argument('--name',default='reconstructed_table'); p.add_argument('--open',action='store_true'); a=p.parse_args()
    payload=json.loads(a.input_json.read_text(encoding='utf-8')); items=extract_items(payload,a.page)
    selected=filter_items(items,a.reading_start,a.reading_end,a.min_hierarchy,tuple(a.bbox) if a.bbox else None)
    if not selected: raise SystemExit('No items remained after filtering.')
    a.output_dir.mkdir(parents=True,exist_ok=True)
    selected_path=a.output_dir/f'{a.name}_selected_items.json'; selected_path.write_text(json.dumps(selected,indent=2,ensure_ascii=False),encoding='utf-8')
    table=core.reconstruct_table(selected,y_tolerance=a.y_tolerance,x_tolerance=a.x_tolerance); md=core.to_layout_markdown(table); llm=core.build_llm_payload(table)
    jp=a.output_dir/f'{a.name}.json'; mp=a.output_dir/f'{a.name}.md'; lp=a.output_dir/f'{a.name}_llm.json'; hp=a.output_dir/f'{a.name}.html'; sp=a.output_dir/f'{a.name}_summary.json'
    jp.write_text(json.dumps(table,indent=2,ensure_ascii=False),encoding='utf-8'); mp.write_text(md,encoding='utf-8'); lp.write_text(json.dumps(llm,indent=2,ensure_ascii=False),encoding='utf-8'); hp.write_text(render_html(table,md,a.name),encoding='utf-8')
    summary={'page':a.page,'selected_item_count':len(selected),'reading_order_min':min(int(x.get('reading_order',0)) for x in selected),'reading_order_max':max(int(x.get('reading_order',0)) for x in selected),'column_count':table.get('column_count'),'header_row_count':len(table.get('header_rows') or []),'body_row_count':len(table.get('body_rows') or []),'warning_count':len(table.get('warnings') or []),'outputs':{'selected_items':str(selected_path.resolve()),'json':str(jp.resolve()),'markdown':str(mp.resolve()),'llm_payload':str(lp.resolve()),'html':str(hp.resolve())}}
    sp.write_text(json.dumps(summary,indent=2),encoding='utf-8'); print(json.dumps(summary,indent=2))
    if a.open:webbrowser.open(hp.resolve().as_uri())
if __name__=='__main__':main()
