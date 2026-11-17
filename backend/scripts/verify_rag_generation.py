import argparse, json, sys
from pathlib import Path
from sqlalchemy import select

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
from app.db.models import RagGeneration
from app.db.session import SessionLocal

p = argparse.ArgumentParser()
p.add_argument("--generation-id", type=int, required=True)
a = p.parse_args()
with SessionLocal() as s:
    r = s.get(RagGeneration, a.generation_id)
    if not r:
        raise RuntimeError("Generation not found")
    print(
        json.dumps(
            {
                "id": r.id,
                "request_type": r.request_type,
                "route": r.route,
                "query_stored": r.user_query is not None,
                "response": r.response_json,
                "sources": r.source_snapshot,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
