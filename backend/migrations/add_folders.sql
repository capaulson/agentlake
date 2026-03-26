-- Migration: Add folders table and folder_id to files
-- Run manually against the database since Alembic is not easily available.

BEGIN;

CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    parent_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    path VARCHAR(2048) NOT NULL DEFAULT '/',
    description TEXT,
    created_by VARCHAR(255),
    ai_summary_id UUID REFERENCES processed_documents(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_folders_parent_id ON folders(parent_id);
CREATE INDEX IF NOT EXISTS ix_folders_path ON folders(path);

-- Add folder_id to the files table
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'files' AND column_name = 'folder_id'
    ) THEN
        ALTER TABLE files ADD COLUMN folder_id UUID REFERENCES folders(id) ON DELETE SET NULL;
        CREATE INDEX ix_files_folder_id ON files(folder_id);
    END IF;
END $$;

COMMIT;
