from __future__ import annotations
import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from app.ai.parsing.unified_parsing_pipeline import UnifiedParsingPipeline

p = argparse.ArgumentParser(description="Parse validated structural extraction JSON.")
p.add_argument("--extraction", required=True, type=Path)
p.add_argument("--output", default="parsed-test-output", type=Path)
p.add_argument("--application", default="TEST")
p.add_argument("--document", default="DOC")
a = p.parse_args()
result = UnifiedParsingPipeline(parsed_root=a.output).parse(
    extraction_path=a.extraction,
    application_reference=a.application,
    document_reference=a.document,
)
print(json.dumps(asdict(result), indent=2))
print("Inspect:", result.parsed_document_path)
print("Digest:", result.parser_digest_path)
