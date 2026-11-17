from __future__ import annotations
import argparse, json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--parsed", required=True, type=Path)
a = p.parse_args()
d = json.loads(a.parsed.read_text(encoding="utf-8"))
print("Sections:", len(d["sections"]))
print("Pages:", len(d["pages"]))
print("Tables:", len(d["tables"]))
print("Excluded:", [p["page_number"] for p in d["excluded_pages"]])
print("\nNon-accepted:")
for r in d["records"]:
    if r["quality_classification"] != "ACCEPTED":
        print(r["record_id"], r["quality_classification"], r["warnings"])
