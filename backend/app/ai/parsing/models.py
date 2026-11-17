from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class StructuralParsingResult:
    extraction_path: str
    output_directory: str
    parsed_document_path: str
    parser_summary_path: str
    parser_digest_path: str
    page_count: int
    included_page_count: int
    excluded_page_count: int
    section_count: int
    table_count: int
    accepted_record_count: int
    review_record_count: int
    rejected_record_count: int
    parser_status: str
