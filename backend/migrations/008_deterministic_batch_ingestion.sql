BEGIN;
ALTER TABLE credit_ai.document_contents DROP CONSTRAINT IF EXISTS ck_document_contents_content_type;
ALTER TABLE credit_ai.document_contents DROP CONSTRAINT IF EXISTS document_contents_content_type_check;
ALTER TABLE credit_ai.document_contents ADD CONSTRAINT ck_document_contents_content_type CHECK (content_type IN ('PARENT_SECTION','CHILD_CHUNK','TABLE_DATA','VISUAL_DATA','TABLE_SUMMARY','IMAGE_SUMMARY','DOCUMENT_SUMMARY','PAGE_SUMMARY','TEXT'));
CREATE INDEX IF NOT EXISTS ix_document_contents_application_type ON credit_ai.document_contents(application_id,content_type);
COMMIT;
