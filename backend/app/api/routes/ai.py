from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.retrieval.json_utils import LlmJsonError
from app.db.session import get_db
from app.schemas.api_models import QueryRequest
from app.services.rag_generation_service import RagGenerationService

router = APIRouter(tags=["AI Assistant"])


@router.post("/applications/{ref}/ai/query")
def query(ref: str, payload: QueryRequest, db: Session = Depends(get_db)):
    try:
        result = RagGenerationService(db).answer_user_query(
            application_reference=ref,
            query=payload.query,
        )
        return {
            "generation_id": result.generation_id,
            "route": result.route,
            "response": result.response,
            "sources": result.sources,
        }
    except LlmJsonError as exc:
        raise HTTPException(
            502, f"The language model returned an invalid structured response: {exc}"
        ) from exc
    except FileNotFoundError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
