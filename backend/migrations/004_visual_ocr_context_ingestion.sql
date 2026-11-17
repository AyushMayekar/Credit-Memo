BEGIN;

ALTER TABLE credit_ai.extracted_images
    ADD COLUMN IF NOT EXISTS content_id INTEGER REFERENCES credit_ai.document_contents(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS visual_reference VARCHAR(50),
    ADD COLUMN IF NOT EXISTS section_id VARCHAR(50),
    ADD COLUMN IF NOT EXISTS section_title TEXT,
    ADD COLUMN IF NOT EXISTS candidate_type VARCHAR(50),
    ADD COLUMN IF NOT EXISTS bounding_box JSONB,
    ADD COLUMN IF NOT EXISTS metadata_path TEXT,
    ADD COLUMN IF NOT EXISTS ocr_output_path TEXT,
    ADD COLUMN IF NOT EXISTS ocr_lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS ocr_average_confidence DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS selectable_text JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS nearby_text JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS generated_title TEXT,
    ADD COLUMN IF NOT EXISTS visual_type VARCHAR(40),
    ADD COLUMN IF NOT EXISTS generated_summary TEXT,
    ADD COLUMN IF NOT EXISTS reporting_periods JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS units JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS important_facts JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS financial_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS uncertainties JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS review_required BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS ocr_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS context_status VARCHAR(30) NOT NULL DEFAULT 'PENDING',
    ADD COLUMN IF NOT EXISTS structured_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS ux_extracted_images_document_reference
    ON credit_ai.extracted_images(document_id, visual_reference);
CREATE INDEX IF NOT EXISTS ix_extracted_images_content_id
    ON credit_ai.extracted_images(content_id);
CREATE INDEX IF NOT EXISTS ix_extracted_images_document_page
    ON credit_ai.extracted_images(document_id, page_number);

COMMIT;
