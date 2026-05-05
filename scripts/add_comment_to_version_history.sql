-- Add comment column to existing deck_version_history table
-- Run this if you already created the table without the comment column

ALTER TABLE data_owner.deck_version_history 
ADD COLUMN IF NOT EXISTS comment TEXT;
