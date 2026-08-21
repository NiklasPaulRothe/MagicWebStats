# Feature: raw-sql-to-orm, Property 9: Year-Filtered Stats
"""
Property test verifying that `get_player_stats_by_year` computes all aggregates
using only games from the specified year, uses year-filtered non-cEDH games as the
sol ring percentage denominator, and includes only players with at least one game
in that year.

**Validates: Requirements 6.1, 6.2, 6.3**
"""

from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Game, Participant, Deck, ColorIdentity
from app.api.queries import get_player_stats_by_year


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def year_filtered_scenario(draw):
    """Generate a scenario with players, games spanning multiple years, and participants.

    Creates 2-3 players (not "Precons"), a target year (2024), and games in both
    the target year and other years. Participants have mixed sol_ring values.
    Some games are cEDH, some are not.
    """
    target_year = 2024

    # Generate 2-3 players with unique names (never "Precons")
    num_players = draw(st.integers(min_value=2, max_value=3))
    players = [{"id": i + 1, "name": f"Player_{i + 1}"} for i in range(num_players)]
    player_ids = [p["id"] for p in players]

    # Generate games spanning multiple years:
    # At least 1 game in target year, at least 1 in another year
    other_years = [2022, 2023, 2025]

    # Games in the target year (1-4 games)
    num_target_games = draw(st.integers(min_value=1, max_value=4))
    # Games in other years (1-3 games)
    num_other_games = draw(st.integers(min_value=1, max_value=3))

    games = []
    game_id = 1

    # Target year games
    for _ in range(num_target_games):
        month = draw(st.integers(min_value=1, max_value=12))
        day = draw(st.integers(min_value=1, max_value=28))
        cedh = draw(st.booleans())
        winner_id = draw(st.sampled_from(player_ids + [None]))
        first_player_id = draw(st.sampled_from(player_ids + [None]))
        games.append({
            "id": game_id,
            "date": date(target_year, month, day),
            "cedh": cedh,
            "winner_id": winner_id,
            "first_player_id": first_player_id,
        })
        game_id += 1

    # Other year games
    for _ in range(num_other_games):
        year = draw(st.sampled_from(other_years))
        month = draw(st.integers(min_value=1, max_value=12))
        day = draw(st.integers(min_value=1, max_value=28))
        cedh = draw(st.booleans())
        winner_id = draw(st.sampled_from(player_ids + [None]))
        first_player_id = draw(st.sampled_from(player_ids + [None]))
        games.append({
            "id": game_id,
            "date": date(year, month, day),
            "cedh": cedh,
            "winner_id": winner_id,
            "first_player_id": first_player_id,
        })
        game_id += 1

    # Generate participations: each game gets 2 to num_players participants
    # Ensure all players participate in at least one target-year game
    # so that they appear in results (we test exclusion separately)
    participations = []
    target_game_ids = [g["id"] for g in games if g["date"].year == target_year]
    other_game_ids = [g["id"] for g in games if g["date"].year != target_year]

    # Ensure each player participates in at least one target year game
    for pid in player_ids:
        gid = draw(st.sampled_from(target_game_ids))
        early_sol_ring = draw(st.booleans())
        participations.append({
            "game_id": gid,
            "player_id": pid,
            "early_sol_ring": early_sol_ring,
        })

    # Add more random participations across all games
    num_extra = draw(st.integers(min_value=2, max_value=8))
    all_game_ids = [g["id"] for g in games]
    for _ in range(num_extra):
        gid = draw(st.sampled_from(all_game_ids))
        pid = draw(st.sampled_from(player_ids))
        early_sol_ring = draw(st.booleans())
        participations.append({
            "game_id": gid,
            "player_id": pid,
            "early_sol_ring": early_sol_ring,
        })

    # Deduplicate (game_id, player_id) pairs - keep first occurrence
    seen = set()
    unique_participations = []
    for part in participations:
        key = (part["game_id"], part["player_id"])
        if key not in seen:
            seen.add(key)
            unique_participations.append(part)

    # Optionally add a player who only has games in other years (to test exclusion)
    extra_player_id = num_players + 1
    add_excluded_player = draw(st.booleans())
    if add_excluded_player and other_game_ids:
        players.append({"id": extra_player_id, "name": f"Player_{extra_player_id}"})
        gid = draw(st.sampled_from(other_game_ids))
        unique_participations.append({
            "game_id": gid,
            "player_id": extra_player_id,
            "early_sol_ring": False,
        })

    return {
        "target_year": target_year,
        "players": players,
        "games": games,
        "participations": unique_participations,
    }


# ---------------------------------------------------------------------------
# Reference Implementation
# ---------------------------------------------------------------------------


def reference_year_stats(target_year, players, games, participations):
    """Simple reference calculation of year-filtered player stats.

    Returns a dict mapping player_name -> expected stats (or None if excluded).

    Semantics:
    - game_count: non-cEDH games in target year where player participated
    - win_count: ALL non-cEDH games in target year where winner_id == player_id
                 (does NOT require a participation record — matches ORM subquery)
    - first_count: ALL non-cEDH games in target year where first_player_id == player_id
                   (does NOT require a participation record — matches ORM subquery)
    - early_sol_ring: participations in target year games (all, regardless of cEDH)
                      where early_sol_ring is True
    - sol_ring_pct: round((early_sol_ring * 100) / year_non_cedh_games, 2) or 0.00
    - Only players with at least one participation in a target year game are included
    """
    game_map = {g["id"]: g for g in games}

    # Determine target year game IDs
    target_year_game_ids = {
        g["id"] for g in games if g["date"].year == target_year
    }
    target_year_non_cedh_games = [
        g for g in games
        if g["date"].year == target_year and not g["cedh"]
    ]

    results = {}
    for player in players:
        pid = player["id"]
        pname = player["name"]

        # Check if player has at least one game in target year
        has_target_year_game = any(
            p["player_id"] == pid and p["game_id"] in target_year_game_ids
            for p in participations
        )
        if not has_target_year_game:
            continue

        # Game count: participations in non-cEDH games in target year
        target_year_non_cedh_game_ids = {g["id"] for g in target_year_non_cedh_games}
        game_count = sum(
            1 for p in participations
            if p["player_id"] == pid
            and p["game_id"] in target_year_non_cedh_game_ids
        )

        # Win count: ALL non-cEDH games in target year where winner_id == player_id
        # (counted from Game table, no participation check needed)
        win_count = sum(
            1 for g in target_year_non_cedh_games
            if g["winner_id"] == pid
        )

        # First count: ALL non-cEDH games in target year where first_player_id == player_id
        # (counted from Game table, no participation check needed)
        first_count = sum(
            1 for g in target_year_non_cedh_games
            if g["first_player_id"] == pid
        )

        # Early sol ring: participations in target year games (ALL, including cEDH)
        # where early_sol_ring is True
        early_sol_ring = sum(
            1 for p in participations
            if p["player_id"] == pid
            and p["game_id"] in target_year_game_ids
            and p["early_sol_ring"]
        )

        # Sol ring denominator: non-cEDH games in target year for this player
        sol_ring_denominator = game_count  # same as game_count for year-filtered

        # Sol ring percentage
        if sol_ring_denominator > 0:
            sol_ring_pct = round((early_sol_ring * 100) / sol_ring_denominator, 2)
        else:
            sol_ring_pct = 0.00

        # Winrate
        if game_count > 0:
            winrate_pct = round((win_count * 100) / game_count, 2)
        else:
            winrate_pct = 0.00

        # First percentage
        if game_count > 0:
            first_pct = round((first_count * 100) / game_count, 2)
        else:
            first_pct = 0.00

        results[pname] = {
            "games": game_count,
            "wins": win_count,
            "first": first_count,
            "early_sol_ring": early_sol_ring,
            "sol_ring_pct": sol_ring_pct,
            "winrate_pct": winrate_pct,
            "first_pct": first_pct,
        }

    return results


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=year_filtered_scenario())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_year_filtered_stats(app, db_session, data):
    """Property 9: For any year and set of games spanning multiple years, the
    year-filtered player stats query SHALL compute all aggregates using only games
    from the specified year, use year-filtered games as the sol ring percentage
    denominator, and include only players with at least one game in that year.
    """
    with app.app_context():
        target_year = data["target_year"]

        # Clean existing data (order matters for FK constraints)
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert a color identity for decks
        ci = ColorIdentity(name="TestColor", amount=1)
        db_session.add(ci)
        db_session.flush()

        # Insert players
        for p in data["players"]:
            player = Player(id=p["id"], name=p["name"])
            db_session.add(player)
        db_session.flush()

        # Insert decks (one per player, needed for Participant FK)
        for p in data["players"]:
            deck = Deck(
                id=p["id"],
                name=f"Deck_{p['name']}",
                commander=f"Commander_{p['name']}",
                player_id=p["id"],
                active=True,
                color_identity="TestColor",
            )
            db_session.add(deck)
        db_session.flush()

        # Insert games
        for g in data["games"]:
            game = Game(
                id=g["id"],
                date=g["date"],
                cedh=g["cedh"],
                winner_id=g["winner_id"],
                first_player_id=g["first_player_id"],
            )
            db_session.add(game)
        db_session.flush()

        # Insert participations
        for part in data["participations"]:
            participant = Participant(
                game_id=part["game_id"],
                player_id=part["player_id"],
                deck_id=part["player_id"],  # Use player_id as deck_id
                early_sol_ring=part["early_sol_ring"],
            )
            db_session.add(participant)
        db_session.flush()

        # Execute the query under test
        actual_results = get_player_stats_by_year(db_session, target_year)

        # Compute reference results
        expected = reference_year_stats(
            target_year,
            data["players"],
            data["games"],
            data["participations"],
        )

        # Build lookup by player name
        actual_by_name = {r["name"]: r for r in actual_results}

        # Verify only players with target year games are included
        for player in data["players"]:
            pname = player["name"]
            if pname in expected:
                assert pname in actual_by_name, (
                    f"Player '{pname}' expected in year-filtered results but not found. "
                    f"Actual players: {list(actual_by_name.keys())}"
                )
            else:
                assert pname not in actual_by_name, (
                    f"Player '{pname}' should be excluded (no games in {target_year}) "
                    f"but was found in results."
                )

        # Verify stats for each included player
        for pname, exp in expected.items():
            actual = actual_by_name[pname]

            # Verify game count (non-cEDH games in target year)
            assert actual["games"] == exp["games"], (
                f"Player '{pname}': games {actual['games']} != expected {exp['games']}"
            )

            # Verify win count (non-cEDH games in target year where winner = player)
            assert actual["wins"] == exp["wins"], (
                f"Player '{pname}': wins {actual['wins']} != expected {exp['wins']}"
            )

            # Verify first count (non-cEDH games in target year where first = player)
            assert actual["first"] == exp["first"], (
                f"Player '{pname}': first {actual['first']} != expected {exp['first']}"
            )

            # Verify early sol ring (target year games, ALL including cEDH)
            assert actual["early_sol_ring"] == exp["early_sol_ring"], (
                f"Player '{pname}': early_sol_ring {actual['early_sol_ring']} "
                f"!= expected {exp['early_sol_ring']}"
            )

            # Verify sol ring percentage
            assert abs(actual["sol_ring_pct"] - exp["sol_ring_pct"]) < 0.01, (
                f"Player '{pname}': sol_ring_pct {actual['sol_ring_pct']} "
                f"!= expected {exp['sol_ring_pct']}"
            )

            # Verify winrate percentage
            assert abs(actual["winrate_pct"] - exp["winrate_pct"]) < 0.01, (
                f"Player '{pname}': winrate_pct {actual['winrate_pct']} "
                f"!= expected {exp['winrate_pct']}"
            )

            # Verify first percentage
            assert abs(actual["first_pct"] - exp["first_pct"]) < 0.01, (
                f"Player '{pname}': first_pct {actual['first_pct']} "
                f"!= expected {exp['first_pct']}"
            )
