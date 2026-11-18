# Integration Guide: Frontend + AI Pipeline + Backend

**Audience:** frontend developers, backend developers, AI engineers, and reviewers.  
**Scope:** upload → Docling extraction → V8 parsing → hierarchical chunking → embedding/ingestion → AI assistant and credit memo.

This guide describes the code as it exists now. If an older guide or plan conflicts with this one, use this one.

---

## 1. What the system does

```text
Frontend
   |
   |  REST /api/v1
   v
FastAPI routes
   |
   +--> PostgreSQL (application, documents, chunks, tables, memos)
   |
   +--> Docling extractor
   |       extraction.json
   |
   +--> V8 structural parser
   |       parsed_document.json
   |
   +--> Hierarchical chunker
   |       parents + CHILD_CHUNK + TABLE_DATA
   |
   +--> Embedding client + FAISS
   |       child and table vectors only
   |
   +--> Retrieval + LLM
           assistant answers and credit memos
```

Fixed retrieval behavior:

| Rule | Value |
|---|---|
| Search | FAISS similarity only |
| Candidate window | `candidate_k = 24` minimum |
| Results inspected | Top 8 usable child/table results |
| Parents sent to LLM | Maximum 2, minimum 1 when evidence exists |
| Child text sent to LLM | Never |
| Tables sent to LLM | Only matched tables, exactly as stored |
| Table fetching | Only when the table itself appears in the top 8; no separate table search |
| Reranking | None |
| Retrieval token trimming | None |
| RAG retries | Zero |
| General-query DB/FAISS calls | Zero |
| Credit-memo retries | Important: 3; less important: 1; initial call excluded |
| Last memo retry | Answer-only; no tool action |

---

## 2. Prerequisites

| Item | Notes |
|---|---|
| Python 3.11+ | The code uses modern `dataclass` and union syntax. |
| PostgreSQL | The models use PostgreSQL `JSONB`. |
| Docling artifacts | Put the local models in `docling_models/`. |
| Embedding endpoint | OpenAI-compatible embeddings endpoint. |
| LLM endpoint | OpenAI-compatible chat endpoint. |

Create `backend/.env` or export these variables:

```bash
DATABASE_URL=postgresql://app_user:app_pass@localhost:5432/credit_ai
EMBEDDING_API_KEY=...
EMBEDDING_MODEL=text-embedding-005-cto-oth
LLM_API_KEY=...
LLM_BASE_URL=https://your-llm-gateway.example/v1
LLM_MODEL=claude-sonnet-4-6-Dev
```

Start the API:

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Base URL: `http://localhost:8000/api/v1`. Health check: `GET /health`.

---

## 3. Frontend flow

### 3.1 Create an application

`POST /applications`

```json
{
  "borrower": {
    "legal_name": "Acme Manufacturing Limited",
    "borrower_type": "CORPORATE",
    "industry": "Manufacturing",
    "country": "IN"
  },
  "facility": {
    "loan_amount": 25000000,
    "currency": "INR",
    "loan_purpose": "Working capital",
    "tenure_months": 36
  }
}
```

Response:

```json
{
  "application_reference": "APP-2026-0001",
  "status": "CREATED"
}
```

### 3.2 Upload a document

`POST /applications/{ref}/documents` as `multipart/form-data` with `file`.

```json
{
  "document_id": 12,
  "filename": "FY2024 Annual Report.pdf",
  "status": "UPLOADED"
}
```

### 3.3 Start the extraction job

`POST /applications/{ref}/preparation-jobs`

```json
{
  "document_ids": [12],
  "reporting_year": "FY2024"
}
```

The job runs Docling-only extraction and returns `202`:

```json
{
  "job_reference": "JOB-2026-0007",
  "job_type": "EXTRACTION",
  "status": "QUEUED",
  "progress_percentage": 0,
  "current_stage": "QUEUED"
}
```

Poll `GET /jobs/{job_ref}` until `status` is `COMPLETED` or `FAILED`. On success, the application status is `WAITING_FOR_CONTENT_REVIEW`.

### 3.4 Review and approve extraction

- `GET /applications/{ref}/extractions` — document extraction status.
- `GET /documents/{document_id}/extraction` — extraction summary.
- `GET /documents/{document_id}/extraction/pages/{page_number}` — page-level data.
- `POST /applications/{ref}/extractions/approve` — mark documents `VALIDATED`.

AI preparation refuses to start until every selected document is validated.

### 3.5 Start AI preparation

`POST /applications/{ref}/ai-preparation-jobs`

```json
{
  "process_text": true,
  "process_selected_tables": true,
  "process_selected_visuals": false,
  "reporting_year": "FY2024"
}
```

This job parses the extraction, creates parent/child/table chunks, embeds only `CHILD_CHUNK` and `TABLE_DATA`, and writes the FAISS index. On success:

```json
{
  "job_type": "AI_PREPARATION",
  "status": "COMPLETED",
  "current_stage": "AI_READY",
  "result_payload": {
    "parsing": ["..."],
    "ingestion": {
      "parent_count": 9,
      "child_count": 38,
      "table_count": 12
    }
  }
}
```

The application status becomes `AI_READY`.

### 3.6 Optional content review

- `GET /applications/{ref}/content-review` — review counts.
- `GET /applications/{ref}/review-items?item_type=TABLE` — table/visual review items.
- `PATCH /review-items/{item_id}/selection` with `{"selected_for_analysis": true}`.
- `GET /review-items/{item_id}/preview` — PNG preview.
- `POST /applications/{ref}/content-review/finalize`.

Review flags do not automatically remove evidence. `REVIEW_REQUIRED` tables remain searchable and can still be cited.

### 3.7 Ask the assistant

`POST /applications/{ref}/ai/query`

```json
{
  "query": "What was revenue in FY2024?"
}
```

Response envelope:

```json
{
  "generation_id": 123,
  "route": "RAG",
  "response": {
    "response_type": "rag_answer",
    "answer": "Revenue was 100 in FY2024.",
    "key_points": ["Revenue was 100 in FY2024."],
    "sources": [
      {
        "source_id": "DOC12-CONTENT-401",
        "claim": "FY2024 revenue"
      }
    ],
    "limitations": []
  },
  "sources": [
    {
      "source_id": "DOC12-CONTENT-401",
      "score": 0.91,
      "raw_score": 0.84,
      "content_id": 401,
      "parent_content_id": 301,
      "content_type": "TABLE_DATA",
      "document_id": 12,
      "chunk_id": "TG-TABLE-0007-PART-001",
      "page_number": 18,
      "page_end": 18,
      "section_title": "Consolidated income statement",
      "source_reference": "FY2024 Annual Report.pdf, page 18, table TABLE-0007, part 1"
    }
  ]
}
```

Routes:

| Route | Behavior | `generation_id` | Sources |
|---|---|---|---|
| `APP_HELP` | Static application context, no PostgreSQL, no FAISS | `0` | `[]` |
| `OUT_OF_SCOPE` | Fixed polite refusal, no PostgreSQL, no FAISS | `0` | `[]` |
| `RAG` | Loads application, retrieves parents/tables, one answer | real ID | parent/table sources |

Important frontend rules:

- Use the returned `sources[].source_id` exactly. Do not invent citation IDs.
- `sources[].content_type` is `PARENT_SECTION` or `TABLE_DATA`.
- For a parent source, `content_id` is the parent and `parent_content_id` is the same parent.
- For a table source, `content_id` is the table chunk and `parent_content_id` is its parent.
- RAG answers do **not** reconstruct or display tables. They use table values to answer.
- If `route` is `OUT_OF_SCOPE`, show the refusal as a normal assistant message.
- `generation_id = 0` means the request was answered without a persisted generation record. Do not call `GET /credit-memos/0`.

### 3.8 Generate a credit memo

`POST /applications/{ref}/credit-memos`

```json
{
  "template": "STANDARD_CREDIT_MEMO"
}
```

Response:

```json
{
  "memo_id": 44,
  "version_number": 1,
  "status": "DRAFT",
  "memo": { "...": "full memo payload" },
  "source_count": 37,
  "quality_status": "COMPLETE"
}
```

Then:

- `GET /credit-memos/{memo_id}` — full memo + validation report.
- `GET /applications/{ref}/credit-memos` — version history.
- `GET /credit-memos/{memo_id}/preview` — HTML preview.
- `POST /credit-memos/{memo_id}/exports/pdf` — generate PDF.
- `GET /credit-memos/{memo_id}/exports/pdf` — download PDF.

Memo sections follow `backend/app/schemas/credit_memo_output.schema.json`:

- `report_metadata`
- `borrower_profile`
- `facility_request`
- `executive_summary`
- `business_and_industry_analysis`
- `management_ownership_governance`
- `financial_analysis`
- `existing_debt_and_repayment_capacity`
- `security_and_collateral`
- `key_credit_strengths`
- `key_credit_risks`
- `risk_mitigants`
- `policy_compliance_and_exceptions`
- `proposed_terms_and_conditions`
- `credit_recommendation`
- `missing_information_and_quality_flags`
- `source_register`
- `generation_metadata`

---

## 4. What the backend stores

### 4.1 `DocumentContent`

| `content_type` | Embedded in FAISS? | Sent to LLM? |
|---|---|---|
| `PARENT_SECTION` | No | Yes |
| `CHILD_CHUNK` | Yes | **Never** |
| `TABLE_DATA` | Yes | Yes, as-is |

Parent metadata includes:

```json
{
  "chunk_id": "PG-SEC-0004-PART-001",
  "parent_group_id": "PG-SEC-0004",
  "parent_part_index": 1,
  "parent_part_count": 2,
  "related_parent_ids": ["PG-SEC-0004-PART-002"],
  "table_chunk_ids": ["TG-TABLE-0007-PART-001"]
}
```

`section_id`, `section_title`, and the page range are stored on the
`DocumentContent` row. `chunk_id` is added by the ingestion service so
related-parent lookup does not have to parse the full metadata tree.

Child metadata includes `chunk_id`, `parent_chunk_id`, `child_group_id`, and related child IDs.

Table metadata includes `chunk_id`, `table_id`, `parent_chunk_id`, `table_part_index`, `table_part_count`, `detected_periods`, `detected_units`, `quality_classification`, and warnings.

`content_metadata["chunk_id"]` is stored at the top level so related-parent lookup does not have to parse the full metadata tree.

### 4.2 `ExtractedTable`

Each `TABLE_DATA` row has an `ExtractedTable` row linked by `content_id`. It stores the original/normalized rows, table markdown, periods, units, uncertainties, quality classification, and optional image paths.

`review_required` is a review marker. It does not reject the table.

### 4.3 Source IDs

The stable source ID is:

```text
DOC<document_id>-CONTENT-<content_id>
```

RAG prompts use this ID directly. Credit-memo prompts use compact aliases `S1..Sn`; the deterministic wrapper expands them back to the stable ID before validation and storage.

---

## 5. AI rules the frontend should assume

| Situation | Behavior |
|---|---|
| General app question | Static answer; no DB/FAISS |
| Unrelated question | Polite refusal; no DB/FAISS |
| Document question | Top-8 retrieval; max 2 parents; no child text |
| Table in top 8 | Table sent as-is + its parent |
| Table outside top 8 | Not fetched separately |
| RAG answer | One retrieval, one answer, no retries |
| Memo batch | Initial retrieval + bounded action retries |
| Important memo batch | 3 retries after the initial call |
| Less-important memo batch | 1 retry after the initial call |
| Last memo retry | Answer-only; a tool action is invalid |
| Invalid final answer | `pending_review` with a caveat; no infinite loop |
| No evidence | `not_disclosed` with a caveat |

The LLM never calls a tool directly. It returns JSON; the backend validates it and performs any allowed tool call.

---

## 6. Error handling

| Status | Meaning | Frontend action |
|---|---|---|
| `400` | Invalid request or invalid structured output that the API treats as client error | Show the message; do not retry blindly |
| `404` | Application, document, memo, or preview not found | Refresh the page state |
| `409` | Missing FAISS index, unapproved extraction, or generation precondition | Show the message and the next required step |
| `422` | FastAPI request validation error | Inspect the payload |
| `502` | LLM returned invalid JSON or an invalid structured contract | Show a retry option; do not parse raw LLM text |
| `503` | PDF renderer unavailable | Keep the HTML preview; retry export later |

The API never returns raw LLM text. It returns validated JSON or an HTTP error.

---

## 7. Developer verification

### 7.1 Unit tests

```bash
cd /path/to/repo
DATABASE_URL=sqlite:// \
EMBEDDING_API_KEY=test \
LLM_API_KEY=test \
LLM_BASE_URL=http://localhost \
PYTHONPATH=backend \
python -m pytest -q backend/tests
```

Current tests cover:

- Retrieval packet: parents/tables only, no child text.
- No parent/table trimming.
- Fixed `top_k=2` and `candidate_k=24`.
- Memo retry budgets: 3 for important, 1 for less important.
- Last retry is answer-only.
- Invalid JSON consumes one retry.
- Unknown parent IDs and unknown citation IDs are rejected.
- Structural parser/chunker contracts.

### 7.2 Parsing/chunking smoke test on the bundled sample

```bash
cd backend
python -m app.ai.parsing.lightweight_parser_v8 \
  --extraction support/extraction.json \
  --application SUPPORT \
  --document DOC-001 \
  --output storage/parsed-v8

python - <<'PY'
import json
from pathlib import Path
from app.ai.chunking.pipeline import run

result = run(
    Path("storage/parsed-v8/SUPPORT/DOC-001/parsed_document.json"),
    borrower_name="SUPPORT",
    document_name="Support sample",
    reporting_year="2024",
    document_id=1,
)
print(json.dumps({
    "parents": len(result["parents"]),
    "children": len(result["children"]),
    "tables": len(result["tables"]),
    "audit": result["audit"]["status"],
}, indent=2))
PY
```

The sample is expected to produce 45 sections, 50 narrative records (44 accepted + 6 review), and 12 tables; chunking produces 9 parents, 38 children, and 12 tables with audit `PASS`.

### 7.3 Read-only retrieval checks

```bash
cd backend
python scripts/test_retrieval_local.py \
  --application APP-2026-0001 \
  --query "What was revenue in FY2024?"
```

```bash
python scripts/test_memo_retrieval_local.py \
  --application APP-2026-0001 \
  --batch revenue_profit
```

Neither script writes a memo or calls the LLM unless explicitly requested.

### 7.4 Full memo batch check (read-only)

```bash
python scripts/test_all_memo_batches_read_only.py \
  --application APP-2026-0001
```

This runs the real retrieval + retry wrapper for every batch and prints the audit rows.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ModuleNotFoundError: docling` | Missing AI dependencies | Install `requirements.txt` in the active environment |
| `FileNotFoundError: FAISS index not found` | AI preparation has not completed | Run `POST /applications/{ref}/ai-preparation-jobs` |
| `409 Approve all document extractions before AI preparation` | Extraction not validated | Call `POST /applications/{ref}/extractions/approve` |
| `502 ... invalid structured response` | LLM returned malformed JSON or wrong schema | Retry the request; check the LLM gateway/model |
| `pending_review` memo section | Retry budget exhausted with no valid final answer | Inspect the caveat and the source review UI |
| `not_disclosed` memo section | No evidence retrieved for that batch | Confirm documents were ingested and the FAISS index contains this application |
| Sources show `content_type = CHILD_CHUNK` | Ingestion is stale or the wrong index is loaded | Re-run AI preparation; child chunks must never reach the LLM |
| `generation_id = 0` | General or out-of-scope answer | Expected; no generation row is written |

---

## 9. Handy request sequence

```text
1. POST /applications
2. POST /applications/{ref}/documents
3. POST /applications/{ref}/preparation-jobs
4. GET  /jobs/{job_ref}                         (poll)
5. POST /applications/{ref}/extractions/approve
6. POST /applications/{ref}/ai-preparation-jobs
7. GET  /jobs/{job_ref}                         (poll)
8. POST /applications/{ref}/ai/query            (assistant)
9. POST /applications/{ref}/credit-memos        (memo)
10. GET /credit-memos/{memo_id}                  (read)
11. GET /credit-memos/{memo_id}/preview          (HTML)
12. POST /credit-memos/{memo_id}/exports/pdf     (generate PDF)
13. GET /credit-memos/{memo_id}/exports/pdf      (download)
```

---

## 10. Non-negotiable contracts

- The LLM never receives child chunks.
- The LLM never receives more than 2 parent contexts in one memo batch or RAG answer.
- Tables are sent exactly as stored.
- Retrieval does not trim tokens or rows.
- Retrieval does not rerank.
- RAG has no retries.
- General/out-of-scope queries make no PostgreSQL or FAISS calls.
- Credit-memo retries are bounded and the last retry is answer-only.
- Every LLM output is JSON-validated before a tool or downstream function receives it.
- Citations must reference supplied evidence IDs.
