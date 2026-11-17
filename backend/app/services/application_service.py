from decimal import Decimal
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.db.models import Borrower, LoanApplication


class ApplicationService:
    def __init__(self, s: Session):
        self.s = s

    def create(self, p):
        borrower = self.s.scalar(
            select(Borrower).where(Borrower.legal_name == p.borrower.legal_name.strip())
        )
        if not borrower:
            borrower = Borrower(**p.borrower.model_dump())
            self.s.add(borrower)
            self.s.flush()
        ref = f"APP-{uuid4().hex[:10].upper()}"
        f = p.facility
        app = LoanApplication(
            application_reference=ref,
            borrower_id=borrower.id,
            loan_amount=f.loan_amount,
            currency=f.currency.upper(),
            loan_purpose=f.loan_purpose,
            tenure_months=f.tenure_months,
            status="DRAFT",
        )
        self.s.add(app)
        self.s.commit()
        self.s.refresh(app)
        return app

    def get(self, ref):
        return self.s.scalar(
            select(LoanApplication).where(LoanApplication.application_reference == ref)
        )
