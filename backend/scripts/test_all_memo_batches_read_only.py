from __future__ import annotations
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from jsonschema import Draft202012Validator
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from app.ai.llm import get_llm
from app.ai.prompts.credit_memo_prompts import build_batch_messages
from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever
from app.ai.retrieval.json_utils import parse_json_object
from app.ai.retrieval.section_retriever import MemoBatchRetriever, RetrievalRequest
from app.core.config import settings
from app.db.models import LoanApplication
from app.db.session import SessionLocal
from app.services.credit_memo_batch_definitions import BATCHES


def load_context(ref):
    with SessionLocal() as s:
        app = s.scalar(
            select(LoanApplication).where(LoanApplication.application_reference == ref)
        )
        if app is None:
            raise RuntimeError("Application not found")
        return RetrievalRequest(
            app.id, app.application_reference, app.borrower.legal_name
        ), {
            "borrower_name": app.borrower.legal_name,
            "facility_amount": float(app.loan_amount),
            "currency": app.currency,
            "tenure_months": app.tenure_months,
        }


def run_one(request, facts, batch):
    with SessionLocal() as s:
        path = (
            settings.resolve_path(settings.faiss_dir)
            / f"{settings.faiss_index_name}.faiss"
        )
        _, packet = MemoBatchRetriever(ApplicationFaissRetriever(s, path)).retrieve(
            request=request, batch=batch
        )
    if not packet:
        return {"batch": batch.key, "status": "NO_EVIDENCE", "evidence": 0}
    messages, contract, _ = build_batch_messages(
        batch=batch, application_facts=facts, evidence=packet
    )
    response = get_llm().chat_response(
        messages, temperature=0, max_tokens=batch.max_output_tokens
    )
    if response.finish_reason == "length":
        return {"batch": batch.key, "status": "LENGTH", "evidence": len(packet)}
    try:
        result = parse_json_object(response.content)
    except Exception as exc:
        return {
            "batch": batch.key,
            "status": "MALFORMED",
            "error": str(exc),
            "evidence": len(packet),
        }
    errors = [e.message for e in Draft202012Validator(contract).iter_errors(result)]
    return {
        "batch": batch.key,
        "status": "PASS" if not errors else "INVALID",
        "evidence": len(packet),
        "output_characters": len(response.content),
        "errors": errors[:3],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--application", required=True)
    a = p.parse_args()
    request, facts = load_context(a.application)
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run_one, request, facts, b): b for b in BATCHES}
        for future in as_completed(futures):
            rows.append(future.result())
    order = {b.key: i for i, b in enumerate(BATCHES)}
    rows.sort(key=lambda x: order[x["batch"]])
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    if any(row["status"] not in {"PASS", "NO_EVIDENCE"} for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
