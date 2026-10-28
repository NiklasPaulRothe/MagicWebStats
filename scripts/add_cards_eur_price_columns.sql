-- =============================================================================
-- MIGRATION: add EUR (Cardmarket) price columns to cards
-- =============================================================================
-- Adds price_eur (non-foil) and price_eur_foil (foil) to the cards table.
-- These hold Scryfall's daily Cardmarket (EUR) prices for each printing, taken
-- from the card object's `prices` object (prices.eur / prices.eur_foil). Either
-- may be NULL when Scryfall has no price for that printing/finish.
--
-- Populated by the nightly card fetch (scripts/fetch_card_data.py) and used to
-- show a current price on the collection page.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database.
--
-- Safe to run multiple times: ADD COLUMN IF NOT EXISTS is idempotent.
-- =============================================================================

BEGIN;

ALTER TABLE magic_stats_owner.cards
    ADD COLUMN IF NOT EXISTS price_eur      NUMERIC(10, 2);
ALTER TABLE magic_stats_owner.cards
    ADD COLUMN IF NOT EXISTS price_eur_foil NUMERIC(10, 2);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, numeric_precision, numeric_scale
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'cards'
--     AND column_name IN ('price_eur', 'price_eur_foil')
--   ORDER BY column_name;
--
-- Expected: price_eur (numeric, 10, 2), price_eur_foil (numeric, 10, 2)
-- -----------------------------------------------------------------------------
