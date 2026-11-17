BEGIN;

ALTER TABLE credit_ai.documents
    ADD COLUMN IF NOT EXISTS parsed_output_path TEXT,
    ADD COLUMN IF NOT EXISTS document_structure_path TEXT,
    ADD COLUMN IF NOT EXISTS parser_summary_path TEXT;

CREATE INDEX IF NOT EXISTS ix_documents_application_hash
    ON credit_ai.documents(application_id, file_hash);

COMMIT;
