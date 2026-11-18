import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select
from app.db.models import Document, LoanApplication
from app.db.session import SessionLocal
from app.services.batch_content_ingestion_service import BatchContentIngestionService

p = argparse.ArgumentParser()
p.add_argument("--application", required=True)
p.add_argument("--reporting-year")
a = p.parse_args()
with SessionLocal() as s:
    app = s.scalar(
        select(LoanApplication).where(
            LoanApplication.application_reference == a.application
        )
    )
    if not app:
        raise RuntimeError("Application not found")
    ids = list(
        s.scalars(
            select(Document.id).where(
                Document.application_id == app.id,
                Document.extraction_status == "VALIDATED",
            )
        )
    )
    result = BatchContentIngestionService(s).ingest_application(
        application_reference=a.application,
        document_ids=ids,
        reporting_year=a.reporting_year,
        replace_existing=True,
    )
    print(json.dumps(asdict(result), indent=2))
