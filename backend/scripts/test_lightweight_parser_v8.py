from __future__ import annotations
import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from app.ai.parsing.lightweight_parser_v8 import LightweightParsingPipelineV8

p=argparse.ArgumentParser()
p.add_argument("--extraction",required=True,type=Path)
p.add_argument("--regions",required=True,type=Path)
p.add_argument("--output",default=Path("parser-v8-output"),type=Path)
p.add_argument("--application",default="TEST")
p.add_argument("--document",default="DOC")
a=p.parse_args()
result=LightweightParsingPipelineV8(parsed_root=a.output).parse(extraction_path=a.extraction,table_regions_path=a.regions,application_reference=a.application,document_reference=a.document)
print(json.dumps(asdict(result),indent=2))
