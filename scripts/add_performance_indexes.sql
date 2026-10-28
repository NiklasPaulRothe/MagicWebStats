-- =============================================================================
-- MIGRATION: add read-performance indexes
-- =============================================================================
-- Adds indexes for the columns most frequently filtered / joined / ordered on
-- the hot read paths (player profile aggregates, the /api stats endpoints, the
-- deck overview, the collection gallery, and the color-usage views). Each index
-- targets a specific query shape found in the app:
--
--   games.winner_id        — win counts (profile, head-to-head, deck stats)
--   games.first_player_id  — first-player counts (player stats)
--   games.date             — date range filters + chronological ordering
--                            (last-365-days activity, recent games, elo scan)
--   games (date) WHERE cedh = false
--                          — partial index matching the pervasive non-cEDH,
--                            date-ordered query shape (boolean cedh alone is too
--                            low-selectivity to index on its own)
--   decks.player_id        — owner filter on every deck listing + the views
--   decks.active           — active-deck filter on listings + the views
--   users.player_id        — User<->Player link on profile / user pages
--   card_faces.card_id     — front-face image lookups (collection + overview);
--                            card_faces grows with the large cards table
--   deck_component.deck_id — deck_overview / printing swap / card-usage filter;
--                            large per-deck table, previously unindexed
--   achievements.deck_id   — per-deck achievements on the deck show page
--   deck_version_history.deck_id — per-deck version history
--
-- Already-covered columns are intentionally NOT re-added here (participants
-- player_id/deck_id and PK game_id; cards oracle_id/name; player_collection
-- player_id/card_id; deck_tags unique(deck_id, tag); oracle_tags / card_rulings
-- oracle_id; deck_component_categories deck_component_id).
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
-- This script is the operational step for an already-built database.
--
-- Safe to run multiple times: CREATE INDEX IF NOT EXISTS is idempotent. These
-- are plain (non-CONCURRENT) index builds wrapped in a transaction, which take
-- brief write locks per table — fine for these mostly-small / nightly-rebuilt
-- tables. If you need to avoid locking a busy table, build that one index
-- separately with CREATE INDEX CONCURRENTLY (which cannot run inside a
-- transaction block).
-- =============================================================================

BEGIN;

-- games
CREATE INDEX IF NOT EXISTS idx_games_winner_id
    ON magic_stats_owner.games (winner_id);
CREATE INDEX IF NOT EXISTS idx_games_first_player_id
    ON magic_stats_owner.games (first_player_id);
CREATE INDEX IF NOT EXISTS idx_games_date
    ON magic_stats_owner.games (date);
CREATE INDEX IF NOT EXISTS idx_games_noncedh_date
    ON magic_stats_owner.games (date) WHERE cedh = false;

-- decks
CREATE INDEX IF NOT EXISTS idx_decks_player_id
    ON magic_stats_owner.decks (player_id);
CREATE INDEX IF NOT EXISTS idx_decks_active
    ON magic_stats_owner.decks (active);

-- users
CREATE INDEX IF NOT EXISTS idx_users_player_id
    ON magic_stats_owner.users (player_id);

-- card_faces
CREATE INDEX IF NOT EXISTS idx_card_faces_card_id
    ON magic_stats_owner.card_faces (card_id);

-- deck_component
CREATE INDEX IF NOT EXISTS idx_deck_component_deck_id
    ON magic_stats_owner.deck_component (deck_id);

-- achievements
CREATE INDEX IF NOT EXISTS idx_achievements_deck_id
    ON magic_stats_owner.achievements (deck_id);

-- deck_version_history
CREATE INDEX IF NOT EXISTS idx_deck_version_history_deck_id
    ON magic_stats_owner.deck_version_history (deck_id);

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT indexname, tablename
--   FROM pg_indexes
--   WHERE schemaname = 'magic_stats_owner'
--     AND indexname IN (
--       'idx_games_winner_id', 'idx_games_first_player_id', 'idx_games_date',
--       'idx_games_noncedh_date', 'idx_decks_player_id', 'idx_decks_active',
--       'idx_users_player_id', 'idx_card_faces_card_id',
--       'idx_deck_component_deck_id', 'idx_achievements_deck_id',
--       'idx_deck_version_history_deck_id'
--     )
--   ORDER BY tablename, indexname;
--
-- Expected: 11 rows (one per index above).
--
-- Optionally ANALYZE the affected tables so the planner has fresh stats:
--   ANALYZE magic_stats_owner.games, magic_stats_owner.decks,
--           magic_stats_owner.users, magic_stats_owner.card_faces,
--           magic_stats_owner.deck_component, magic_stats_owner.achievements,
--           magic_stats_owner.deck_version_history;
-- -----------------------------------------------------------------------------
