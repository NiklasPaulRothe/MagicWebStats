-- =============================================================================
-- MIGRATION: add player_collection table
-- =============================================================================
-- Stores a player's owned cards, collapsed to one row per distinct physical
-- card. Two source rows collapse into one (their quantities summed) only when
-- the printing, finish, condition and language are all identical, so the dedup
-- key is (player_id, scryfall_id, finish, condition, language), enforced by the
-- unique constraint uq_player_collection_entry.
--
-- card_id links to the cards (printing) table when the printing can be resolved
-- (by Scryfall id, else by name — see resolve_card_id in deckbuilder.py), and
-- is NULL when no matching card is stored. The scryfall_id / name / set /
-- collector columns are retained from the import so the entry stays meaningful
-- even when card_id is NULL.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database. The table
-- is populated by the collection import (scripts/import_player_collection.py).
--
-- Safe to run multiple times: CREATE TABLE/INDEX IF NOT EXISTS are idempotent.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS magic_stats_owner.player_collection (
    id               SERIAL PRIMARY KEY,
    player_id        INTEGER NOT NULL
        REFERENCES magic_stats_owner.players(id) ON DELETE CASCADE,
    card_id          TEXT
        REFERENCES magic_stats_owner.cards(id) ON DELETE SET NULL,
    scryfall_id      TEXT NOT NULL,
    finish           TEXT NOT NULL,
    condition        TEXT NOT NULL,
    language         TEXT NOT NULL,
    name             TEXT NOT NULL,
    set_code         TEXT,
    set_name         TEXT,
    collector_number TEXT,
    count            INTEGER NOT NULL DEFAULT 1 CHECK (count > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_player_collection_entry
        UNIQUE (player_id, scryfall_id, finish, condition, language)
);

CREATE INDEX IF NOT EXISTS idx_player_collection_player
    ON magic_stats_owner.player_collection (player_id);

CREATE INDEX IF NOT EXISTS idx_player_collection_card
    ON magic_stats_owner.player_collection (card_id);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'player_collection'
--   ORDER BY ordinal_position;
--
-- Expected columns: id (integer, NO), player_id (integer, NO),
--   card_id (text, YES), scryfall_id (text, NO), finish (text, NO),
--   condition (text, NO), language (text, NO), name (text, NO),
--   set_code (text, YES), set_name (text, YES), collector_number (text, YES),
--   count (integer, NO), created_at (timestamp with time zone, NO),
--   updated_at (timestamp with time zone, NO)
-- -----------------------------------------------------------------------------
