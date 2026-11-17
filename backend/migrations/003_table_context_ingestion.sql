BEGIN;

-- This POC migration standardizes the extracted_tables contract used by the table pipeline.
ALTER TABLE credit_ai.extracted_tables
    ADD COLUMN IF NOT EXISTS content_id INTEGER REFERENCES credit_ai.document_contents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS table_reference VARCHAR(50),
    ADD COLUMN IF NOT EXISTS page_number INTEGER,
    ADD COLUMN IF NOT EXISTS section_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS section_title TEXT,
    ADD COLUMN IF NOT EXISTS bounding_box JSONB,
    ADD COLUMN IF NOT EXISTS original_rows JSONB,
    ADD COLUMN IF NOT EXISTS normalized_rows JSONB,
    ADD COLUMN IF NOT EXISTS table_markdown TEXT,
    ADD COLUMN IF NOT EXISTS json_path TEXT,
    ADD COLUMN IF NOT EXISTS markdown_path TEXT,
    ADD COLUMN IF NOT EXISTS image_path TEXT,
    ADD COLUMN IF NOT EXISTS nearby_text JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS generated_title TEXT,
    ADD COLUMN IF NOT EXISTS generated_summary TEXT,
    ADD COLUMN IF NOT EXISTS reporting_periods JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS units JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS important_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS financial_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS uncertainties JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS quality_score DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS quality_classification VARCHAR(40),
    ADD COLUMN IF NOT EXISTS review_required BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS context_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_tables_document_reference
    ON credit_ai.extracted_tables(document_id, table_reference);
CREATE INDEX IF NOT EXISTS ix_extracted_tables_content_id
    ON credit_ai.extracted_tables(content_id);
CREATE INDEX IF NOT EXISTS ix_extracted_tables_document_page
    ON credit_ai.extracted_tables(document_id, page_number);

COMMIT;
