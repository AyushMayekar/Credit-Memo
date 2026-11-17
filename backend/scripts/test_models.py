import sys
from pathlib import Path

from sqlalchemy import inspect, select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.models import CreditPolicyRule, User  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402

EXPECTED_TABLES = {
    "audit_logs",
    "borrowers",
    "calculated_metrics",
    "credit_memos",
    "credit_policy_rules",
    "data_mismatches",
    "document_contents",
    "documents",
    "extracted_images",
    "extracted_tables",
    "faiss_indexes",
    "faiss_vector_mappings",
    "financial_values",
    "loan_applications",
    "risk_flags",
    "users",
}


def main() -> None:
    inspector = inspect(engine)
    database_tables = set(inspector.get_table_names(schema="credit_ai"))

    missing_tables = EXPECTED_TABLES - database_tables
    unexpected_tables = database_tables - EXPECTED_TABLES

    print(f"Mapped tables expected: {len(EXPECTED_TABLES)}")
    print(f"Database tables found: {len(database_tables)}")

    if missing_tables:
        raise RuntimeError(f"Missing database tables: {sorted(missing_tables)}")

    if unexpected_tables:
        print(f"[WARN] Additional database tables: {sorted(unexpected_tables)}")

    with SessionLocal() as session:
        users = session.scalars(select(User).order_by(User.id)).all()
        rules = session.scalars(
            select(CreditPolicyRule).order_by(CreditPolicyRule.rule_code)
        ).all()

        print(f"Users readable through ORM: {len(users)}")
        for user in users:
            print(f"  - {user.id}: {user.full_name} ({user.role})")

        print(f"Credit-policy rules readable through ORM: {len(rules)}")
        for rule in rules:
            print(f"  - {rule.rule_code}: {rule.rule_name}")

    print("[SUCCESS] All SQLAlchemy models imported and queried successfully")


if __name__ == "__main__":
    main()
