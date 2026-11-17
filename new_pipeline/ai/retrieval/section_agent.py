from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from app.ai.retrieval.faiss_retriever import ApplicationFaissRetriever, RetrievedEvidence


# ── Prompt constants ──────────────────────────────────────────────────────
CITATION_PATTERN = r"\[(\d+)\]"

MAX_EVIDENCE_CONTEXTS = 4       # max distinct parent+child contexts per batch
MAX_EVIDENCE_CHARS = 12_000     # rough character cap for the evidence block
MAX_ROUNDS = 3                  # hard stop after 3 retrieval rounds
MAX_QUERY_WORDS = 12            # rewriter word limit
MAX_QUERY_CHARS = 160           # rewriter character limit


# ── State dataclass ───────────────────────────────────────────────────────
@dataclass
class BatchAgentState:
    """Holds everything for one batch across rounds."""

    batch_key: str
    application_id: int
    borrower_name: str
    application_reference: str
    query: str
    request_type: str

    # Per-round tracking
    round: int = 1
    seen_parent_ids: set[int] = field(default_factory=set)
    seen_content_ids: set[int] = field(default_factory=set)
    accumulated_evidence: list[RetrievedEvidence] = field(default_factory=list)
    accumulated_query_texts: set[str] = field(default_factory=set)

    # Final output
    final_score: int = 0
    final_missing: list[dict[str, Any]] = field(default_factory=list)
    final_next_query: str = ""
    final_status: str = "not_disclosed"  # available | not_disclosed | pending_review
    final_source_ids: list[str] = field(default_factory=list)  # global [1], [2], ...


# ── Helper utilities ──────────────────────────────────────────────────────
def _cap_evidence(state: BatchAgentState) -> BatchAgentState:
    """Enforce context/character caps; trim accumulated evidence."""
    # If adding new evidence would exceed caps, trim from the front
    while (
        len(state.accumulated_evidence) >= MAX_EVIDENCE_CONTEXTS
        or _evidence_chars(state.accumulated_evidence) > MAX_EVIDENCE_CHARS
    ):
        state.accumulated_evidence.pop(0)
    return state


def _evidence_chars(evidence: list[RetrievedEvidence]) -> int:
    """Return approximate character count of evidence texts."""
    return sum(len(e.text or "") for e in evidence)


def _dedupe_evidence(state: BatchAgentState) -> BatchAgentState:
    """Deduplicate by (content_type, content_id) and normalized context text."""
    seen: set[tuple[str, int, str]] = set()
    deduped: list[RetrievedEvidence] = []
    for ev in state.accumulated_evidence:
        norm = " ".join((ev.context_text or "").split()).casefold()
        key = (ev.content_type, ev.content_id, norm)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)
    state.accumulated_evidence = deduped
    return state


def _build_global_aliases(evidence: list[RetrievedEvidence]) -> dict[str, str]:
    """Map global [1], [2] ... to each evidence's source_id."""
    return {f"[{i + 1}]": ev.source_id for i, ev in enumerate(evidence)}


def _clamp_score(raw: int) -> int:
    """Clamp to 1–5."""
    return max(1, min(5, raw))


# ── Core agent loop (single batch) ────────────────────────────────────────
def run_batch_agent(
    retriever: ApplicationFaissRetriever,
    session: Session,
    *,
    application_id: int,
    borrower_name: str,
    application_reference: str,
    query: str,
    request_type: str,
) -> BatchAgentState:
    """Run the bounded retrieval loop for one batch.

    Returns a populated BatchAgentState with final_score, final_missing,
    final_next_query, final_status, final_source_ids.
    """
    state = BatchAgentState(
        batch_key="",  # set by caller
        application_id=application_id,
        borrower_name=borrower_name,
        application_reference=application_reference,
        query=query,
        request_type=request_type,
    )

    # ---------------------------------------------------------------
    # Round 1: initial retrieval
    # ---------------------------------------------------------------
    evidence = _retrieve_round(
        retriever, session, state, query, exclude_parent_ids=set(), exclude_content_ids=set()
    )
    state = _dedupe_evidence(state)
    state.accumulated_evidence = evidence

    # Run extraction + scoring
    state = _extract_and_score(state, round=1)

    if state.round >= MAX_ROUNDS or state.final_status != "pending_review":
        # No more rounds allowed or already resolved
        state.final_source_ids = list(
            _build_global_aliases(state.accumulated_evidence).keys()
        )
        return state

    # ---------------------------------------------------------------
    # Round 2: query rewrite + retrieval (exclude what we've seen)
    # ---------------------------------------------------------------
    next_query = _rewrite_query(state)
    if not next_query:
        # LLM said stop
        state.final_status = "not_disclosed"
        state.final_source_ids = list(
            _build_global_aliases(state.accumulated_evidence).keys()
        )
        return state

    evidence = _retrieve_round(
        retriever,
        session,
        state,
        next_query,
        exclude_parent_ids=state.seen_parent_ids,
        exclude_content_ids=state.seen_content_ids,
    )
    state = _dedupe_evidence(state)
    # Accumulate (cap will enforce limits)
    state.accumulated_evidence.extend(evidence)
    state = _cap_evidence(state)
    state = _dedupe_evidence(state)

    state = _extract_and_score(state, round=2)

    if state.round >= MAX_ROUNDS or state.final_status != "pending_review":
        state.final_source_ids = list(
            _build_global_aliases(state.accumulated_evidence).keys()
        )
        return state

    # ---------------------------------------------------------------
    # Round 3: final retrieval
    # ---------------------------------------------------------------
    next_query = _rewrite_query(state)
    if not next_query:
        state.final_status = "not_disclosed"
        state.final_source_ids = list(
            _build_global_aliases(state.accumulated_evidence).keys()
        )
        return state

    evidence = _retrieve_round(
        retriever,
        session,
        state,
        next_query,
        exclude_parent_ids=state.seen_parent_ids,
        exclude_content_ids=state.seen_content_ids,
    )
    state = _dedupe_evidence(state)
    state.accumulated_evidence.extend(evidence)
    state = _cap_evidence(state)
    state = _dedupe_evidence(state)

    state = _extract_and_score(state, round=3)

    # Last pass regardless of score
    state.final_source_ids = list(
        _build_global_aliases(state.accumulated_evidence).keys()
    )
    return state


def _retrieve_round(
    retriever: ApplicationFaissRetriever,
    session: Session,
    state: BatchAgentState,
    query: str,
    *,
    exclude_parent_ids: set[int],
    exclude_content_ids: set[int],
) -> list[RetrievedEvidence]:
    """One FAISS search round with exclusions."""
    evidence = retriever.search(
        query_vector=[0.0] * 768,  # placeholder; real embedding done outside
        application_id=state.application_id,
        top_k=2,
        candidate_k=40,
        exclude_parent_ids=exclude_parent_ids,
        exclude_content_ids=exclude_content_ids,
    )
    # Mark any returned evidence as excluded for tracking
    for ev in evidence:
        ev.excluded = True  # will be set properly by caller if needed
    # Update state tracking sets
    for ev in evidence:
        if ev.parent_content_id is not None:
            state.seen_parent_ids.add(ev.parent_content_id)
        state.seen_content_ids.add(ev.content_id)
    return evidence


def _rewrite_query(state: BatchAgentState) -> str | None:
    """Ask the LLM for a next query (bounded). Returns None if should stop."""
    # The extraction LLM call already produced next_query; if absent, stop.
    # This function just validates length constraints.
    missing = state.final_missing  # type: ignore[attr-defined]
    for item in missing[-3:]:  # look at last 3 missing items
        q = item.get("next_query", "")
        if not q:
            continue
        # Strip whitespace
        q = q.strip()
        if len(q.split()) > MAX_QUERY_WORDS or len(q) > MAX_QUERY_CHARS:
            # Too long — clamp to batch-defined deterministic query
            return None
        if q in state.accumulated_query_texts:
            # Duplicate query
            continue
        state.accumulated_query_texts.add(q)
        return q
    return None


def _extract_and_score(state: BatchAgentState, round: int) -> BatchAgentState:
    """Call the extraction LLM with the current evidence and return scored result.

    The extraction response JSON schema (simplified) expects:
    {
      "status": "available|not_disclosed|pending_review",
      "score": 1-5,
      "missing": [{"label": "...", "retryable": true|false, "next_query": "..."}],
      "citations": ["[1]", "[2]"],  // or we map later
      "answer": "..."
    }
    """
    # Build the prompt with [1], [2] citations
    evidence_text = _evidence_to_text(state.accumulated_evidence)
    aliases = _build_global_aliases(state.accumulated_evidence)

    # Construct the prompt - keep it bounded
    prompt = f"""You are extracting focused information for a credit memo batch.

Batch: {state.batch_key}
Query: {state.query}
Request type: {state.request_type}

Evidence (limited to {len(state.accumulated_evidence)} contexts, ~{_evidence_chars(state.accumulated_evidence)} chars):
{evidence_text}

Rules:
- Use only the evidence above. Do not add outside facts.
- Return exactly one JSON object.
- Score the completeness of the evidence for the query on a scale of 1–5
  (5 = all needed facts present, 1 = almost nothing useful).
- If the evidence is incomplete, list up to 3 missing items.
  For each missing item: give a short label, mark "retryable" (true only if
  the fact is likely findable in other documents), and propose the next query
  in at most 12 words / 160 characters.
- If the evidence is sufficient, set "retryable": false and "next_query": "".
- Cite every material fact using the supplied source IDs exactly as [1], [2], etc.
- Set "status" to "available" if sufficient, "not_disclosed" if no info,
  or "pending_review" if some parts need human checking.

Return JSON only:
{{
  "status": "available|not_disclosed|pending_review",
  "score": <int 1-5>,
  "missing": [
    {{"label": "...", "retryable": true|false, "next_query": "..."}}
  ],
  "answer": "..."
}}
"""

    from app.ai.llm import get_llm
    from app.ai.retrieval.json_utils import parse_json_object, LlmJsonError

    llm = get_llm()
    raw = llm.invoke(prompt, temperature=0, max_tokens=2000)

    try:
        result = parse_json_object(raw)
    except LlmJsonError:
        # Try extract first balanced object
        result = _first_balanced_json(raw)
        if result is None:
            # LLM failed completely — force not_disclosed
            state.final_status = "not_disclosed"
            return state

    # Clamp score to 1-5
    raw_score = result.get("score", 3)
    state.final_score = _clamp_score(raw_score)

    # Status logic
    status = result.get("status", "not_disclosed")
    if status == "available" and state.final_score >= 4:
        state.final_status = "available"
    elif status == "not_disclosed":
        state.final_status = "not_disclosed"
    else:
        # pending_review or low score → may need another round
        state.final_status = "pending_review"

    # Missing items
    missing = result.get("missing", [])
    # Ensure at most 3, each with retryable + next_query
    state.final_missing = missing[:3]
    for item in state.final_missing:
        item["retryable"] = item.get("retryable", False)
        item["next_query"] = item.get("next_query", "").strip()[:160]

    # Answer text (grounded)
    state.final_answer = result.get("answer", "")

    return state


def _first_balanced_json(raw: str) -> dict | None:
    """Very simple JSON extractor: find the first outermost {…} block."""
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(raw):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return __import__("json").loads(raw[start : i + 1])
                except Exception:
                    return None
    return None


def _evidence_to_text(evidence: list[RetrievedEvidence]) -> str:
    """Convert evidence to a compact text block with [1], [2] markers."""
    blocks: list[str] = []
    for i, ev in enumerate(evidence):
        # Trim to reasonable length per item
        text = (ev.text or "")[: 3000].strip()
        blocks.append(f"[{i + 1}] {text}")
    return "\n\n".join(blocks)


# ── Per-batch wrapper with threading ──────────────────────────────────────
def run_batch_with_threads(
    *,
    application_id: int,
    borrower_name: str,
    application_reference: str,
    query: str,
    request_type: str,
    batch_key: str,
    retriever: ApplicationFaissRetriever,
    session_factory,
) -> dict[str, Any]:
    """Run the agent in a thread, return the final dict for combine/assembly."""
    import threading

    result_holder: dict[str, Any] = {}

    def _worker():
        sess = session_factory()
        try:
            state = run_batch_agent(
                retriever,
                sess,
                application_id=application_id,
                borrower_name=borrower_name,
                application_reference=application_reference,
                query=query,
                request_type=request_type,
            )
            result_holder.update(
                {
                    "status": state.final_status,
                    "score": state.final_score,
                    "missing": state.final_missing,
                    "answer": state.final_answer,
                    "source_ids": state.final_source_ids,
                    "round": state.round,
                    "batch_key": state.batch_key,
                }
            )
        except Exception as exc:  # pylint: disable=broad-except
            result_holder["error"] = str(exc)
        finally:
            try:
                sess.close()
            except Exception:
                pass

    t = threading.Thread(target=_worker, name=f"batch-{batch_key}")
    t.start()
    t.join(timeout=300)  # 5 min per batch max
    if t.is_alive():
        # Timeout – shouldn't happen with thread, but be safe
        return {
            "status": "not_disclosed",
            "score": 1,
            "missing": [{"label": "timeout", "retryable": False, "next_query": ""}],
            "answer": "",
            "source_ids": [],
            "round": MAX_ROUNDS,
            "batch_key": batch_key,
        }
    return result_holder


# ── Orchestrator for multiple batches ─────────────────────────────────────
def run_all_batches(
    batch_configs: list[dict[str, Any]],
    session_factory,
    max_workers: int = 5,
) -> dict[str, dict[str, Any]]:
    """Run the agent across many batches concurrently (max_workers threads).

    Each batch_config must contain:
        application_id, borrower_name, application_reference, query,
        request_type, batch_key

    Returns: {batch_key: {status, score, missing, answer, source_ids, round}}
    """
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_key = {
            pool.submit(
                run_batch_with_threads,
                application_id=c["application_id"],
                borrower_name=c["borrower_name"],
                application_reference=c["application_reference"],
                query=c["query"],
                request_type=c["request_type"],
                batch_key=c["batch_key"],
                retriever=c["retriever"],
                session_factory=session_factory,
            ): c["batch_key"]
            for c in batch_configs
        }
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                results[key] = {
                    "status": "not_disclosed",
                    "score": 1,
                    "missing": [{"label": f"error: {exc}", "retryable": False, "next_query": ""}],
                    "answer": "",
                    "source_ids": [],
                    "round": MAX_ROUNDS,
                    "batch_key": key,
                }
    return results
