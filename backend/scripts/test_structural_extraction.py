from __future__ import annotations
import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.ai.extraction.pdfplumber_extractor import PdfPlumberExtractionService

p = argparse.ArgumentParser()
p.add_argument("--pdf", required=True)
p.add_argument("--output", default="structural-extraction-test")
a = p.parse_args()
r = PdfPlumberExtractionService(Path(a.output)).extract(
    pdf_path=Path(a.pdf), application_reference="TEST", document_reference="DOC"
)
print(json.dumps(asdict(r), indent=2))
print("Inspect:", r.extraction_path)
