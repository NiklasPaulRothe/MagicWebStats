-- =============================================================================
-- MIGRATION: add users.bio column (player-profile feature)
-- =============================================================================
-- Adds the nullable `bio` column to magic_stats_owner.users, backing the
-- editable profile bio introduced by the player-profile feature.
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and are mirrored in scripts/schema.sql (the single source of
-- truth). This script is the operational step for an already-built database.
--
-- Safe to run multiple times: ADD COLUMN IF NOT EXISTS is idempotent, so a
-- second run is a no-op and will not error or alter existing bio values.
-- =============================================================================

BEGIN;

-- Nullable VARCHAR(1000); matches User.bio (so.String(1000)) and the
-- users table definition in scripts/schema.sql.
ALTER TABLE magic_stats_owner.users
    ADD COLUMN IF NOT EXISTS bio VARCHAR(1000);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration; not part of the transaction):
--
--   SELECT column_name, data_type, character_maximum_length, is_nullable
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name   = 'users'
--     AND column_name  = 'bio';
--
-- Expected: bio | character varying | 1000 | YES
-- -----------------------------------------------------------------------------
