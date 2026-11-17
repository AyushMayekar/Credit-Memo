# Integration Guide: Frontend + AI Pipeline + Backend
*(Designed to work with the code you just received – the Docling‑only extractor, the V8 structural parser, the hierarchical chunker and the batch‑ingestion service.)*

---

## 1️⃣ What this guide does
It shows **one complete end‑to‑end flow** that takes a PDF, extracts loss‑less Docling text, parses it into sections + tables, chunks the narrative, and finally stores everything in the database so your frontend can display/search it.
All steps use the **new modules we just created or updated**:

| Module | Location | Purpose |
|--------|----------|---------|
| `StandaloneHybridExtractorV4` | `backend/app/ai/extraction/standalone_hybrid_extractor_v4.py` | Docling‑only extraction (no pdfplumber tables). |
| `LightweightParsingPipelineV8` | `backend/app/ai/parsing/lightweight_parser_v8.py` | Structural parser that produces `parsed_document.json` (sections, records, tables). |
| `run()` in `backend/app/ai/chunking/pipeline.py` | `backend/app/ai/chunking/pipeline.py` | Hierarchical chunker → parent/child/table chunks. |
| `ingest_parsed_document()` in `backend/app/services/batch_content_ingestion_service.py` | `backend/app/services/batch_content_ingestion_service.py` | Persists the chunks into the DB (`DocumentContent` + `ExtractedTable`). |
| Front‑end (your UI) | Any React/Vue/HTML that talks to the FastAPI backend (`/api/...` endpoints). | Consume the DB records that were just created. |

---

## 2️⃣ Prerequisites
| Item | Why you need it | How to get it |
|------|----------------|---------------|
| **Python 3.11+** (the project originally targeted 3.11; the code also runs on 3.8 with a small `dataclass‑slots` shim). | All new modules use Python‑3.11+ type‑hints and `dataclass` features. | Install from `pyenv` or your system package manager. |
| **Poetry** (or `pip`) – manages the project’s virtual‑env and dependencies. | Guarantees the correct versions of `docling`, `faiss‑cpu`, `sqlalchemy`, etc. | `curl -sSL https://install.python-poetry.org | python3 -` then `poetry install` in the repo root. |
| **Node ≥ 18** + **npm/yarn** (if you have a React/Vue front‑end). | The frontend calls the FastAPI routes; you may already have a separate front‑end repo. | Use `nvm` or your system package manager. |
| **PostgreSQL** (or SQLite for quick demos). | The ingestion service writes to `DocumentContent` / `ExtractedTable` tables. | `sudo apt-get install postgresql` (or Docker `postgres`). |
| **.env file** with these keys (copy from `.env.example` and fill):  

```
DATABASE_URL=postgresql://app_user:app_pass@localhost:5432/credit_ai
DOCLING_ARTIFACTS_PATH=/absolute/path/to/docling_models
```

| Required by the extractor and the parser. | Create the file at `backend/.env`. |
| **OpenAI / Claude API key** (if you want LLM‑driven prompts). | Set `LLM_API_KEY` / `LLM_BASE_URL` in `.env`. |  

---

## 3️⃣ Folder layout (what you already have)
```
backend/
│
├─ app/
│   ├─ ai/
│   │   ├─ extraction/standalone_hybrid_extractor_v4.py
│   │   ├─ parsing/lightweight_parser_v8.py
│   │   ├─ chunking/pipeline.py            ← new/changed
│   │   └─ tables/processing_pipeline.py
│   └─ services/batch_content_ingestion_service.py   ← changed
│
├─ scripts/
│   └─ table_boundary_detector.py
│
└─ docs/extraction.json          (sample Docling output – you will generate your own)
```

All paths below assume you are in the **repo root** (`/mnt/c/Users/ayush/Desktop/vs/Credit-Memo-Copy`).

---

## 4️⃣ Step‑by‑step pipeline
### 4.1 Extract the PDF with the Docling‑only extractor
```bash
# 1️⃣  Activate the project virtual‑env
poetry shell

# 2️⃣  Run the extractor on a sample PDF
python -m app.ai.extraction.standalone_hybrid_extractor_v4 \
    --pdf /path/to/your/memo.pdf \
    --output storage/extracted \
    --artifacts /absolute/path/to/docling_models \
    --application MYAPP \
    --document MYDOC \
    --document-name "My Credit Memo" \
    --period-type annual \
    --period-end 2024-04-30 \
    --period-label FY2024
```
*What you get*  
* `storage/extracted/MYAPP/MYDOC/extraction.json` – the **raw Docling JSON** (pages + items, no table heuristics).  
* `extraction_review.json` & `extraction_digest.txt` – optional inspection artifacts.  

The extraction JSON is the **single source of truth** for the rest of the pipeline.

### 4.2 Parse the extraction into sections + tables
```bash
python -m app.ai.parsing.lightweight_parser_v8 \
    --extraction storage/extracted/MYAPP/MYDOC/extraction.json \
    --application MYAPP \
    --document MYDOC \
    --document-name "My Credit Memo" \
    --period-type annual \
    --period-end 2024-04-30
```
*What you get*  
* `storage/parsed-v8/MYAPP/MYDOC/parsed_document.json` – the **structured output** containing:  

  * `sections` – hierarchy of headings, `heading_path`, `page_start/end`, `record_ids`, `table_ids`.  
  * `records` – `SECTION_TEXT` entries with `content_text`, `quality_classification`.  
  * `tables` – 51 financial tables, each with `table_id`, `markdown`, `column_labels`, `detected_periods`, `numeric_audit`, `region_confidence`, `review_reasons`, etc.  
  * `audit` – counts of items, garbage removed, tables, etc.  

The file is now ready for chunking.

### 4.3 Chunk the parsed document (parent + child + tables)
```bash
python -m app.ai.chunking.pipeline \
    --extraction storage/extracted/MYAPP/MYDOC/extraction.json \
    --parsed   storage/parsed-v8/MYAPP/MYDOC/parsed_document.json \
    --borrower MYAPP \
    --document MYDOC \
    --year 2024 \
    --output chunking-output.json
```
*What you get*  
* `chunking-output.json` – a JSON payload with three top‑level keys:  

  * **`parents`** – one entry per section (heading path, page range, child‑record IDs).  
  * **`children`** – one entry per narrative `SECTION_TEXT` record (page range, text, parent‑chunk ID).  
  * **`tables`** – one entry per financial table (markdown, column labels, numeric audit, warnings, etc.).  

You can also run the same command **without** the `--extraction` flag if the parsed document already exists (the script will just use the `--parsed` path).

### 4.4 Ingest the chunks into the database
```bash
# First, make sure PostgreSQL is running and the DB/user exist:
#   createuser -s app_user
#   createdb credit_ai

# Then run the ingestion function (you can do it from Python or via the CLI wrapper)
python - <<'PY'
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.services.batch_content_ingestion_service import ingest_parsed_document
from pathlib import Path

session = SessionLocal()
stats = ingest_parsed_document(
    session,
    application_id=1,                # corresponds to the app you created in DB
    document_id=2,                    # corresponds to the document row
    parsed_path=Path("storage/parsed-v8/MYAPP/MYDOC/parsed_document.json"),
)
print(stats)          # → {'parent_chunk_count': 106, 'child_chunk_count': 91, 'table_chunk_count': 51, ...}
session.commit()
PY
```
*What you get*  
* **`DocumentContent` rows** – parent sections (`content_type = "PARENT_SECTION"`) and narrative records (`content_type = "SECTION_TEXT"`).  
* **`ExtractedTable` rows** – one per financial table, storing markdown, column metadata, `numeric_audit`, `region_confidence`, `review_reasons`, etc.  
* **`audit` statistics** that you can post back to your job board or CI pipeline.  

At this point your database is fully populated and ready for the frontend to query.

#### 4.4.1 Optional: Quick sanity‑check with the CLI wrapper (included in `pipeline.py`)
```bash
python -m app.ai.chunking.pipeline \
    --extraction storage/extracted/MYAPP/MYDOC/extraction.json \
    --parsed   storage/parsed-v8/MYAPP/MYDOC/parsed_document.json \
    --borrower MYAPP \
    --output /tmp/chunking-stats.json
cat /tmp/chunking-stats.json   # shows the same audit fields as above
```

### 4.5 Front‑end integration (very simple)
Your UI already talks to the FastAPI backend. The new DB rows are exposed through a few ready‑made endpoints (you may already have them, or add them quickly).

| Endpoint | What it returns | How your UI can use it |
|----------|----------------|-----------------------|
| `GET /api/documents/{doc_id}/parents` | JSON list of parent‑section chunks (id, title, heading_path, page_start/page_end, quality). | Build a collapsible table of “sections”; clicking a section expands its children. |
| `GET /api/documents/{doc_id}/children` | JSON list of narrative `SECTION_TEXT` chunks (id, page_start/page_end, content_text, quality). | Render the text in a scrollable pane; highlight low‑quality passages in yellow. |
| `GET /api/documents/{doc_id}/tables` | JSON list of table chunks (id, page, markdown, column_labels, detected_periods, quality). | Render the markdown as an HTML table, or copy to a spreadsheet‑like view. |
| `GET /api/documents/{doc_id}/audit` | JSON with `source_item_count`, `table_owned_count`, `garbage_removed`, … | Show a tiny summary box (“51 tables, 106 sections, 91 narrative records, …”). |

**Minimal example (fetch + display a section):**

```javascript
async function loadSection(sectionId) {
  const resp = await fetch(`/api/documents/${docId}/parents/${sectionId}`);
  const sec = await resp.json();               // {chunk_id, title, heading_path, …}
  const kiddies = await fetch(`/api/documents/${docId}/children?parent=${sectionId}`)
                     .then(r => r.json());
  const textDiv = document.getElementById('section‑text');
  textDiv.innerHTML = kiddies.map(c => `<p>${c.content_text}</p>`).join('');
  document.getElementById('section‑title').textContent = sec.title;
}
```

That’s all you need – the backend already returns the data in the shape your UI expects.

### 4.6 Testing the flow (quick checklist)
| Step | Command | Expected result |
|------|---------|-----------------|
| **Extract** | `python -m app.ai.extraction.standalone_hybrid_extractor_v4 …` | `extraction.json` appears, `item_count` ≈ 3 000 (for a 31‑page memo). |
| **Parse** | `python -m app.ai.parsing.lightweight_parser_v8 …` | `parsed_document.json` appears, `section_count` ≈ 106, `table_count` = 51. |
| **Chunk** | `python -m app.ai.chunking.pipeline …` | `chunking-output.json` has `parents.length === 106`, `children.length === 91`, `tables.length === 51`. |
| **Ingest** | `python - <<'PY' …` | DB tables `document_content` and `extracted_table` have the matching row counts; `status` field = `"COMPLETED"`. |
| **Frontend** | `npm run dev` (or whatever you use) | UI loads, shows section list, clicking a section reveals narrative text, and a “Tables” tab shows the 51 tables with their markdown. |  

If any step fails, check:  

* **Docling model path** – must exist at `DOCLING_ARTIFACTS_PATH`.  
* **DB connection** – `DATABASE_URL` in `.env` must point to a running PostgreSQL (or SQLite if you switched the models).  
* **Python path** – make sure you are inside the `poetry shell` or have `backend` on `PYTHONPATH`.  

### 4.7 Quick “one‑liner” to run the whole thing (optional)
If you just want to try the pipeline end‑to‑end without writing separate commands, you can use the helper script that was added to `backend/scripts/test_batch_ingestion.py` (already adapted to call the new services). Run:

```bash
python backend/scripts/test_batch_ingestion.py \
    --extraction docs/extraction.json \
    --parsed   /tmp/parsed-test/TEST/DOC/parsed_document.json \
    --borrower TEST
```

It will print the same audit statistics we showed in the step‑by‑step section.

### 4.8 Troubleshooting cheat‑sheet
| Symptom | Likely cause | Fix |
|--------|--------------|-----|
| `ModuleNotFoundError: No module named 'docling'` | Docling not installed in the active env. | `poetry add docling` or `pip install docling`. |
| `StandaloneExtractionError: Missing local Docling layout model` | `DOCLING_ARTIFACTS_PATH` points nowhere. | Set the absolute path to `docling_models/docling-project--docling-layout-heron`. |
| `psycopg2.errors.CannotCoerceValue: cannot coerce ...` | DB schema mismatch (maybe old `DocumentContent` table). | Run `alembic upgrade head` (if you use migrations) or drop/recreate the DB. |
| Tables appear with `quality_classification: "REVIEW_REQUIRED"` but you expected `ACCEPTED`. | Region had `header_resets > 0` or `prose_rows > 0`. Inspect the review HTML (`table_regions_review.html`) to see which warning fired. | Accept the review flag – the ingestion service already marks it for human review. |
| Front‑end gets `404` on `/api/documents/…` | `docId` does not correspond to a DB row. | Verify that you inserted the document via the orchestration service first (the `run_ai_preparation_job` step). |  

### 4.9 What you have now
* **A Docling‑only extraction** that never mixes pdfplumber heuristics.  
* **A V8 structural parser** that gives you clean sections, narrative records, and fully‑meta‑described tables.  
* **A hierarchical chunker** that emits parents, children, and tables in a single JSON call.  
* **A batch‑ingestion service** that materialises everything into your PostgreSQL DB.  
* **A minimal front‑end contract** (endpoints + data shape) you can plug into any UI framework.  

Follow the steps above, and your system will go from a raw PDF to a searchable, section‑grounded knowledge base in just a few minutes.  

---  
🎉 **You’re done!**  

If you hit any snag or want to tweak something (e.g., add a new quality rule, change the chunk‑version, or expose additional fields), just let me know and I’ll adjust the code or the integration guide accordingly. Happy parsing!