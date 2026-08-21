-- Fix v_color_usage and v_color_usage_player views
-- Run this against the production database to correct the broken view definitions.

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
