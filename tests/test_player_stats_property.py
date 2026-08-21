# Feature: raw-sql-to-orm, Property 1: Player Stats Aggregation Correctness
"""
Property test verifying that `get_player_stats` produces game counts, win counts,
first-player counts, early sol ring counts, and all derived percentages that match
a simple reference calculation — where game/win/first counts exclude cEDH games,
sol ring count includes all games, sol ring percentage uses post-2024-04-19 games
as denominator, and all percentages are rounded to exactly 2 decimal places.

**Validates: Requirements 1.1, 1.2, 1.5, 1.8**
"""

import pytest
from datetime import date, timedelta

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.api.queries import get_player_stats


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=65, max_codepoint=122),
    min_size=2,
    max_size=12,
)


@st.composite
def player_stats_scenario(draw):
    """Generate a scenario with players, games, and participations.

    Constraints:
    - At least 2 players (none named "Precons")
    - Each player has at least one game within the last 365 days (so they appear in results)
    - Games have mixed cEDH flags, random winners, first_players
    - Participants link players to games with random early_sol_ring
    """
    # Generate 2-4 players with unique names (excluding "Precons")
    num_players = draw(st.integers(min_value=2, max_value=4))
    player_names = draw(
        st.lists(
            name_strategy.filter(lambda n: n.lower() != "precons"),
            min_size=num_players,
            max_size=num_players,
            unique=True,
        )
    )
    players = [{"id": i + 1, "name": name} for i, name in enumerate(player_names)]
    player_ids = [p["id"] for p in players]

    # Generate games: mix of dates and cEDH flags
    # Ensure we have at least one recent game per player
    today = date.today()
    recent_date_strategy = st.dates(
        min_value=today - timedelta(days=300),
        max_value=today,
    )
    old_date_strategy = st.dates(
        min_value=date(2023, 1, 1),
        max_value=today - timedelta(days=400),
    )
    # Also include some dates around the sol ring cutoff (2024-04-19)
    sol_ring_area_strategy = st.dates(
        min_value=date(2024, 3, 1),
        max_value=date(2024, 6, 30),
    )

    date_strategy = st.one_of(recent_date_strategy, old_date_strategy, sol_ring_area_strategy)

    num_games = draw(st.integers(min_value=num_players, max_value=num_players + 6))
    games = []
    for i in range(num_games):
        game_date = draw(date_strategy)
        cedh = draw(st.booleans())
        winner_id = draw(st.sampled_from(player_ids + [None]))
        first_player_id = draw(st.sampled_from(player_ids + [None]))
        games.append({
            "id": i + 1,
            "date": game_date,
            "cedh": cedh,
            "winner_id": winner_id,
            "first_player_id": first_player_id,
        })

    # Ensure each player has at least one recent game participation
    # First, assign one recent game per player
    participations = []
    participation_keys = set()  # (game_id, player_id) to avoid duplicates

    for idx, player in enumerate(players):
        # Assign the first N games to ensure coverage; override date if needed
        game_idx = idx % num_games
        games[game_idx]["date"] = draw(recent_date_strategy)
        key = (games[game_idx]["id"], player["id"])
        if key not in participation_keys:
            participation_keys.add(key)
            participations.append({
                "game_id": games[game_idx]["id"],
                "player_id": player["id"],
                "early_sol_ring": draw(st.booleans()),
            })

    # Add more random participations
    extra_participations = draw(st.integers(min_value=0, max_value=8))
    for _ in range(extra_participations):
        game_id = draw(st.sampled_from([g["id"] for g in games]))
        player_id = draw(st.sampled_from(player_ids))
        key = (game_id, player_id)
        if key not in participation_keys:
            participation_keys.add(key)
            participations.append({
                "game_id": game_id,
                "player_id": player_id,
                "early_sol_ring": draw(st.booleans()),
            })

    return {"players": players, "games": games, "participations": participations}


# ---------------------------------------------------------------------------
# Reference Implementation
# ---------------------------------------------------------------------------

SOL_RING_CUTOFF = date(2024, 4, 19)


def reference_player_stats(players, games, participations):
    """Simple reference calculation of player stats.

    Returns a dict mapping player name -> expected stats.

    Key semantics from the implementation:
    - game count: count of participations in non-cEDH games
    - win count: count of ALL non-cEDH games where winner_id = player.id
      (does NOT require participation in that game)
    - first count: count of ALL non-cEDH games where first_player_id = player.id
      (does NOT require participation in that game)
    - early_sol_ring: count of participations with early_sol_ring=True (all games)
    - sol ring denominator: count of participations in games after 2024-04-19 (all games)
    """
    today = date.today()
    activity_cutoff = today - timedelta(days=365)

    # Build lookup: game_id -> game
    game_map = {g["id"]: g for g in games}

    results = {}
    for player in players:
        pid = player["id"]

        # Get all participations for this player
        player_parts = [p for p in participations if p["player_id"] == pid]

        # Check activity: at least one game within 365 days
        has_recent = any(
            game_map[p["game_id"]]["date"] >= activity_cutoff
            for p in player_parts
        )
        if not has_recent:
            continue

        # Games = participations where game.cedh is False
        non_cedh_games = [
            p for p in player_parts if game_map[p["game_id"]]["cedh"] is False
        ]
        game_count = len(non_cedh_games)

        # Wins = ALL non-cEDH games where winner_id = player.id
        # (correlated subquery on Game table, no participation join)
        win_count = sum(
            1 for g in games
            if g["cedh"] is False and g["winner_id"] == pid
        )

        # First = ALL non-cEDH games where first_player_id = player.id
        # (correlated subquery on Game table, no participation join)
        first_count = sum(
            1 for g in games
            if g["cedh"] is False and g["first_player_id"] == pid
        )

        # Early sol ring = participations where early_sol_ring is True (all games)
        early_sol_ring = sum(
            1 for p in player_parts if p["early_sol_ring"] is True
        )

        # Sol ring percentage: denominator = participations in games after 2024-04-19 (all games)
        games_after_cutoff = sum(
            1 for p in player_parts
            if game_map[p["game_id"]]["date"] > SOL_RING_CUTOFF
        )

        if games_after_cutoff > 0:
            sol_ring_pct = round((early_sol_ring * 100) / games_after_cutoff, 2)
        else:
            sol_ring_pct = 0.00

        if game_count > 0:
            winrate_pct = round((win_count * 100) / game_count, 2)
            first_pct = round((first_count * 100) / game_count, 2)
        else:
            winrate_pct = 0.00
            first_pct = 0.00

        results[player["name"]] = {
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


@given(data=player_stats_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_player_stats_aggregation_correctness(app, db_session, data):
    """Property 1: For any set of players with game participations (including a mix
    of cEDH and non-cEDH games, varying winners, first-players, and early sol ring
    values), get_player_stats SHALL produce game counts, win counts, first-player
    counts, early sol ring counts, and all derived percentages that match a simple
    reference calculation.
    """
    with app.app_context():
        # Clean existing data
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert a ColorIdentity for FK constraints on Deck
        ci = ColorIdentity(name="TestColor", amount=1)
        db_session.add(ci)
        db_session.flush()

        # Insert players
        for p in data["players"]:
            player = Player(id=p["id"], name=p["name"])
            db_session.add(player)
        db_session.flush()

        # We need a Deck per player to satisfy the Participant.deck_id FK
        deck_map = {}  # player_id -> deck_id
        for i, p in enumerate(data["players"]):
            deck = Deck(
                id=i + 1,
                name=f"Deck_{p['name']}",
                commander=f"Commander_{p['name']}",
                player_id=p["id"],
                active=True,
                color_identity="TestColor",
            )
            db_session.add(deck)
            deck_map[p["id"]] = deck.id
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
                deck_id=deck_map[part["player_id"]],
                early_sol_ring=part["early_sol_ring"],
            )
            db_session.add(participant)
        db_session.flush()

        # Call the function under test
        actual_results = get_player_stats(db_session)

        # Compute reference
        expected = reference_player_stats(
            data["players"], data["games"], data["participations"]
        )

        # Verify: actual results should match reference for all players
        actual_by_name = {r["name"]: r for r in actual_results}

        # Every player in reference should appear in actual
        for name, exp_stats in expected.items():
            assert name in actual_by_name, (
                f"Player '{name}' expected in results but not found. "
                f"Actual players: {list(actual_by_name.keys())}"
            )
            actual = actual_by_name[name]

            assert actual["games"] == exp_stats["games"], (
                f"Player '{name}': games {actual['games']} != expected {exp_stats['games']}"
            )
            assert actual["wins"] == exp_stats["wins"], (
                f"Player '{name}': wins {actual['wins']} != expected {exp_stats['wins']}"
            )
            assert actual["first"] == exp_stats["first"], (
                f"Player '{name}': first {actual['first']} != expected {exp_stats['first']}"
            )
            assert actual["early_sol_ring"] == exp_stats["early_sol_ring"], (
                f"Player '{name}': early_sol_ring {actual['early_sol_ring']} != expected {exp_stats['early_sol_ring']}"
            )
            assert actual["sol_ring_pct"] == exp_stats["sol_ring_pct"], (
                f"Player '{name}': sol_ring_pct {actual['sol_ring_pct']} != expected {exp_stats['sol_ring_pct']}"
            )
            assert actual["winrate_pct"] == exp_stats["winrate_pct"], (
                f"Player '{name}': winrate_pct {actual['winrate_pct']} != expected {exp_stats['winrate_pct']}"
            )
            assert actual["first_pct"] == exp_stats["first_pct"], (
                f"Player '{name}': first_pct {actual['first_pct']} != expected {exp_stats['first_pct']}"
            )

        # No extra players in actual that aren't in reference
        for name in actual_by_name:
            assert name in expected, (
                f"Player '{name}' in actual results but not in reference. "
                f"Expected players: {list(expected.keys())}"
            )
