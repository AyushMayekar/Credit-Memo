"""Demo script showing the new pipeline for all three query types.

This shows the architecture without requiring a live LLM/DB.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add new_pipeline to path
sys.path.insert(0, str(Path(__file__).parent))

from new_pipeline.ai.retrieval.workflow import RagWorkflow, answer_user_query
from new_pipeline.ai.retrieval.section_agent import BatchAgentState, run_batch_agent
from new_pipeline.ai.prompts.credit_memo_prompts import build_batch_messages
from new_pipeline.ai.prompts.retrieval_prompts import (
    ROUTER_PROMPT,
    GENERAL_PROMPT,
    RAG_ANSWER_PROMPT,
)


def demo_general_query():
    """Demo: GENERAL query is answered directly by the router, no retrieval."""
    print("=" * 60)
    print("DEMO 1: GENERAL Query")
    print("=" * 60)
    query = "How does the credit memo application work?"
    
    # Simulate the router logic
    lower = query.casefold()
    document_terms = ("revenue", "profit", "risk", "borrower", "company",
                      "document", "report", "financial", "table", "chart")
    
    has_terms = any(term in lower for term in document_terms)
    is_short = len(lower.split()) <= 8
    
    if not has_terms and is_short:
        # Router returns GENERAL
        print(f"Query: '{query}'")
        print("Router: GENERAL (short query, no document terms)")
        print("→ One LLM call, answer immediately (no retrieval)")
        print("→ No FAISS search, no evidence needed")
    else:
        print("→ Would route to RAG (has terms or long query)")
    print()


def demo_rag_query():
    """Demo: RAG query goes through one retrieval + LLM answer pass."""
    print("=" * 60)
    print("DEMO 2: RAG Query")
    print("=" * 60)
    query = "What is the borrower's revenue for FY2023?"
    
    print(f"Query: '{query}'")
    print("Router: RAG (contains financial term 'revenue')")
    print("→ Step 1: Embed query + FAISS search (2 contexts)")
    print("→ Step 2: LLM answers using only the 2 evidence items")
    print("→ No retry loops, hard stop after 1 round")
    print("→ Answer grounded in cited evidence [1], [2]")
    print()


def demo_credit_memo_query():
    """Demo: CREDIT_MEMO query runs per-batch agents with 5 workers."""
    print("=" * 60)
    print("DEMO 3: Credit Memo Query")
    print("=" * 60)
    query = "Generate a credit memo for this application"
    application_reference = "APP-001"
    
    print(f"Query: '{query}'")
    print(f"Application: {application_reference}")
    print("Router: CREDIT_MEMO (request_type=CREDIT_MEMO)")
    print("→ Step 1: Router identifies CREDIT_MEMO route")
    print("→ Step 2: Run 21 batches concurrently (max 5 workers)")
    print("→ Each batch: retrieval loop (max 3 rounds, score 1-5)")
    print("→ Bounded evidence: 4 contexts max, ~12k chars")
    print("→ Citations: [1], [2], [3], ... up to [6]")
    print("→ Last pass used as final result")
    print("→ Results combined by CreditMemoBatchCombiner")
    print("→ Assembly → Calculation → Validation (separate services)")
    print()


def demo_citation_format():
    """Show the [1], [2] vs s1, s2 difference."""
    print("=" * 60)
    print("CITATION FORMAT DEMO")
    print("=" * 60)
    print("OLD format (s1, s2):")
    print("  - source_id: 'SRC-1', cited as 's1' in prompt")
    print("  - max 2 citations per fact/item")
    print()
    print("NEW format ([1], [2]):")
    print("  - source_id: 'SRC-1', cited as '[1]' in prompt")
    print("  - max 6 per section (from build_output_contract)")
    print("  - Aliases remapped globally across rounds")
    print()
    print("Prompt rule: 'Every material statement must cite supplied source aliases")
    print("exactly as [1], [2], [3], etc.'")
    print()


def demo_score_gating():
    """Show the 1-5 score + missing/next_query logic."""
    print("=" * 60)
    print("SCORE GATING LOGIC (1-5)")
    print("=" * 60)
    print("Score 5: All needed facts present → status=available, stop")
    print("Score 4+: Sufficient but some gaps → may trigger round 2 if retryable")
    print("Score 3: Partial → trigger round 2 if retryable items exist")
    print("Score ≤2: Insufficient → trigger round 2 if retryable + next_query")
    print("→ Max 3 rounds total hard stop")
    print("→ If no retryable gaps or no next_query → stop and mark not_disclosed")
    print("→ Last pass always used as final result, regardless of score")
    print()
    print("Missing item format:")
    print("  {{'label': 'revenue FY2024', 'retryable': True, 'next_query': 'revenue FY2024'}}")
    print("  → retryable=true only if fact likely findable in other docs")
    print("  → next_query max 12 words / 160 chars")
    print()
    print("Deterministic gates (always check before LLM score):")
    print("  1. Required slots empty → force retry")
    print("  2. Expected content type not retrieved (e.g. no TABLE_DATA)")
    print("  3. Citations missing from output → force retry")
    print("  4. LLM score high but deterministic check fails → trust deterministic")


def main():
    print("NEW PIPELINE DEMONSTRATION")
    print("=" * 60)
    print("Features:")
    print("  • Citations: [1], [2], [3] ... (not s1, s2)")
    print("  • Score: 1-5 integer with explicit thresholds")
    print("  • Max 3 retrieval rounds per batch")
    print("  • Evidence caps: 4 contexts, ~12k chars")
    print("  • 5 worker threads for parallel batch processing")
    print("  • Hard stop: no infinite loops")
    print("  • Last pass used as final result")
    print("  • Router: GENERAL→one LLM call, RAG→one retrieval pass,")
    print("    CREDIT_MEMO→per-batch agents")
    print()
    demo_general_query()
    demo_rag_query()
    demo_credit_memo_query()
    demo_citation_format()
    demo_score_gating()
    print("\nAll three query types complete with retrieval pipeline.")
    print("Next steps: install deps, connect LLM/DB, run evals.")


if __name__ == "__main__":
    main()
