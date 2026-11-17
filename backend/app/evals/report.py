import html, json


def write(out, payload):
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    rows = []
    for r in payload["results"]:
        bad = [c for c in r["checks"] if not c["passed"]]
        detail = "".join(
            "<li>" + html.escape(c["name"] + ": " + c.get("detail", "")) + "</li>"
            for c in bad
        )
        rows.append(
            "<tr><td>"
            + html.escape(r["case_id"])
            + "</td><td>"
            + r["status"]
            + "</td><td>"
            + html.escape(str(r.get("layer") or ""))
            + "</td><td><ul>"
            + detail
            + "</ul></td></tr>"
        )
    page = (
        '<!doctype html><meta charset="utf-8"><title>AI evaluation</title><style>body{font:14px Arial;margin:24px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #aaa;padding:8px;vertical-align:top}th{background:#eee}</style><h1>Credit Memo AI Evaluation</h1><pre>'
        + html.escape(json.dumps(payload["metrics"], indent=2))
        + "</pre><table><tr><th>Case</th><th>Status</th><th>Layer</th><th>Failures</th></tr>"
        + "".join(rows)
        + "</table>"
    )
    (out / "report.html").write_text(page, encoding="utf-8")
