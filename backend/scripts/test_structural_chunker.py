from __future__ import annotations
import argparse, json, sys, time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.ai.chunking.pipeline import HybridTextChunkingPipeline

p = argparse.ArgumentParser()
p.add_argument("--parsed", required=True, type=Path)
p.add_argument("--output", default="chunking-test-output", type=Path)
p.add_argument("--borrower", default="Test Borrower")
p.add_argument("--document-name")
p.add_argument("--reporting-year")
p.add_argument("--max-digest-chars", type=int, default=24000)
a = p.parse_args()
start = time.perf_counter()
result = HybridTextChunkingPipeline().run(
    a.parsed,
    borrower_name=a.borrower,
    document_name=a.document_name,
    reporting_year=a.reporting_year,
)
a.output.mkdir(parents=True, exist_ok=True)
payload = {
    "chunker_version": HybridTextChunkingPipeline.VERSION,
    "source_parsed_document": str(a.parsed.resolve()),
    "elapsed_seconds": round(time.perf_counter() - start, 4),
    "parents": [asdict(x) for x in result.parents],
    "children": [asdict(x) for x in result.children],
    "tables": [asdict(x) for x in result.tables],
}
path = a.output / "chunking_output.json"
path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
summary = {
    "elapsed_seconds": payload["elapsed_seconds"],
    "parent_count": len(result.parents),
    "child_count": len(result.children),
    "table_count": len(result.tables),
    "min_child_tokens": min((x.token_count for x in result.children), default=0),
    "max_child_tokens": max((x.token_count for x in result.children), default=0),
    "average_child_tokens": round(
        sum(x.token_count for x in result.children) / max(len(result.children), 1), 2
    ),
    "review_child_count": sum(
        x.metadata.get("quality_classification") == "REVIEW_REQUIRED"
        for x in result.children
    ),
    "review_table_count": sum(
        x.quality_classification == "REVIEW_REQUIRED" for x in result.tables
    ),
    "low_priority_child_count": sum(
        x.metadata.get("search_priority") == "LOW" for x in result.children
    ),
    "high_priority_table_count": sum(
        x.metadata.get("search_priority") == "HIGH" for x in result.tables
    ),
    "unique_child_ids": len({x.chunk_id for x in result.children}),
    "output_path": str(path),
}
(a.output / "chunking_summary.json").write_text(
    json.dumps(summary, indent=2), encoding="utf-8"
)
print(json.dumps(summary, indent=2))
print("Output:", path)
