-- =============================================================================
-- MIGRATION: add deck_folders table + decks.folder_id column
-- =============================================================================
-- Adds owner-defined folders for organizing decks on the "My Decks" page.
--
--   deck_folders: one row per folder. Belongs to a player (player_id). Folders
--   nest arbitrarily via the self-referential parent_id (NULL = top-level).
--   Deleting a folder cascades to its subfolders.
--
--   decks.folder_id: the folder a deck lives in (NULL = root). ON DELETE SET
--   NULL so deleting a folder never deletes the decks inside it — they fall
--   back to the root instead.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database.
--
-- Safe to run multiple times: CREATE TABLE/INDEX IF NOT EXISTS and
-- ADD COLUMN IF NOT EXISTS are idempotent.
--
-- DATABASE SAFETY: run this ONLY against the local development database
-- (LOCAL_DATABASE_URL). Do NOT run it against the production DATABASE_URL.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS magic_stats_owner.deck_folders (
    id         SERIAL PRIMARY KEY,
    player_id  INTEGER NOT NULL
        REFERENCES magic_stats_owner.players(id) ON DELETE CASCADE,
    name       VARCHAR(255) NOT NULL,
    parent_id  INTEGER
        REFERENCES magic_stats_owner.deck_folders(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deck_folders_player_id
    ON magic_stats_owner.deck_folders (player_id);
CREATE INDEX IF NOT EXISTS idx_deck_folders_parent_id
    ON magic_stats_owner.deck_folders (parent_id);

ALTER TABLE magic_stats_owner.decks
    ADD COLUMN IF NOT EXISTS folder_id INTEGER
    REFERENCES magic_stats_owner.deck_folders(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_decks_folder_id
    ON magic_stats_owner.decks (folder_id);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'deck_folders'
--   ORDER BY ordinal_position;
--
--   SELECT column_name FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name = 'decks' AND column_name = 'folder_id';
--
-- Expected deck_folders: id (integer, NO), player_id (integer, NO),
--   name (character varying, NO), parent_id (integer, YES),
--   created_at (timestamptz, NO), updated_at (timestamptz, NO)
-- Expected decks: folder_id present.
-- -----------------------------------------------------------------------------
