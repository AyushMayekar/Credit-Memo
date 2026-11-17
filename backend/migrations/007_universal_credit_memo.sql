BEGIN;
ALTER TABLE credit_ai.credit_memos ADD COLUMN IF NOT EXISTS schema_version VARCHAR(30), ADD COLUMN IF NOT EXISTS raw_generation_json JSONB, ADD COLUMN IF NOT EXISTS validation_report JSONB, ADD COLUMN IF NOT EXISTS generated_html_path TEXT;
ALTER TABLE credit_ai.credit_memos ALTER COLUMN prompt_version TYPE VARCHAR(80);
COMMIT;
