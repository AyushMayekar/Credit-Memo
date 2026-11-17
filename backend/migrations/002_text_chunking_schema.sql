BEGIN;

ALTER TABLE credit_ai.document_contents
    ADD COLUMN IF NOT EXISTS page_end INTEGER,
    ADD COLUMN IF NOT EXISTS token_count INTEGER,
    ADD COLUMN IF NOT EXISTS chunk_index INTEGER,
    ADD COLUMN IF NOT EXISTS embedding_text TEXT,
    ADD COLUMN IF NOT EXISTS chunking_strategy VARCHAR(80),
    ADD COLUMN IF NOT EXISTS content_metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

-- Replace the old content-type constraint if it exists.
ALTER TABLE credit_ai.document_contents
    DROP CONSTRAINT IF EXISTS ck_document_contents_content_type;
ALTER TABLE credit_ai.document_contents
    DROP CONSTRAINT IF EXISTS document_contents_content_type_check;

ALTER TABLE credit_ai.document_contents
    ADD CONSTRAINT ck_document_contents_content_type
    CHECK (content_type IN (
        'PARENT_SECTION', 'CHILD_CHUNK', 'TABLE_SUMMARY',
        'IMAGE_SUMMARY', 'DOCUMENT_SUMMARY', 'PAGE_SUMMARY', 'TEXT'
    ));

CREATE INDEX IF NOT EXISTS ix_document_contents_parent
    ON credit_ai.document_contents(parent_content_id);
CREATE INDEX IF NOT EXISTS ix_document_contents_document_type
    ON credit_ai.document_contents(document_id, content_type);
CREATE INDEX IF NOT EXISTS ix_document_contents_metadata_gin
    ON credit_ai.document_contents USING GIN(content_metadata);

COMMIT;
