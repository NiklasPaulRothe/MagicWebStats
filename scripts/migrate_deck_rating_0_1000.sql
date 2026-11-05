-- =============================================================================
-- MIGRATION: switch deck Elo to the capped 0-1000 strength rating
-- =============================================================================
-- Replaces the old additive, unbounded chess-style Elo (seed 1500, no cap) with
-- a bounded confidence-weighted strength rating computed by
-- app/services/elo_service.py (and the nightly scripts/fetch_card_data.py):
--
--   decks.elo_rating : mean strength estimate on a fixed 0-1000 scale (centre
--                      500). NULL = unrated (fewer than 5 counted games). On
--                      this scale 0 is a LEGAL rating, so NULL — not 0 — is the
--                      unrated sentinel.
--   decks.elo_rd     : rating deviation (confidence / internal range). Wide for
--                      a new deck, narrows as it plays. NULL when unrated.
--   decks.elo_games  : number of valid games counted toward the rating. Drives
--                      the leaderboard gate (>= 5) and replaces the old
--                      `elo_rating = 0` sentinel.
--
-- This migration only changes the SCHEMA (adds columns, swaps the CHECK/default,
-- drops NOT NULL and clears stale 1500-scale values). It does NOT compute new
-- ratings. After running it, trigger a full recalculation so the new columns
-- are populated:
--   * web app (admin):  visit  GET /decks/elo
--   * or run the nightly job:  python scripts/fetch_card_data.py
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
--
-- Safe to run multiple times: ADD COLUMN IF NOT EXISTS and the guarded
-- constraint swap are idempotent.
--
-- DATABASE SAFETY: run this ONLY against the local development database
-- (LOCAL_DATABASE_URL). Do NOT run it against the production DATABASE_URL —
-- hand the production command to the owner to run.
-- =============================================================================

BEGIN;

-- 1. New columns (nullable rating + rd; games defaults to 0).
ALTER TABLE magic_stats_owner.decks
    ADD COLUMN IF NOT EXISTS elo_rd FLOAT;
ALTER TABLE magic_stats_owner.decks
    ADD COLUMN IF NOT EXISTS elo_games INTEGER NOT NULL DEFAULT 0;

-- 2. elo_rating becomes nullable (NULL is the new unrated sentinel) and loses
--    its old 1500 default (new decks now seed at the centre inside the rating
--    engine, not via a column default).
ALTER TABLE magic_stats_owner.decks
    ALTER COLUMN elo_rating DROP NOT NULL;
ALTER TABLE magic_stats_owner.decks
    ALTER COLUMN elo_rating DROP DEFAULT;

-- 3. Clear every existing rating. Old values live on the 0..~2000+ Elo scale
--    and are meaningless on the new 0-1000 scale; a fresh recompute will
--    repopulate them. (Also clears the old `0` = unrated sentinel.)
UPDATE magic_stats_owner.decks
    SET elo_rating = NULL,
        elo_rd     = NULL,
        elo_games  = 0;

-- 4. Swap the CHECK constraint from `elo_rating >= 0` to the bounded 0-1000
--    range, and add bounds for the new columns. Guarded so a re-run is safe.
ALTER TABLE magic_stats_owner.decks
    DROP CONSTRAINT IF EXISTS ck_deck_elo_rating;
ALTER TABLE magic_stats_owner.decks
    ADD CONSTRAINT ck_deck_elo_rating
    CHECK (elo_rating >= 0 AND elo_rating <= 1000);

ALTER TABLE magic_stats_owner.decks
    DROP CONSTRAINT IF EXISTS ck_deck_elo_rd;
ALTER TABLE magic_stats_owner.decks
    ADD CONSTRAINT ck_deck_elo_rd
    CHECK (elo_rd >= 0);

ALTER TABLE magic_stats_owner.decks
    DROP CONSTRAINT IF EXISTS ck_deck_elo_games;
ALTER TABLE magic_stats_owner.decks
    ADD CONSTRAINT ck_deck_elo_games
    CHECK (elo_games >= 0);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name = 'decks'
--     AND column_name IN ('elo_rating','elo_rd','elo_games')
--   ORDER BY column_name;
--   -- expect: elo_rating nullable, no default; elo_rd nullable; elo_games
--   --         NOT NULL default 0.
--
--   SELECT conname FROM pg_constraint
--   WHERE conrelid = 'magic_stats_owner.decks'::regclass
--     AND conname IN ('ck_deck_elo_rating','ck_deck_elo_rd','ck_deck_elo_games');
--
-- Then recompute ratings (see header) and sanity-check the spread:
--   SELECT min(elo_rating), max(elo_rating), count(*) FILTER (WHERE elo_rating IS NOT NULL)
--   FROM magic_stats_owner.decks;
-- -----------------------------------------------------------------------------
