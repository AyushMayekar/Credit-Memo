# Retrieval, Agent, and Credit-Memo Retry Decisions

**Status:** Fixed decisions  
**Scope:** Everything after chunking and ingestion — query routing, retrieval, evidence assembly, agent tools, structured LLM outputs, and credit-memo retries.  
**Audience:** Backend developers, AI engineers, reviewers, and anyone integrating the frontend with the FastAPI pipeline.

This document is deliberately simple. If a rule here conflicts with older code or an older plan, **this document wins**.

---

## 1. One-page summary

| Area | Fixed decision |
|---|---|
| **General questions** | Answered from static application context. No PostgreSQL call. No FAISS call. Out-of-application questions are politely refused. |
| **RAG questions** | One retrieval pass. Search child + table vectors in FAISS. Send only parents and tables to the LLM. No retries. |
| **Credit-memo generation** | Parallel section batches. Each batch retrieves once, then the LLM may request more evidence through structured actions. Retry budgets apply only here. |
| **Search settings** | `candidate_k = 24`. Inspect the **top 8** child results. Select **max 2 / min 1** distinct parents. FAISS similarity only. No reranking. |
| **What the LLM sees** | Parent chunks and table chunks only. **Never child chunks.** Tables are sent exactly as stored. |
| **Trimming** | None. No token-count check at retrieval. No row filtering. No table shortening. |
| **Tables** | Embedded like children. Only tables that appear in the top 8 are sent. A matched table is sent as-is together with its parent. Tables are **not** fetched separately. |
| **Citations** | Every answer cites supplied evidence IDs. Parent evidence cites the parent. Table evidence cites the table. |
| **LLM output** | Always structured JSON. A deterministic wrapper validates it before any tool or function receives it. |
| **Tool calling** | The LLM never calls a tool directly. It emits a structured intent. The wrapper validates the intent and calls the tool. |
| **Credit-memo retries** | Important sections: **3 retries**. Less-important sections/batches: **1 retry**. The initial retrieval is **not** a retry. |
| **Last try rule** | The final retry is **answer-only**. No tool action is allowed on the last try. |
| **RAG retries** | **Zero.** One retrieval, one answer. |
| **General retries** | **Zero.** No retrieval exists. |

---

## 2. Definitions

| Term | Meaning |
|---|---|
| **Parent chunk** | A bounded section-level context. It contains complete narrative child chunks and is the prose context sent to the LLM. Parents are stored in PostgreSQL but are **not** embedded in FAISS. |
| **Child chunk** | A narrative search unit of roughly 350 tokens (target 350 / soft 500 / hard 600, with ~50-token overlap). Children are embedded in FAISS. They are used **only** to find parents. **They are never sent to the LLM.** |
| **Table chunk** | A special child chunk with `content_type = "TABLE_DATA"`. It is embedded in FAISS. It contains the complete reconstructed table, exactly as stored. It is sent to the LLM as-is when it appears in the top results. |
| **Candidate** | A vector returned by FAISS. `candidate_k = 24`. |
| **Top 8** | The first eight usable child results inspected after the FAISS search. Tables count as child results. |
| **Distinct parent** | A unique `PARENT_SECTION` record. Multiple child or table matches that belong to the same parent produce **one** parent in the evidence packet. |
| **Evidence packet** | The validated flat list of `PARENT` and `TABLE` entries sent to the LLM. Each entry has a stable `source_id`; parent entries carry related-parent previews. It never contains child text. |
| **Deterministic wrapper** | Backend code that parses the LLM's JSON, validates it against a schema, checks IDs and actions, then calls the correct tool or function. It never passes raw LLM text downstream. |
| **Retry** | One additional LLM call after the initial LLM call. A retry may be preceded by exactly one tool call. |
| **Initial attempt** | The first retrieval plus the first LLM call. This is **not** counted as a retry. |
| **Last try** | The final allowed retry. It is answer-only and has no tool access. |

---

## 3. Fixed chunking facts this document relies on

These are already implemented and are not changed here.

| Chunk type | Target | Soft limit | Hard limit | Embedded in FAISS? | Sent to LLM? |
|---|---:|---:|---:|---|---|
| Narrative child | 350 | 500 | 600 | Yes | **No** |
| Parent section | 1,800 | 2,400 | 2,700 | No | **Yes** |
| Table chunk | 900 | 1,400 | 1,800 | Yes | **Yes, as-is** |

Additional fixed facts:

- A parent never cuts a child unless that child itself is oversized.
- A chunk may cross the soft limit to preserve a complete paragraph, list, or child, but must not cross the hard limit.
- Split children share a `child_group_id` and list related child IDs.
- Split parents share a `parent_group_id` and list related parent IDs.
- Tables split only by complete rows, repeating headers, periods, and units.
- Table quality flags such as `REVIEW_REQUIRED` are metadata. Retrieval does **not** filter tables by quality.
- Parents contain `related_parent_ids` and a short related-parent preview in their metadata. This is the information the LLM uses when deciding whether to request related parents.

---

## 4. Query routing

Every request is classified before any database or FAISS call.

### 4.1 Routes

| Route | Meaning | DB call? | FAISS call? | Retries? |
|---|---|---|---|---|
| `APP_HELP` | High-level question about the application itself. Example: "What does this application do?" | No | No | No |
| `OUT_OF_SCOPE` | Question unrelated to the application or its documents. Example: "Who is Messi?" or "What colour is an apple?" | No | No | No |
| `RAG` | Question that needs evidence from the uploaded documents. Example: "What was revenue in FY 2024?" | Yes | Yes | No |
| `CREDIT_MEMO` | Credit-memo section generation. | Yes | Yes | Yes, per section |

### 4.2 Router output contract

The router is an LLM call that must return exactly this JSON:

```json
{
  "route": "APP_HELP | OUT_OF_SCOPE | RAG | CREDIT_MEMO",
  "reason": "short reason"
}
```

The deterministic wrapper validates the enum. Anything else is treated as `OUT_OF_SCOPE`; the router path is zero-retry. A malformed router JSON response is surfaced as a `502` by the API rather than repaired with another LLM call.

### 4.3 General-query behaviour

- `APP_HELP` is answered from a **static application context** that is included in the prompt. It explains what the application does, what documents it accepts, and what the assistant can help with.
- `OUT_OF_SCOPE` receives a fixed polite refusal:

  > "I'm sorry, I can only answer questions about this application and the documents you've uploaded."

- General routing must not load the application from PostgreSQL and must not search FAISS.
- If an application-level question actually needs document evidence, the router sends it to `RAG`.

---

## 5. Retrieval rules (RAG and credit memo)

### 5.1 Search procedure

```
1. Embed the user query with the same embedding model used for children and tables.
2. Ask FAISS for candidate_k = 24 vectors.
3. Inspect the first 8 usable child results.
4. Resolve each result:
   - CHILD_CHUNK match  -> resolve its bounded parent.
   - TABLE_DATA match   -> keep the table chunk as-is AND resolve its bounded parent.
5. Deduplicate parents. Each parent appears once.
6. Select at most 2 distinct parents, and at least 1 if evidence exists.
7. Build the evidence packet with parents and matched tables only.
```

### 5.2 Search settings

| Setting | Value |
|---|---|
| `candidate_k` | 24 (minimum candidate window) |
| Results inspected | Top 8 usable application child results (tables count as child results) |
| Distinct parents selected | Maximum 2, minimum 1 when evidence exists |
| Ranking | FAISS similarity only |
| Reranking | None |
| Token trimming | None |
| Table row filtering | None |
| Separate table fetch | None |

> **Shared-index note:** the FAISS file is shared by all applications. The retriever may search more than 24 raw vectors so it can find this application's vectors, but it only inspects the first eight usable results that belong to the application. The extra vectors never reach the LLM.

### 5.3 What happens when a child matches

- The child is used only to find its parent.
- The child text is **not** placed in the evidence packet.
- The parent text is placed in the evidence packet.
- The parent is cited.

### 5.4 What happens when a table matches

- The table chunk is placed in the evidence packet **as-is**.
- Its bounded parent is also placed in the evidence packet.
- The table is cited as a table source.
- The parent is cited if it is used for narrative context.
- If several tables share the same parent, the parent appears once; each matched table appears separately.
- If a table appears in the top 8 but its parent is a third distinct parent, the table is not sent. The max-2-parent rule wins; no type-based reranking is allowed.

### 5.5 Deduplication rule

- Deduplicate by parent ID, not by child ID.
- If two children point to the same parent, send the parent once.
- If a table and a child point to the same parent, send the parent once and the table separately.
- Never send the same parent twice, even if it arrived through different children.

### 5.6 No trimming rule

- Do not count tokens during retrieval.
- Do not remove parents to fit a budget.
- Do not shorten tables.
- Do not drop rows.
- Do not re-embed or summarize evidence before the LLM sees it.
- The top-8 / max-2-parents rule is a **selection** rule, not a token cap.

---

## 6. Evidence packet

The wrapper builds one packet for the LLM. Its shape is fixed.

The implementation uses a flat list so parents and their matched tables stay in similarity order:

```json
[
  {
    "source_id": "DOC1-CONTENT-101",
    "source_type": "PARENT",
    "content_id": 101,
    "parent_content_id": 101,
    "chunk_id": "PG-SEC-0004-PART-001",
    "document_id": 1,
    "page": 4,
    "page_end": 5,
    "section": "Financial review",
    "document_name": "FY2024 Annual Report.pdf",
    "text": "complete parent text as stored",
    "related_parents": [
      {
        "parent_id": "PG-SEC-0004-PART-002",
        "content_id": 102,
        "document_id": 1,
        "section_title": "Financial review (continued)",
        "pages": "5-6",
        "part": "2 of 2"
      }
    ]
  },
  {
    "source_id": "DOC1-CONTENT-205",
    "source_type": "TABLE",
    "content_id": 205,
    "parent_content_id": 101,
    "chunk_id": "TG-TABLE-0007-PART-001",
    "table_id": "TABLE-0007",
    "document_id": 1,
    "page": 4,
    "page_end": 4,
    "section": "Revenue by period",
    "document_name": "FY2024 Annual Report.pdf",
    "text": "complete table chunk exactly as stored"
  }
]
```

Rules:

- `text` is the stored text. It is not regenerated.
- A `PARENT` entry never contains child text.
- A `TABLE` entry is never shortened, trimmed, or row-filtered.
- `related_parents[]` lists only parents the LLM is allowed to request.
- Every entry is itself a citation. There is no separate `citations[]` array in the runtime packet; the prompt builder assigns `S1..Sn` aliases to the entries it sends.

---

## 7. Deterministic structured-output wrapper

This is the most important part of the design.

### 7.1 Core rule

> **The LLM never calls a tool directly. The LLM returns structured JSON. The deterministic wrapper validates it and calls the tool or function.**

No downstream component ever receives free-form LLM text.

### 7.2 Wrapper pipeline

```
raw LLM response
      |
      v
1. JSON parse
      |
      v
2. Schema validation
      |
      v
3. Semantic validation
   - allowed IDs
   - allowed action
   - required fields for that action
   - citation IDs exist in the evidence packet
      |
      v
4. Dispatch
   - ANSWER              -> return validated section
   - FETCH_RELATED_PARENTS -> PostgreSQL tool
   - VECTOR_SEARCH       -> FAISS tool
      |
      v
5. Normalize tool result
      |
      v
6. Send the normalized result to the next LLM call
```

### 7.3 Validation rules

| Check | Rule |
|---|---|
| JSON | Must be exactly one JSON object. Code fences are removed before parsing. |
| Schema | Must match the selected contract. Extra fields are rejected. |
| Action | Must be one of `ANSWER`, `FETCH_RELATED_PARENTS`, `VECTOR_SEARCH`, unless the call is answer-only. |
| Parent IDs | Every requested `parent_id` must appear in the current `related_parents[]` list. |
| Parent count | The total number of distinct parents must never exceed 2. |
| Search query | `VECTOR_SEARCH` must include a non-empty `search_query`. |
| Citations | Every `source_id` in the answer must match an entry `source_id` in the current flat packet. |
| Section answer | Must match the batch's output contract (`facts`, `narrative`, or `items`). |

### 7.4 Rejection rules

- Unknown or invented parent IDs are rejected. No database call is made.
- A `FETCH_RELATED_PARENTS` action is rejected if 2 parents are already present.
- An action in an answer-only call is rejected.
- Invalid output consumes one retry because it consumed one LLM call.
- On the last try, invalid output produces a deterministic fallback section. No further LLM call is made.
- A batch with no evidence at all returns `status = "not_disclosed"`. A batch whose final answer is invalid returns `status = "pending_review"`. Both include a caveat.

### 7.5 Why this is deterministic

- The wrapper decides which tool runs.
- The wrapper validates every ID before use.
- The wrapper enforces the parent cap.
- The wrapper enforces the retry budget.
- The wrapper can always produce a fallback without asking the LLM again.
- The LLM can only choose from the evidence and IDs it was shown.

---

## 8. Credit-memo retry logic

Retries exist **only** in credit-memo generation.

### 8.1 The three LLM actions

| Action | Meaning | Tool called |
|---|---|---|
| `ANSWER` | The LLM has enough evidence and returns the final section. | None |
| `FETCH_RELATED_PARENTS` | The LLM wants parents that are related to the current parents. | PostgreSQL lookup by parent ID |
| `VECTOR_SEARCH` | The LLM wants another FAISS search with a reformulated query. | FAISS search |

### 8.2 Action JSON contracts

**ANSWER**

```json
{
  "action": "ANSWER",
  "answer": {
    "status": "available",
    "summary": "final section text",
    "facts": [],
    "observations": [],
    "items": [],
    "caveats": [],
    "source_ids": ["S1"]
  }
}
```

The `answer` object must match the batch's output contract. Only the field for the batch's output kind is present (`facts` for a facts batch, `observations` for a narrative batch, `items` for an items batch). The wrapper extracts only `answer` and validates it.

**FETCH_RELATED_PARENTS**

```json
{
  "action": "FETCH_RELATED_PARENTS",
  "reason": "The current parent is part 1 of 2 and the figure is in part 2.",
  "parent_ids": ["PG-SEC-0004-PART-002"]
}
```

**VECTOR_SEARCH**

```json
{
  "action": "VECTOR_SEARCH",
  "reason": "The current parents discuss revenue but do not contain the FY2024 table.",
  "search_query": "FY2024 revenue table consolidated income statement"
}
```

### 8.3 Retry budget

| Section importance | Retries after the initial attempt | Total LLM calls after retrieval | Tool calls allowed |
|---|---:|---:|---:|
| Important | 3 | 4 | 3 |
| Less important | 1 | 2 | 1 |
| RAG | 0 | 1 | 0 |
| General | 0 | 1 | 0 |

**The initial attempt is not a retry.**  
A retry is one additional LLM call after the initial LLM call.

### 8.4 Exact call sequence — important section (3 retries)

```
Initial retrieval
      |
      v
Call 0: action allowed
      |
      +-- ANSWER ------------------------------> done
      |
      +-- FETCH_RELATED_PARENTS / VECTOR_SEARCH
                 |
                 v
          tool runs
                 |
                 v
Call 1 (retry 1): action allowed
      |
      +-- ANSWER ------------------------------> done
      |
      +-- action
                 |
                 v
          tool runs
                 |
                 v
Call 2 (retry 2): action allowed
      |
      +-- ANSWER ------------------------------> done
      |
      +-- action
                 |
                 v
          tool runs
                 |
                 v
Call 3 (retry 3, LAST TRY): ANSWER ONLY
      |
      +-- valid final section ------------------> done
      |
      +-- invalid / action returned -----------> deterministic fallback
```

### 8.5 Exact call sequence — less-important section (1 retry)

```
Initial retrieval
      |
      v
Call 0: action allowed
      |
      +-- ANSWER ------------------------------> done
      |
      +-- FETCH_RELATED_PARENTS / VECTOR_SEARCH
                 |
                 v
          tool runs
                 |
                 v
Call 1 (retry 1, LAST TRY): ANSWER ONLY
      |
      +-- valid final section ------------------> done
      |
      +-- invalid / action returned -----------> deterministic fallback
```

### 8.6 The last-try rule

> **The final retry must return only a final answer. It must not return a tool action.**

On the last try:

- The wrapper uses an **answer-only contract** — the batch's normal section contract.
- The `action` field is not part of the schema.
- No tool is available.
- `FETCH_RELATED_PARENTS` and `VECTOR_SEARCH` are invalid.
- If the section is invalid, the wrapper returns a deterministic fallback:
  - `status = "pending_review"` (or `"not_disclosed"` when no evidence was found).
  - `summary = null`.
  - `caveats` includes the validation error or `"The final attempt was invalid."`.
  - `source_ids = []`.
- No further LLM call is made.

### 8.7 What counts as a retry

| Event | Consumes a retry? |
|---|---|
| Initial retrieval + first LLM call | No |
| LLM returns a valid action; tool runs; next LLM call | Yes |
| LLM returns invalid JSON; wrapper re-prompts | Yes |
| LLM returns an unknown parent ID; wrapper re-prompts | Yes |
| LLM returns an action when 2 parents are already present; wrapper re-prompts | Yes |
| JSON repair call | Not used in the memo retry loop. The correction call is the retry. |
| Deterministic fallback | No LLM call, no retry |

### 8.8 Retry exhaustion

When the budget is exhausted:

1. The wrapper performs the last-try answer-only call.
2. If that answer is valid, it is used.
3. If it is invalid, the deterministic fallback is used.
4. The batch is marked with a quality caveat so the memo validator can surface it.
5. The pipeline continues with the other batches. It never loops forever.

### 8.9 Default importance mapping

| Importance | Retries | Batches |
|---|---:|---|
| Important | 3 | `revenue_profit`, `margins_returns`, `assets_equity`, `liquidity_working_capital`, `operating_cash_flow`, `capex_financing`, `debt_liquidity`, `maturities_capacity`, `existing_security`, `proposed_security`, `credit_strengths`, `credit_risks`, `risk_mitigants`, `policy_exceptions`, `proposed_terms` |
| Less important | 1 | `legal_identity`, `ownership_background`, `business_operations`, `markets_concentration`, `leadership_control`, `governance_controls` |

This mapping lives in the batch definition, not in the LLM prompt. The LLM cannot change its own retry budget.

---

## 9. RAG behaviour — no retries

RAG is intentionally simple.

```
classify -> RAG
   |
   v
load application (PostgreSQL)
   |
   v
vector_search (FAISS, 24 / top 8 / max 2 parents)
   |
   v
build evidence packet (parents + tables only)
   |
   v
one LLM answer call
   |
   v
return answer with citations
```

Rules:

- No `FETCH_RELATED_PARENTS`.
- No second `VECTOR_SEARCH`.
- No action envelope.
- If the evidence is insufficient, the LLM says so in the answer.
- The prompt must not ask the LLM to reconstruct or display the table. It uses the table values to answer the question.
- Tables are sent as-is.
- Child chunks are never sent.
- Citations are mandatory.

---

## 10. General behaviour — no retrieval

```
classify -> APP_HELP
   |
   v
static application context in prompt
   |
   v
one LLM answer call
   |
   v
return answer (no sources)

classify -> OUT_OF_SCOPE
   |
   v
fixed polite refusal
```

Rules:

- No PostgreSQL call.
- No FAISS call.
- No evidence packet.
- No retries.
- Application context is static and safe to include in every general prompt.
- Out-of-scope questions are refused politely, not answered from general knowledge.

Example static context topics:

- What the application does.
- What document types it accepts.
- How the credit-memo workflow works.
- What the assistant can and cannot answer.
- What the user should upload or select.

---

## 11. Table handling summary

| Situation | What is sent to the LLM |
|---|---|
| Table appears in the top 8 | The table chunk as-is, plus its parent. |
| Table does not appear in the top 8 | Nothing. Tables are not fetched separately. |
| Several tables share one parent | All matched tables are sent as-is; the parent is sent once. |
| Table is large | It is already split by the chunker at complete-row boundaries. Each part is sent as-is. |
| Table has `REVIEW_REQUIRED` | It is still sent. Quality flags are metadata, not a retrieval filter. |
| RAG question | The LLM uses the table to answer. It does not reconstruct or display the table. |
| Credit-memo question | The LLM may reconstruct the table from the as-is chunk when writing the memo. |

No table markdown is stripped. No header is removed. No period or unit is removed. No row is filtered.

---

## 12. Citation rules

| Evidence | Citation target |
|---|---|
| Narrative parent | The parent's `content_id` / source ID |
| Table chunk | The table's `content_id` / source ID |
| Child chunk | Never cited directly, because it is never sent |

Additional rules:

- Every material statement must cite at least one supplied source ID.
- Citation IDs must exist in the evidence packet.
- Unknown citation IDs are rejected by the wrapper.
- Citation arrays are not artificially limited to two. If the packet contains more than two evidence items, the LLM may cite any of them.
- The wrapper validates `source_ids ⊆ allowed_source_ids`.
- **Source ID convention:** the stored source ID is stable: `DOC<document_id>-CONTENT-<content_id>`. RAG prompts use these IDs directly. Credit-memo batches relabel the same evidence as `S1`, `S2`, … for compact prompts; the wrapper expands each alias back to the stable source ID before validation and storage. The LLM never invents database IDs.

---

## 13. Tool catalogue

| Tool | Input (validated) | Output | Used by |
|---|---|---|---|
| `classify_query` | User query + static app context | Route JSON | All requests |
| `load_application` | Application reference | Borrower + application facts | RAG, credit memo |
| `embed_query` | Query text | Vector | RAG, credit memo |
| `vector_search` | Query vector, application ID | Up to 2 parents + matched tables + citation IDs | RAG, credit memo |
| `fetch_related_parents` | Application ID + document ID + allowed parent chunk IDs | Parent records from PostgreSQL | Credit memo only |
| `generate_general_answer` | Query + static context | General answer JSON | `APP_HELP` |
| `generate_rag_answer` | Query + evidence packet | RAG answer JSON | `RAG` |
| `generate_memo_action` | Batch + evidence packet + retry state | Action JSON | Credit memo |
| `validate_section` | Section JSON + contract | Valid / errors | Credit memo |
| `assemble_memo` | All validated sections | Memo payload | Credit memo |

The LLM does not call these tools. The wrapper calls them after validating the LLM's structured output.

---

## 14. Node and edge graph

### 14.1 Top level

```
START
  |
  v
classify_query
  |
  +--> APP_HELP ------> generate_general_answer ------> END
  |
  +--> OUT_OF_SCOPE --> polite_refusal ---------------> END
  |
  +--> RAG ------------> load_application
  |                        |
  |                        v
  |                     vector_search
  |                        |
  |                        v
  |                     build_evidence_packet
  |                        |
  |                        v
  |                     generate_rag_answer --------> END
  |
  +--> CREDIT_MEMO -----> memo batch loop
                           |
                           v
                        combine -> validate -> persist -> END
```

### 14.2 Credit-memo batch loop

```
memo_retrieve
  |
  v
memo_llm_action
  |
  +--> ANSWER ---------------------------> validate_section -> done
  |
  +--> FETCH_RELATED_PARENTS -> fetch_related_parents
  |                                  |
  |                                  v
  |                            memo_llm_action
  |
  +--> VECTOR_SEARCH ----------> vector_search
                                     |
                                     v
                               memo_llm_action
  |
  +--> budget exhausted / last try -> answer-only call
                                     |
                                     +--> valid -> done
                                     |
                                     +--> invalid -> fallback -> done
```

---

## 15. Worked examples

### 15.1 General question

**User:** "Who is Messi?"

```
classify_query -> OUT_OF_SCOPE
polite_refusal -> "I'm sorry, I can only answer questions about this application and the documents you've uploaded."
```

No DB. No FAISS.

### 15.2 General application question

**User:** "What does this application do?"

```
classify_query -> APP_HELP
generate_general_answer (static context) ->
  "This application helps you upload credit documents, extract their contents,
   review tables, and generate a grounded credit memo."
```

No DB. No FAISS.

### 15.3 RAG question

**User:** "What was revenue in FY 2024?"

```
classify_query -> RAG
load_application
vector_search:
  candidate_k = 24
  inspect top 8
  child match A -> parent P1
  table match T1 -> table T1 + parent P2
  distinct parents: P1, P2 (max 2)
build evidence packet:
  parents: P1, P2
  tables: T1 as-is
  no child text
generate_rag_answer:
  uses P1 and T1
  cites SRC-1 (P1) and SRC-2 (T1)
  does not reconstruct the table
```

No retry.

### 15.4 Credit memo — important section, answers first time

```
memo_retrieve -> parents P1, P2; table T1
memo_llm_action -> {"action":"ANSWER","answer":{...}}
validate_section -> done
```

One LLM call. Zero retries.

### 15.5 Credit memo — important section, requests related parent

```
memo_retrieve -> parent P1 (part 1 of 2)
memo_llm_action -> {"action":"FETCH_RELATED_PARENTS","parent_ids":["P1-PART-002"]}
wrapper validates P1-PART-002 is in related_parents
fetch_related_parents -> P1-PART-002
memo_llm_action (retry 1) -> {"action":"ANSWER","answer":{...}}
validate_section -> done
```

One retry used.

### 15.6 Credit memo — less-important section, last try

```
memo_retrieve -> parent P1
memo_llm_action -> {"action":"VECTOR_SEARCH","search_query":"..."}
vector_search -> new evidence
Call 1 (retry 1, LAST TRY): answer-only contract
  -> valid final section -> done
```

One retry used. No tool action allowed on the last call.

### 15.7 Credit memo — retry exhaustion

```
Call 0: action
Call 1: action
Call 2: action
Call 3 (retry 3, LAST TRY): answer-only
  -> invalid output
deterministic fallback:
  status = "pending_review"
  summary = null
  caveats = ["The final retry did not produce a valid answer."]
```

No infinite loop.

---

## 16. What the system must not do

- Do not send child chunks to the LLM.
- Do not send child text inside a parent-looking block.
- Do not fetch tables separately from the top-8 results.
- Do not trim parent or table text.
- Do not apply a token budget at retrieval time.
- Do not rerank by priority, preferred type, or quality.
- Do not let the LLM call tools directly.
- Do not let the LLM invent parent IDs.
- Do not allow more than 2 distinct parents.
- Do not allow a tool action on the last retry.
- Do not retry in RAG.
- Do not retry in general queries.
- Do not answer out-of-scope general questions from world knowledge.
- Do not cite evidence that is not in the packet.
- Do not silently accept `REVIEW_REQUIRED` tables as correct; pass their quality metadata through.

---

## 17. Decision register

| ID | Decision |
|---|---|
| D1 | `candidate_k = 24`. |
| D2 | Inspect the top 8 child results. Tables count as child results. |
| D3 | Select at most 2 distinct parents, minimum 1 when evidence exists. |
| D4 | Use FAISS similarity only. No reranking. |
| D5 | Send parents and tables to the LLM only. Never children. |
| D6 | Tables are sent as-is. No trimming, no row filtering, no reconstruction before the prompt. |
| D7 | Table matches also send their bounded parent. |
| D8 | Tables are not fetched separately. |
| D9 | No token-count check or trimming at retrieval. |
| D10 | RAG has one retrieval and one answer. No retries. |
| D11 | General queries use static application context. No DB, no FAISS. |
| D12 | Out-of-scope general questions are politely refused. |
| D13 | Every LLM output is structured JSON validated by a deterministic wrapper. |
| D14 | The LLM never calls tools directly. The wrapper dispatches. |
| D15 | Credit-memo important sections get 3 retries after the initial attempt. |
| D16 | Credit-memo less-important sections/batches get 1 retry after the initial attempt. |
| D17 | The initial retrieval is not counted as a retry. |
| D18 | The last retry is answer-only. No tool action is allowed. |
| D19 | Unknown or invented parent IDs are rejected. |
| D20 | The parent cap of 2 is enforced by the wrapper, not by the LLM. |
| D21 | Citations are mandatory and must reference supplied evidence IDs. |
| D22 | Citation arrays are not artificially limited to two; any supplied evidence ID may be cited. |
| D23 | Table quality flags are metadata. Retrieval does not filter by them. |
| D24 | Retry budgets live in batch definitions, not in the prompt. |

---

## 18. Implementation map (where these rules live)

| Concern | File |
|---|---|
| Query routing | `backend/app/ai/retrieval/workflow.py` |
| Router/general/RAG/memo prompts | `backend/app/ai/prompts/retrieval_prompts.py` |
| FAISS search + parent/table resolution | `backend/app/ai/retrieval/faiss_retriever.py` |
| Memo batch retrieval | `backend/app/ai/retrieval/section_retriever.py` |
| Memo batch retry loop + structured wrapper | `backend/app/services/credit_memo_extraction_service.py` |
| Batch importance + retry budget | `backend/app/services/credit_memo_batch_definitions.py` |
| Memo prompt contracts + evidence blocks | `backend/app/ai/prompts/credit_memo_prompts.py` |
| Structured JSON parsing | `backend/app/ai/retrieval/json_utils.py` |
| Chunk metadata for related parents | `backend/app/services/batch_content_ingestion_service.py` |
| Existing section validators | `backend/app/services/credit_memo_validation_service.py` |

---

## 19. Final checklist

Before implementation is considered correct:

- [x] A general query makes zero PostgreSQL and zero FAISS calls.
- [x] An out-of-scope question gets a polite refusal.
- [x] A RAG query inspects top 8, selects max 2 parents, and sends no child text.
- [x] A table match sends the table as-is and its parent.
- [x] No token trimming exists in the retrieval path.
- [x] No reranking exists in the retrieval path.
- [x] Every LLM output is schema-validated before use.
- [x] The LLM cannot call a tool directly.
- [x] Unknown parent IDs are rejected.
- [x] The parent cap of 2 is enforced.
- [x] Important memo sections get exactly 3 retries after the initial attempt.
- [x] Less-important memo sections get exactly 1 retry after the initial attempt.
- [x] The last retry is answer-only.
- [x] RAG has no retries.
- [x] Citations are validated against the evidence packet.
- [x] Retry exhaustion produces a deterministic fallback, never a loop.
