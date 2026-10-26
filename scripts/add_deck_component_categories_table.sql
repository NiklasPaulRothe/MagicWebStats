-- =============================================================================
-- MIGRATION: add deck_component_categories table
-- =============================================================================
-- Stores the categories a deck component belongs to (Archidekt categories), in
-- a normalized child table: one row per (component, category). `position` is
-- the ordinal from the source site (0 = primary/main category). Secondary
-- categories (position >= 1) are stored now so later features can use them
-- without another migration/re-import.
--
-- Moxfield decks have no categories, so their components simply have no rows.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database. The table
-- is (re)populated by the deck import (manual or the nightly fetch).
--
-- Safe to run multiple times: CREATE TABLE/INDEX IF NOT EXISTS are idempotent.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS magic_stats_owner.deck_component_categories (
    deck_component_id INTEGER NOT NULL
        REFERENCES magic_stats_owner.deck_component(id) ON DELETE CASCADE,
    category          TEXT NOT NULL,
    position          INTEGER NOT NULL,
    PRIMARY KEY (deck_component_id, category)
);

CREATE INDEX IF NOT EXISTS idx_deck_component_categories_component
    ON magic_stats_owner.deck_component_categories (deck_component_id);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'deck_component_categories'
--   ORDER BY ordinal_position;
--
-- Expected: deck_component_id (integer, NO), category (text, NO),
--           position (integer, NO)
-- -----------------------------------------------------------------------------
