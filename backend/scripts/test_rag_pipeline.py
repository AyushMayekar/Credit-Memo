import argparse, json, sys
from dataclasses import asdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from app.db.session import SessionLocal
from app.services.rag_generation_service import RagGenerationService


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--application", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--query")
    group.add_argument("--credit-memo", action="store_true")
    a = p.parse_args()
    with SessionLocal() as session:
        svc = RagGenerationService(session)
        result = (
            svc.generate_credit_memo(application_reference=a.application)
            if a.credit_memo
            else svc.answer_user_query(
                application_reference=a.application, query=a.query
            )
        )
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
