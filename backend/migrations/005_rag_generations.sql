BEGIN;
CREATE TABLE IF NOT EXISTS credit_ai.rag_generations (
 id SERIAL PRIMARY KEY,
 application_id INTEGER NOT NULL REFERENCES credit_ai.loan_applications(id) ON DELETE CASCADE,
 request_type VARCHAR(30) NOT NULL,
 route VARCHAR(30) NOT NULL,
 user_query TEXT,
 predefined_prompt_key VARCHAR(80),
 response_json JSONB NOT NULL,
 source_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb,
 status VARCHAR(30) NOT NULL DEFAULT 'COMPLETED',
 error_message TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_rag_generations_application_created
 ON credit_ai.rag_generations(application_id,created_at DESC);
COMMIT;
