import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db.session import SessionLocal
from app.services.credit_memo_generation_service import (
    UniversalCreditMemoGenerationService,
)

p = argparse.ArgumentParser()
p.add_argument("--application", required=True)
a = p.parse_args()
with SessionLocal() as s:
    r = UniversalCreditMemoGenerationService(s).generate(
        application_reference=a.application
    )
print(
    json.dumps(
        {
            "memo_id": r.memo_id,
            "version": r.version_number,
            "status": r.memo_status,
            "sources": r.source_count,
            "quality": r.quality_status,
        },
        indent=2,
    )
)
