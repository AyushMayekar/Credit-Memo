BEGIN;
CREATE TABLE IF NOT EXISTS credit_ai.processing_jobs (
 id SERIAL PRIMARY KEY, job_reference VARCHAR(60) UNIQUE NOT NULL,
 application_id INTEGER NOT NULL REFERENCES credit_ai.loan_applications(id) ON DELETE CASCADE,
 document_id INTEGER REFERENCES credit_ai.documents(id) ON DELETE CASCADE,
 job_type VARCHAR(40) NOT NULL, status VARCHAR(30) NOT NULL DEFAULT 'QUEUED',
 progress_percentage INTEGER NOT NULL DEFAULT 0,
 current_stage VARCHAR(60) NOT NULL DEFAULT 'QUEUED',
 current_stage_label VARCHAR(160) NOT NULL DEFAULT 'Waiting to begin',
 message TEXT, stage_details JSONB NOT NULL DEFAULT '[]'::jsonb,
 result_payload JSONB NOT NULL DEFAULT '{}'::jsonb, error_message TEXT,
 cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), started_at TIMESTAMPTZ,
 completed_at TIMESTAMPTZ, updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_processing_jobs_application ON credit_ai.processing_jobs(application_id, created_at DESC);
CREATE TABLE IF NOT EXISTS credit_ai.content_review_items (
 id SERIAL PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES credit_ai.loan_applications(id) ON DELETE CASCADE,
 document_id INTEGER NOT NULL REFERENCES credit_ai.documents(id) ON DELETE CASCADE,
 item_type VARCHAR(20) NOT NULL, item_reference VARCHAR(50) NOT NULL,
 page_number INTEGER NOT NULL, section_title TEXT, preview_path TEXT,
 source_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
 quality_status VARCHAR(40) NOT NULL DEFAULT 'CONFIRMED',
 selected_for_analysis BOOLEAN NOT NULL DEFAULT TRUE,
 excluded_by_user BOOLEAN NOT NULL DEFAULT FALSE, exclusion_reason TEXT,
 reviewed_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
 UNIQUE(document_id,item_type,item_reference)
);
ALTER TABLE credit_ai.loan_applications DROP CONSTRAINT IF EXISTS chk_application_status;
ALTER TABLE credit_ai.loan_applications ADD CONSTRAINT chk_application_status CHECK (status IN (
'DRAFT','DOCUMENTS_UPLOADED','PREPARING_DOCUMENTS','WAITING_FOR_CONTENT_REVIEW','PREPARING_AI','AI_READY','GENERATING_MEMO','MEMO_READY','FAILED'));
COMMIT;
