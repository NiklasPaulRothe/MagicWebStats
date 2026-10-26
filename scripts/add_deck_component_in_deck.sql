-- =============================================================================
-- MIGRATION: add deck_component.in_deck column
-- =============================================================================
-- Adds the boolean `in_deck` flag to magic_stats_owner.deck_component. It marks
-- whether a card counts as part of the actual deck. On import the flag is
-- derived from the card's PRIMARY category (Archidekt) or its board
-- (Moxfield); cards that are imported but excluded (Maybeboard, "Considered",
-- sideboard, etc.) are stored with in_deck = FALSE for later features.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database.
--
-- Defaulting to TRUE keeps existing rows behaving as before (counted as
-- in-deck) until decks are re-imported, at which point the flag is set
-- correctly per card.
--
-- Safe to run multiple times: ADD COLUMN IF NOT EXISTS is idempotent.
-- =============================================================================

BEGIN;

ALTER TABLE magic_stats_owner.deck_component
    ADD COLUMN IF NOT EXISTS in_deck BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, column_default, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'deck_component'
--     AND column_name  = 'in_deck';
--
-- Expected: in_deck | boolean | true | NO
-- -----------------------------------------------------------------------------
