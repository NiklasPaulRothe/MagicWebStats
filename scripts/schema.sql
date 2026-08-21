-- =============================================================================
-- MagicWebStats — Full Database Build Script
-- =============================================================================
-- Target schema/role: magic_stats_owner
--
-- THIS IS THE SINGLE SOURCE OF TRUTH FOR THE DATABASE SCHEMA.
--
-- Rules for maintaining this file:
--   1. This script always represents a COMPLETE, FRESH build of the database.
--      Running it against an empty Postgres instance creates every role,
--      schema, table, constraint, index, and trigger the application needs.
--   2. There are no incremental ALTER-based migration files. When the schema
--      changes, this file is edited in place so it keeps describing the
--      current desired end state — not the history of how it got there.
--   3. This script must remain idempotent (IF NOT EXISTS / OR REPLACE guards)
--      so re-running it against an already-built database is always safe.
--   4. One-time, non-repeatable operations (copying data from the legacy
--      `data_owner` schema, dropping `data_owner` once verified) are NOT part
--      of this file — those are one-off operational scripts run by hand
--      during the cutover, since they are not "build from scratch" steps.
--      See scripts/migrate_data_owner_to_magic_stats_owner.sql.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 0. Role and schema
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    -- Schema only — no separate role needed.
    -- The schema is owned by the current database user.
    NULL;
END
$$;

CREATE SCHEMA IF NOT EXISTS magic_stats_owner;

SET search_path TO magic_stats_owner;

-- ---------------------------------------------------------------------------
-- 1. players (in-game participants — distinct from `users`)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.players (
    id         SERIAL PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 2. users (application login accounts — distinct from `players`)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(256),
    player_id     INTEGER REFERENCES magic_stats_owner.players(id) ON DELETE SET NULL,
    active        BOOLEAN NOT NULL DEFAULT true,
    role          VARCHAR(64) NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 3. colors / color identities (WUBRG reference data)
-- ---------------------------------------------------------------------------
-- (numbering below is sequential and does not correspond to FK dependency
-- order beyond what's already satisfied by table creation order above)
CREATE TABLE IF NOT EXISTS magic_stats_owner.colors (
    name         TEXT PRIMARY KEY,
    abbreviation TEXT NOT NULL,
    img          TEXT
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.color_identities (
    name   TEXT PRIMARY KEY,
    amount INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.color_components (
    color_identity TEXT NOT NULL REFERENCES magic_stats_owner.color_identities(name) ON DELETE CASCADE,
    color          TEXT NOT NULL REFERENCES magic_stats_owner.colors(name) ON DELETE CASCADE,
    PRIMARY KEY (color_identity, color)
);

-- ---------------------------------------------------------------------------
-- 4. decks
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.decks (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL UNIQUE,
    active         BOOLEAN NOT NULL DEFAULT true,
    commander      TEXT NOT NULL,
    partner        TEXT,
    player_id      INTEGER NOT NULL REFERENCES magic_stats_owner.players(id) ON DELETE RESTRICT,
    color_identity TEXT NOT NULL REFERENCES magic_stats_owner.color_identities(name) ON DELETE RESTRICT,
    elo_rating     FLOAT NOT NULL DEFAULT 1500 CHECK (elo_rating >= 0),
    decklist       TEXT,
    decksite       TEXT,
    archidekt_id   TEXT,
    image_uri      TEXT,
    last_rework    DATE NOT NULL DEFAULT current_date,
    last_change    DATE NOT NULL DEFAULT current_date,
    last_patch     DATE NOT NULL DEFAULT current_date,
    cedh           BOOLEAN NOT NULL DEFAULT false,
    version        INTEGER NOT NULL DEFAULT 0 CHECK (version >= 0),
    patch          INTEGER NOT NULL DEFAULT 0 CHECK (patch >= 0),
    change         INTEGER NOT NULL DEFAULT 0 CHECK (change >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 5. games
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.games (
    id              SERIAL PRIMARY KEY,
    date            DATE NOT NULL,
    first_player_id INTEGER REFERENCES magic_stats_owner.players(id) ON DELETE RESTRICT,
    winner_id       INTEGER REFERENCES magic_stats_owner.players(id) ON DELETE RESTRICT,
    planechase      BOOLEAN NOT NULL DEFAULT false,
    turns           INTEGER CHECK (turns >= 0),
    final_blow      TEXT,
    first_ko_turn   INTEGER,
    first_ko_by     TEXT,
    cedh            BOOLEAN NOT NULL DEFAULT false,
    added_by_user_id INTEGER REFERENCES magic_stats_owner.users(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 6. participants
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.participants (
    game_id             INTEGER NOT NULL REFERENCES magic_stats_owner.games(id) ON DELETE RESTRICT,
    player_id           INTEGER NOT NULL REFERENCES magic_stats_owner.players(id) ON DELETE RESTRICT,
    deck_id             INTEGER NOT NULL REFERENCES magic_stats_owner.decks(id) ON DELETE RESTRICT,
    seat                INTEGER,
    early_sol_ring      BOOLEAN NOT NULL DEFAULT false,
    mulligans           INTEGER CHECK (mulligans >= 0),
    comments            TEXT,
    landdrops           INTEGER,
    lands               INTEGER,
    enough_mana         BOOLEAN,
    enough_gas          BOOLEAN,
    deckplan            BOOLEAN,
    unanswered_threats  BOOLEAN,
    loss_without_answer BOOLEAN,
    selfmade_win        BOOLEAN,
    fun_moments         BOOLEAN,
    removal_played      INTEGER,
    targeted_by_removal INTEGER,
    protection_played   INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (game_id, player_id),
    CONSTRAINT chk_participant_seat_min CHECK (seat IS NULL OR seat >= 1)
);

CREATE INDEX IF NOT EXISTS idx_participants_player_id ON magic_stats_owner.participants (player_id);
CREATE INDEX IF NOT EXISTS idx_participants_deck_id ON magic_stats_owner.participants (deck_id);

-- Deferred constraint trigger: a participant's seat can never exceed the
-- number of players already recorded for that game. Must be deferred to
-- COMMIT because game_add inserts participants one row at a time within a
-- single transaction — checking immediately after the first row would
-- reject even a valid 4-player game.
CREATE OR REPLACE FUNCTION magic_stats_owner.check_participant_seat()
RETURNS TRIGGER AS $$
DECLARE
    player_count INTEGER;
BEGIN
    IF NEW.seat IS NOT NULL THEN
        SELECT count(*) INTO player_count
        FROM magic_stats_owner.participants
        WHERE game_id = NEW.game_id;

        IF NEW.seat > player_count THEN
            RAISE EXCEPTION 'seat % exceeds number of players (%) in game %',
                NEW.seat, player_count, NEW.game_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_check_participant_seat ON magic_stats_owner.participants;
CREATE CONSTRAINT TRIGGER trg_check_participant_seat
    AFTER INSERT OR UPDATE ON magic_stats_owner.participants
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION magic_stats_owner.check_participant_seat();

-- ---------------------------------------------------------------------------
-- 7. cards and normalized card metadata (Scryfall-sourced)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.cards (
    id           TEXT PRIMARY KEY,
    oracle_id    TEXT NOT NULL,
    name         TEXT NOT NULL,
    mana_cost    TEXT,
    cmc          FLOAT NOT NULL DEFAULT 0,
    type_line    TEXT NOT NULL,
    oracle_text  TEXT,
    layout       TEXT NOT NULL,
    set_code     TEXT NOT NULL,
    set_name     TEXT NOT NULL,
    rarity       TEXT NOT NULL,
    released_at  DATE
);

CREATE INDEX IF NOT EXISTS idx_cards_oracle_id ON magic_stats_owner.cards (oracle_id);
CREATE INDEX IF NOT EXISTS idx_cards_name ON magic_stats_owner.cards (name);

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_faces (
    id          SERIAL PRIMARY KEY,
    card_id     TEXT NOT NULL REFERENCES magic_stats_owner.cards(id) ON DELETE CASCADE,
    face_index  INTEGER NOT NULL,
    name        TEXT NOT NULL,
    mana_cost   TEXT,
    type_line   TEXT,
    oracle_text TEXT,
    image_uri   TEXT,
    UNIQUE (card_id, face_index)
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_colors (
    card_id TEXT NOT NULL REFERENCES magic_stats_owner.cards(id) ON DELETE CASCADE,
    color   VARCHAR(1) NOT NULL CHECK (color IN ('W', 'U', 'B', 'R', 'G')),
    PRIMARY KEY (card_id, color)
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_color_identity (
    card_id TEXT NOT NULL REFERENCES magic_stats_owner.cards(id) ON DELETE CASCADE,
    color   VARCHAR(1) NOT NULL CHECK (color IN ('W', 'U', 'B', 'R', 'G')),
    PRIMARY KEY (card_id, color)
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_keywords (
    card_id TEXT NOT NULL REFERENCES magic_stats_owner.cards(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    PRIMARY KEY (card_id, keyword)
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.card_legalities (
    card_id TEXT NOT NULL REFERENCES magic_stats_owner.cards(id) ON DELETE CASCADE,
    format  TEXT NOT NULL,
    status  TEXT NOT NULL CHECK (status IN ('legal', 'not_legal', 'banned', 'restricted')),
    PRIMARY KEY (card_id, format)
);

CREATE TABLE IF NOT EXISTS magic_stats_owner.oracle_tags (
    id        SERIAL PRIMARY KEY,
    oracle_id TEXT NOT NULL,
    tag       TEXT NOT NULL,
    UNIQUE (oracle_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_oracle_tags_oracle_id ON magic_stats_owner.oracle_tags (oracle_id);

-- ---------------------------------------------------------------------------
-- 8. deck_component (cards belonging to a deck's decklist)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.deck_component (
    id      SERIAL PRIMARY KEY,
    deck_id INTEGER REFERENCES magic_stats_owner.decks(id) ON DELETE CASCADE,
    card_id TEXT REFERENCES magic_stats_owner.cards(id) ON DELETE SET NULL,
    count   INTEGER,
    name    TEXT
);

-- ---------------------------------------------------------------------------
-- 9. achievements
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.achievements (
    id          SERIAL PRIMARY KEY,
    title       TEXT,
    description TEXT,
    amount      INTEGER,
    deck_id     INTEGER REFERENCES magic_stats_owner.decks(id) ON DELETE CASCADE,
    achieved    INTEGER
);

-- ---------------------------------------------------------------------------
-- 10. deck_version_history
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.deck_version_history (
    id               SERIAL PRIMARY KEY,
    deck_id          INTEGER NOT NULL REFERENCES magic_stats_owner.decks(id) ON DELETE CASCADE,
    change_type      VARCHAR(20) NOT NULL CHECK (change_type IN ('change', 'patch', 'rework')),
    previous_version INTEGER NOT NULL,
    previous_patch   INTEGER NOT NULL,
    previous_change  INTEGER NOT NULL,
    new_version      INTEGER NOT NULL,
    new_patch        INTEGER NOT NULL,
    new_change       INTEGER NOT NULL,
    comment          TEXT,
    timestamp        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- 11. deck_tags
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.deck_tags (
    id         SERIAL PRIMARY KEY,
    deck_id    INTEGER NOT NULL REFERENCES magic_stats_owner.decks(id) ON DELETE CASCADE,
    tag        VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (deck_id, tag)
);

-- ---------------------------------------------------------------------------
-- 12. audit_log
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS magic_stats_owner.audit_log (
    id          SERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id     INTEGER NOT NULL REFERENCES magic_stats_owner.users(id) ON DELETE RESTRICT,
    username    TEXT NOT NULL,
    action      TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id   TEXT,
    details     TEXT
);

-- ---------------------------------------------------------------------------
-- 13. Views
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW magic_stats_owner.v_color_usage AS
SELECT
    c.name AS color,
    ROUND(
        COUNT(DISTINCT g.id)::numeric * 100.0
        / NULLIF((SELECT COUNT(*) FROM magic_stats_owner.games), 0)::numeric,
        2
    ) AS likelihood,
    ROUND((
        SELECT AVG(temp.color_count)
        FROM (
            SELECT g_1.id AS game_id,
                   c_1.name AS color_name,
                   COUNT(c_1.name) AS color_count
            FROM magic_stats_owner.games g_1
            JOIN magic_stats_owner.participants p_1 ON g_1.id = p_1.game_id
            JOIN magic_stats_owner.decks d_1 ON p_1.deck_id = d_1.id
            JOIN magic_stats_owner.color_identities ci_1 ON d_1.color_identity = ci_1.name
            JOIN magic_stats_owner.color_components cic_1 ON ci_1.name = cic_1.color_identity
            JOIN magic_stats_owner.colors c_1 ON cic_1.color = c_1.name
            WHERE c_1.name = c.name AND g_1.cedh = false
            GROUP BY g_1.id, c_1.name
        ) temp
    ), 2) AS average,
    ROUND(
        COUNT(DISTINCT CASE WHEN cic.color = c.name THEN d.id ELSE NULL END)::numeric * 100.0
        / NULLIF((SELECT COUNT(DISTINCT decks.id) FROM magic_stats_owner.decks), 0)::numeric,
        2
    ) AS deck_percentage
FROM magic_stats_owner.games g
JOIN magic_stats_owner.participants p ON g.id = p.game_id
JOIN magic_stats_owner.decks d ON p.deck_id = d.id
JOIN magic_stats_owner.color_identities ci ON d.color_identity = ci.name
JOIN magic_stats_owner.color_components cic ON ci.name = cic.color_identity
JOIN magic_stats_owner.colors c ON cic.color = c.name
WHERE g.cedh = false AND d.cedh = false
GROUP BY c.name;

CREATE OR REPLACE VIEW magic_stats_owner.v_color_usage_player AS
SELECT
    p.name AS "Player",
    COUNT(DISTINCT d.id) AS "Decks",
    ROUND(SUM(CASE WHEN cc.color = 'White' THEN 1 ELSE 0 END)::numeric * 100.0 / NULLIF(COUNT(DISTINCT d.id), 0)::numeric, 2) AS white,
    ROUND(SUM(CASE WHEN cc.color = 'Blue' THEN 1 ELSE 0 END)::numeric * 100.0 / NULLIF(COUNT(DISTINCT d.id), 0)::numeric, 2) AS blue,
    ROUND(SUM(CASE WHEN cc.color = 'Black' THEN 1 ELSE 0 END)::numeric * 100.0 / NULLIF(COUNT(DISTINCT d.id), 0)::numeric, 2) AS black,
    ROUND(SUM(CASE WHEN cc.color = 'Red' THEN 1 ELSE 0 END)::numeric * 100.0 / NULLIF(COUNT(DISTINCT d.id), 0)::numeric, 2) AS red,
    ROUND(SUM(CASE WHEN cc.color = 'Green' THEN 1 ELSE 0 END)::numeric * 100.0 / NULLIF(COUNT(DISTINCT d.id), 0)::numeric, 2) AS green,
    (SELECT ROUND(AVG(ci_1.amount), 2)
     FROM magic_stats_owner.players p_1
     JOIN magic_stats_owner.decks d_1 ON p_1.id = d_1.player_id
     JOIN magic_stats_owner.color_identities ci_1 ON d_1.color_identity = ci_1.name
     WHERE p_1.name = p.name AND d_1.active = true AND d_1.cedh = false
     GROUP BY p_1.id) AS avg_number_of_colors
FROM magic_stats_owner.players p
JOIN magic_stats_owner.decks d ON d.player_id = p.id AND d.active = true AND d.cedh = false
JOIN magic_stats_owner.color_identities ci ON ci.name = d.color_identity
LEFT JOIN magic_stats_owner.color_components cc ON cc.color_identity = d.color_identity
LEFT JOIN magic_stats_owner.colors c ON cc.color = c.name
GROUP BY p.name
ORDER BY COUNT(DISTINCT d.id) DESC;

-- =============================================================================
-- End of full build script.
-- =============================================================================
