-- =============================================================================
-- MIGRATION: deck_component collection-tracking columns + availability views
-- =============================================================================
-- Adds per-deck-card collection tracking so the owner can mark whether a card
-- in a deck is a physical copy they own, a proxy, or unmarked, and so the app
-- can show which owned cards are free vs. consumed by decks.
--
--   deck_component.physical_status   TEXT 'unset' | 'in_deck' | 'proxy'
--                                    (default 'unset'). 'in_deck' claims one
--                                    collection copy matching this card's
--                                    printing (card_id) + physical_finish +
--                                    physical_language.
--   deck_component.physical_finish   TEXT, nullable. Finish the claim matches.
--   deck_component.physical_language TEXT, nullable. Language the claim matches.
--
-- Views (see section 14 of schema.sql for the mirrored copies):
--   v_player_printing_availability — per (player_id, scryfall_id, finish,
--       language): owned copies vs. copies claimed 'in_deck', and an
--       over_claimed flag (claimed > owned, including owned = 0).
--   v_deck_card_collection_status — per deck_component: the resolved status
--       used by the deck overview and collection pages.
--
-- Matching is EXACT: printing (card_id / scryfall_id) + finish + language.
-- Condition is ignored (it doesn't change which card it is).
--
-- No Alembic is used in this project (ADR-001); schema changes are applied via
-- hand-run SQL and mirrored in scripts/schema.sql (the single source of truth).
--
-- Safe to run multiple times: ADD COLUMN IF NOT EXISTS and CREATE OR REPLACE
-- VIEW are idempotent.
--
-- DATABASE SAFETY: run this ONLY against the local development database
-- (LOCAL_DATABASE_URL). Do NOT run it against the production DATABASE_URL.
-- =============================================================================

BEGIN;

ALTER TABLE magic_stats_owner.deck_component
    ADD COLUMN IF NOT EXISTS physical_status TEXT NOT NULL DEFAULT 'unset';
-- physical_finish / physical_language default to the most common printing
-- identity ('Normal' / 'EN', matching the collection's finish/language tokens)
-- so every card has a concrete identity to match on. Added nullable first,
-- backfilled, then set NOT NULL + default so a re-run on an older install with
-- NULLs is corrected.
ALTER TABLE magic_stats_owner.deck_component
    ADD COLUMN IF NOT EXISTS physical_finish TEXT;
ALTER TABLE magic_stats_owner.deck_component
    ADD COLUMN IF NOT EXISTS physical_language TEXT;

UPDATE magic_stats_owner.deck_component SET physical_finish = 'Normal' WHERE physical_finish IS NULL;
UPDATE magic_stats_owner.deck_component SET physical_language = 'EN' WHERE physical_language IS NULL;

ALTER TABLE magic_stats_owner.deck_component ALTER COLUMN physical_finish SET DEFAULT 'Normal';
ALTER TABLE magic_stats_owner.deck_component ALTER COLUMN physical_finish SET NOT NULL;
ALTER TABLE magic_stats_owner.deck_component ALTER COLUMN physical_language SET DEFAULT 'EN';
ALTER TABLE magic_stats_owner.deck_component ALTER COLUMN physical_language SET NOT NULL;

-- Guard the allowed values without failing a re-run.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.constraint_column_usage
        WHERE table_schema = 'magic_stats_owner'
          AND table_name = 'deck_component'
          AND constraint_name = 'ck_deck_component_physical_status'
    ) THEN
        ALTER TABLE magic_stats_owner.deck_component
            ADD CONSTRAINT ck_deck_component_physical_status
            CHECK (physical_status IN ('unset', 'in_deck', 'proxy'));
    END IF;
END $$;

-- -----------------------------------------------------------------------------
-- View: per-printing availability for a player.
-- owned_count  = summed collection copies of the exact printing+finish+language
--                (condition ignored).
-- claimed_count= number of deck cards the player has marked 'in_deck' whose
--                current printing+finish+language match that pool (across all
--                their decks).
-- over_claimed = claimed_count > owned_count (not enough matching copies).
-- The pool key is (player_id, card_id, finish, language); finish/language are
-- normalized to lower-case so 'Foil' and 'foil' collapse together.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW magic_stats_owner.v_player_printing_availability AS
WITH owned AS (
    SELECT
        pc.player_id,
        pc.card_id,
        LOWER(COALESCE(pc.finish, ''))   AS finish_key,
        LOWER(COALESCE(pc.language, '')) AS language_key,
        SUM(pc.count)                    AS owned_count
    FROM magic_stats_owner.player_collection pc
    WHERE pc.card_id IS NOT NULL
    GROUP BY pc.player_id, pc.card_id,
             LOWER(COALESCE(pc.finish, '')), LOWER(COALESCE(pc.language, ''))
),
claimed AS (
    SELECT
        d.player_id,
        dc.card_id,
        LOWER(COALESCE(dc.physical_finish, ''))   AS finish_key,
        LOWER(COALESCE(dc.physical_language, '')) AS language_key,
        SUM(COALESCE(dc.count, 1))                AS claimed_count
    FROM magic_stats_owner.deck_component dc
    JOIN magic_stats_owner.decks d ON d.id = dc.deck_id
    WHERE dc.physical_status = 'in_deck'
      AND dc.card_id IS NOT NULL
    GROUP BY d.player_id, dc.card_id,
             LOWER(COALESCE(dc.physical_finish, '')), LOWER(COALESCE(dc.physical_language, ''))
)
SELECT
    COALESCE(o.player_id, c.player_id)     AS player_id,
    COALESCE(o.card_id, c.card_id)         AS card_id,
    COALESCE(o.finish_key, c.finish_key)   AS finish_key,
    COALESCE(o.language_key, c.language_key) AS language_key,
    COALESCE(o.owned_count, 0)             AS owned_count,
    COALESCE(c.claimed_count, 0)           AS claimed_count,
    (COALESCE(c.claimed_count, 0) > COALESCE(o.owned_count, 0)) AS over_claimed
FROM owned o
FULL OUTER JOIN claimed c
    ON o.player_id = c.player_id
   AND o.card_id = c.card_id
   AND o.finish_key = c.finish_key
   AND o.language_key = c.language_key;

-- -----------------------------------------------------------------------------
-- View: resolved collection status per deck_component.
-- status is one of:
--   'in_deck_ok'        marked in_deck and the matching pool is not over-claimed
--   'in_deck_faulty'    marked in_deck but not enough matching copies owned
--   'proxy'             marked proxy
--   'available'         unset, and an owned copy of this exact printing+finish+
--                       language is free (owned > copies otherwise claimed)
--   'owned_no_copy'     unset, owns this exact printing+finish+language but all
--                       copies are claimed by in_deck cards
--   'owned_other'       unset, owns a different printing of the same card
--   'not_owned'         unset, owns no printing of this card
-- Only deck cards that are part of the deck (in_deck flag TRUE) are classified;
-- excluded (maybeboard/sideboard) components resolve to 'not_owned' context but
-- the deck overview only renders in-deck cards anyway.
-- -----------------------------------------------------------------------------
--
-- 'available' / 'owned_no_copy' (own this exact printing) resolve against the
-- EXACT pool (printing + finish + language). The fallbacks when the exact
-- printing isn't owned resolve at the ORACLE level (summed across every
-- printing/finish/language of the card), because for "is a free physical copy
-- available at all?" the printing doesn't matter:
--   * 'owned_other'   — don't own this exact printing, but own the card in
--                       another printing WITH a free copy.
--   * 'owned_no_copy' — own the card somewhere, but every copy across all
--                       printings is already allocated to a deck.
-- DROP first so re-running after an earlier (different-typed) definition always
-- lands the current shape.
DROP VIEW IF EXISTS magic_stats_owner.v_deck_card_collection_status;
CREATE VIEW magic_stats_owner.v_deck_card_collection_status AS
WITH oracle_availability AS (
    -- Owned vs claimed per (player, oracle_id), summed across all printings.
    SELECT
        av.player_id,
        c.oracle_id,
        SUM(av.owned_count)   AS owned_count,
        SUM(av.claimed_count) AS claimed_count
    FROM magic_stats_owner.v_player_printing_availability av
    JOIN magic_stats_owner.cards c ON c.id = av.card_id
    GROUP BY av.player_id, c.oracle_id
)
SELECT
    dc.id            AS deck_component_id,
    dc.deck_id       AS deck_id,
    d.player_id      AS player_id,
    dc.card_id       AS card_id,
    dc.physical_status,
    dc.physical_finish,
    dc.physical_language,
    COALESCE(av.owned_count, 0)   AS owned_count,
    COALESCE(av.claimed_count, 0) AS claimed_count,
    CASE
        WHEN dc.physical_status = 'in_deck' AND COALESCE(av.over_claimed, TRUE) THEN 'in_deck_faulty'
        WHEN dc.physical_status = 'in_deck' THEN 'in_deck_ok'
        WHEN dc.physical_status = 'proxy' THEN 'proxy'
        -- unset, exact printing owned:
        WHEN COALESCE(av.owned_count, 0) > COALESCE(av.claimed_count, 0) THEN 'available'
        WHEN COALESCE(av.owned_count, 0) > 0 THEN 'owned_no_copy'
        -- unset, exact printing NOT owned -> fall back to oracle level:
        WHEN COALESCE(oa.owned_count, 0) > COALESCE(oa.claimed_count, 0) THEN 'owned_other'
        WHEN COALESCE(oa.owned_count, 0) > 0 THEN 'owned_no_copy'
        ELSE 'not_owned'
    END AS status
FROM magic_stats_owner.deck_component dc
JOIN magic_stats_owner.decks d ON d.id = dc.deck_id
LEFT JOIN magic_stats_owner.cards dcard ON dcard.id = dc.card_id
LEFT JOIN magic_stats_owner.v_player_printing_availability av
       ON av.player_id = d.player_id
      AND av.card_id = dc.card_id
      AND av.finish_key = LOWER(dc.physical_finish)
      AND av.language_key = LOWER(dc.physical_language)
LEFT JOIN oracle_availability oa
       ON oa.player_id = d.player_id
      AND oa.oracle_id = dcard.oracle_id;

COMMIT;

-- -----------------------------------------------------------------------------
-- Verification (run manually after the migration):
--
--   SELECT column_name, data_type, is_nullable, column_default
--   FROM information_schema.columns
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name = 'deck_component'
--     AND column_name IN ('physical_status','physical_finish','physical_language')
--   ORDER BY column_name;
--
--   SELECT table_name FROM information_schema.views
--   WHERE table_schema = 'magic_stats_owner'
--     AND table_name IN ('v_player_printing_availability',
--                        'v_deck_card_collection_status');
-- -----------------------------------------------------------------------------
