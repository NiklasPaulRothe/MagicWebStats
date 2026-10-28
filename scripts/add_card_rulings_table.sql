-- =============================================================================
-- MIGRATION: add card_rulings table (card popup rulings feature)
-- =============================================================================
-- Adds magic_stats_owner.card_rulings, which stores Gatherer/Scryfall rulings
-- for cards. Rulings are shared across all printings of a card, so they key on
-- oracle_id (like oracle_tags) rather than a per-printing card id.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and are mirrored in scripts/schema.sql (the single source of
-- truth). This script is the operational step for an already-built database.
--
-- The table is populated by scripts/fetch_card_data.py (the nightly fetch),
-- which streams Scryfall's separate "rulings" bulk file. Running the fetch
-- after this migration will fill the table.
--
-- Safe to run multiple times: CREATE TABLE/INDEX IF NOT EXISTS are idempotent,
-- so a second run is a no-op and will not error or drop existing rows.
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_rulings (
    id           SERIAL PRIMARY KEY,
    oracle_id    TEXT NOT NULL,
    source       TEXT,
    published_at DATE,
    comment      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_card_rulings_oracle_id
    ON magic_stats_owner.card_rulings (oracle_id);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration; not part of the transaction):
--
--   SELECT column_name, data_type, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'card_rulings'
--   ORDER BY ordinal_position;
--
-- Expected rows: id (integer, NO), oracle_id (text, NO), source (text, YES),
--                published_at (date, YES), comment (text, NO)
-- -----------------------------------------------------------------------------
