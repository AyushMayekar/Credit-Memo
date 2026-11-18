from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai.chunking.pipeline import HybridTextChunkingPipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the finalized structural chunker without database or FAISS writes.")
    parser.add_argument("--parsed", required=True, type=Path)
    parser.add_argument("--output", default=Path("chunking-test-output"), type=Path)
    parser.add_argument("--borrower", default="Test Borrower")
    parser.add_argument("--document-name")
    parser.add_argument("--reporting-year")
    parser.add_argument("--document-id", type=int)
    args = parser.parse_args()

    started = time.perf_counter()
    result = HybridTextChunkingPipeline().run(
        args.parsed,
        borrower_name=args.borrower,
        document_name=args.document_name,
        reporting_year=args.reporting_year,
        document_id=args.document_id,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "chunker_version": HybridTextChunkingPipeline.VERSION,
        "source_parsed_document": str(args.parsed.resolve()),
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "parents": [asdict(x) for x in result.parents],
        "children": [asdict(x) for x in result.children],
        "tables": [asdict(x) for x in result.tables],
        "audit": result.audit,
    }
    output_path = args.output / "chunking_output.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {
        "status": result.audit["status"],
        "elapsed_seconds": payload["elapsed_seconds"],
        "parent_count": len(result.parents),
        "child_count": len(result.children),
        "table_chunk_count": len(result.tables),
        "max_parent_tokens": result.audit["max_parent_tokens"],
        "max_child_tokens": result.audit["max_child_tokens"],
        "max_table_tokens": result.audit["max_table_tokens"],
        "missing_record_ids": result.audit["missing_record_ids"],
        "missing_table_ids": result.audit["missing_table_ids"],
        "broken_parent_links": result.audit["broken_parent_links"],
        "output_path": str(output_path.resolve()),
    }
    (args.output / "chunking_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if result.audit["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
