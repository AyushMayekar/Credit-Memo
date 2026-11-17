import argparse, sys
from pathlib import Path
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.db.models import DocumentContent, FaissVectorMapping, LoanApplication
from app.db.session import SessionLocal

p = argparse.ArgumentParser()
p.add_argument("--application", required=True)
a = p.parse_args()
with SessionLocal() as s:
    app = s.scalar(
        select(LoanApplication).where(
            LoanApplication.application_reference == a.application
        )
    )
    if not app:
        raise RuntimeError("Application not found")
    rows = s.execute(
        select(DocumentContent.content_type, func.count(DocumentContent.id))
        .where(DocumentContent.application_id == app.id)
        .group_by(DocumentContent.content_type)
        .order_by(DocumentContent.content_type)
    ).all()
    print("Content records:")
    [print(f"  {t}: {c}") for t, c in rows]
    vectors = s.execute(
        select(FaissVectorMapping.content_type, func.count(FaissVectorMapping.id))
        .where(
            FaissVectorMapping.application_id == app.id,
            FaissVectorMapping.is_active.is_(True),
        )
        .group_by(FaissVectorMapping.content_type)
        .order_by(FaissVectorMapping.content_type)
    ).all()
    print("Active vectors:")
    [print(f"  {t}: {c}") for t, c in vectors]
