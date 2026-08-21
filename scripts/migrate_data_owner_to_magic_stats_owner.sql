-- =============================================================================
-- ONE-OFF DATA MIGRATION: data_owner → magic_stats_owner
-- =============================================================================
-- This script copies all data from the legacy data_owner schema into the new
-- magic_stats_owner schema. It should be run ONCE during the cutover window
-- after schema.sql has been executed to create the target tables.
--
-- The entire migration is wrapped in a single transaction (BEGIN/COMMIT) for
-- atomicity — if any INSERT fails, all changes roll back and data_owner
-- remains the authoritative source.
--
-- Key transformations:
--   • PascalCase/quoted column names → snake_case
--   • German column names in achievements: titel→title, beschreibung→description,
--     anzahl→amount, deck→deck_id
--   • Games.added_by → games.added_by_user_id
--   • First_Player → seat=1 for matching participant; NULL for all others
--   • Card-related tables are straight copies (already snake_case)
--   • SERIAL sequences are reset after data load
--
-- DO NOT run this script more than once without first truncating target tables.
-- =============================================================================

BEGIN;

-- 1. Core reference tables (no FK dependencies)
INSERT INTO magic_stats_owner.players (id, name, created_at, updated_at)
SELECT id, "Name", now(), now()
FROM data_owner."Player";

INSERT INTO magic_stats_owner.users (id, username, email, password_hash, player_id, active, role, created_at, updated_at)
SELECT id, username, email, password_hash, spieler, active, COALESCE(role, 'user'), now(), now()
FROM data_owner."user";

INSERT INTO magic_stats_owner.colors (name, abbreviation, img)
SELECT "Name", abbreviation, img
FROM data_owner."Colors";

INSERT INTO magic_stats_owner.color_identities (name, amount)
SELECT "Name", amount
FROM data_owner."Color_Identities";

INSERT INTO magic_stats_owner.color_components (color_identity, color)
SELECT color_identity, color
FROM data_owner.color_components;

-- 2. Decks (depends on players, color_identities)
INSERT INTO magic_stats_owner.decks (
    id, name, active, commander, partner, player_id, color_identity,
    elo_rating, decklist, decksite, archidekt_id, image_uri,
    last_rework, last_change, last_patch, cedh,
    version, patch, change, created_at, updated_at
)
SELECT
    id, "Name", "Active", "Commander", "Partner", "Player", "Color_Identity",
    elo_rating, decklist, decksite, archidekt_id, image_uri,
    "Last_Rework", "Last_Change", last_patch, cedh,
    "Version", patch, "change", now(), now()
FROM data_owner."Decks";

-- 3. Games (depends on players, users)
INSERT INTO magic_stats_owner.games (
    id, date, first_player_id, winner_id, planechase, turns,
    final_blow, first_ko_turn, first_ko_by, cedh, added_by_user_id,
    created_at, updated_at
)
SELECT
    id, "Date", "First_Player", "Winner", "Planechase", turns,
    final_blow, first_ko_turn, first_ko_by, cedh, added_by,
    now(), now()
FROM data_owner."Games";

-- 4. Participants (depends on games, players, decks)
-- Set seat=1 for the first player (known from games.First_Player), NULL for others.
-- If a game's First_Player is NULL, all participants in that game get seat=NULL.
INSERT INTO magic_stats_owner.participants (
    game_id, player_id, deck_id, seat, early_sol_ring, mulligans,
    comments, landdrops, lands, enough_mana, enough_gas, deckplan,
    unanswered_threats, loss_without_answer, selfmade_win, fun_moments,
    removal_played, targeted_by_removal, protection_played,
    created_at, updated_at
)
SELECT
    p.game_id, p.player_id, p.deck_id,
    CASE WHEN g."First_Player" IS NOT NULL AND p.player_id = g."First_Player" THEN 1 ELSE NULL END,
    COALESCE(p.early_sol_ring, false), p.mulligans,
    p.comments, p.landdrops, p.lands, p.enough_mana, p.enough_gas, p.deckplan,
    p.unanswered_threats, p.loss_without_answer, p.selfmade_win, p.fun_moments,
    p.removal_played, p.targeted_by_removal, p.protection_played,
    now(), now()
FROM data_owner."Participants" p
JOIN data_owner."Games" g ON g.id = p.game_id;

-- 5. Cards and related tables (already snake_case in data_owner)
INSERT INTO magic_stats_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at)
SELECT id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at
FROM data_owner.cards;

INSERT INTO magic_stats_owner.card_faces (id, card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri)
SELECT id, card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri
FROM data_owner.card_faces;

INSERT INTO magic_stats_owner.card_colors (card_id, color)
SELECT card_id, color FROM data_owner.card_colors;

INSERT INTO magic_stats_owner.card_color_identity (card_id, color)
SELECT card_id, color FROM data_owner.card_color_identity;

INSERT INTO magic_stats_owner.card_keywords (card_id, keyword)
SELECT card_id, keyword FROM data_owner.card_keywords;

INSERT INTO magic_stats_owner.card_legalities (card_id, format, status)
SELECT card_id, format, status FROM data_owner.card_legalities;

INSERT INTO magic_stats_owner.oracle_tags (id, oracle_id, tag)
SELECT id, oracle_id, tag FROM data_owner.oracle_tags;

-- 6. Deck-related tables
INSERT INTO magic_stats_owner.deck_component (id, deck_id, card_id, count, name)
SELECT id, deck_id, card_id, count, name
FROM data_owner.deck_component;

INSERT INTO magic_stats_owner.achievements (id, title, description, amount, deck_id, achieved)
SELECT id, titel, beschreibung, anzahl, deck, achieved
FROM data_owner.achievements;

INSERT INTO magic_stats_owner.deck_version_history (id, deck_id, change_type, previous_version, previous_patch, previous_change, new_version, new_patch, new_change, comment, timestamp)
SELECT id, deck_id, change_type, previous_version, previous_patch, previous_change, new_version, new_patch, new_change, comment, timestamp
FROM data_owner.deck_version_history;

INSERT INTO magic_stats_owner.deck_tags (id, deck_id, tag, created_at)
SELECT id, deck_id, tag, created_at
FROM data_owner.deck_tags;

-- 7. Audit log
INSERT INTO magic_stats_owner.audit_log (id, timestamp, user_id, username, action, entity_type, entity_id, details)
SELECT id, timestamp, user_id, username, action, entity_type, entity_id, details
FROM data_owner.audit_log;

-- 8. Reset all SERIAL sequences
SELECT setval('magic_stats_owner.players_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.players), 1));
SELECT setval('magic_stats_owner.users_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.users), 1));
SELECT setval('magic_stats_owner.decks_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.decks), 1));
SELECT setval('magic_stats_owner.games_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.games), 1));
SELECT setval('magic_stats_owner.card_faces_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.card_faces), 1));
SELECT setval('magic_stats_owner.deck_component_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.deck_component), 1));
SELECT setval('magic_stats_owner.achievements_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.achievements), 1));
SELECT setval('magic_stats_owner.deck_version_history_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.deck_version_history), 1));
SELECT setval('magic_stats_owner.deck_tags_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.deck_tags), 1));
SELECT setval('magic_stats_owner.audit_log_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.audit_log), 1));
SELECT setval('magic_stats_owner.oracle_tags_id_seq', COALESCE((SELECT MAX(id) FROM magic_stats_owner.oracle_tags), 1));

COMMIT;
