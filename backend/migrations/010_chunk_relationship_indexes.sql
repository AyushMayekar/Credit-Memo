BEGIN;

-- No new relationship column is required. document_contents.parent_content_id
-- already links CHILD_CHUNK and TABLE_DATA to PARENT_SECTION.
CREATE INDEX IF NOT EXISTS ix_document_contents_application_parent_type
    ON credit_ai.document_contents(application_id, parent_content_id, content_type);

CREATE INDEX IF NOT EXISTS ix_faiss_vector_mapping_application_active_type
    ON credit_ai.faiss_vector_mappings(application_id, is_active, content_type);

COMMIT;
