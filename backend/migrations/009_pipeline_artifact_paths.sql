BEGIN;

ALTER TABLE credit_ai.documents
    ADD COLUMN IF NOT EXISTS extraction_path TEXT,
    ADD COLUMN IF NOT EXISTS extraction_summary_path TEXT,
    ADD COLUMN IF NOT EXISTS parsed_document_path TEXT;

UPDATE credit_ai.documents
SET extraction_path = document_structure_path
WHERE extraction_path IS NULL
  AND document_structure_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_documents_extraction_status
    ON credit_ai.documents(application_id, extraction_status);

COMMIT;
