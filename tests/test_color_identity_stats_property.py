# Feature: raw-sql-to-orm, Property 4: Color Identity Stats Aggregation
"""
Property test verifying that `get_color_data` produces game counts and win counts
that exclude cEDH games, compute winrate as (wins × 100 / games) rounded to 2
decimal places, and exclude any color identity with zero qualifying games.

**Validates: Requirements 2.1, 2.2, 2.3**
"""

import pytest
from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.api.queries import get_color_data


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

color_identity_names = st.sampled_from([
    "Azorius", "Dimir", "Rakdos", "Gruul", "Selesnya",
    "Orzhov", "Izzet", "Golgari", "Boros", "Simic",
    "Esper", "Jund", "Naya", "Sultai", "Mardu",
])


@st.composite
def color_data_scenario(draw):
    """Generate a scenario with color identities, players, decks, games, and participations.

    Constraints:
    - 2-4 color identities
    - 2-4 players
    - Each player has at least one deck; decks have various color identities
    - Some decks have cedh=True, some have cedh=False
    - Games with participants; some participants' player_id matches game.winner_id
    """
    # Generate 2-4 unique color identities
    num_cis = draw(st.integers(min_value=2, max_value=4))
    ci_names = draw(
        st.lists(
            color_identity_names,
            min_size=num_cis,
            max_size=num_cis,
            unique=True,
        )
    )

    # Generate 2-4 players
    num_players = draw(st.integers(min_value=2, max_value=4))
    players = [{"id": i + 1, "name": f"Player_{i + 1}"} for i in range(num_players)]
    player_ids = [p["id"] for p in players]

    # Generate decks: each player gets 1-2 decks with random color identity and cedh flag
    decks = []
    deck_id = 1
    for player in players:
        num_decks = draw(st.integers(min_value=1, max_value=2))
        for _ in range(num_decks):
            ci = draw(st.sampled_from(ci_names))
            cedh = draw(st.booleans())
            decks.append({
                "id": deck_id,
                "player_id": player["id"],
                "color_identity": ci,
                "cedh": cedh,
            })
            deck_id += 1

    # Generate 3-8 games
    num_games = draw(st.integers(min_value=3, max_value=8))
    games = []
    for i in range(num_games):
        winner_id = draw(st.sampled_from(player_ids + [None]))
        games.append({
            "id": i + 1,
            "date": date(2024, 6, 15),
            "winner_id": winner_id,
        })

    # Generate participations: each game has 2-4 participants
    # Constraint: (game_id, player_id) must be unique (composite PK)
    participations = []
    for game in games:
        num_parts = draw(st.integers(min_value=2, max_value=min(4, num_players)))
        # Pick distinct players for this game
        chosen_player_ids = draw(
            st.lists(
                st.sampled_from(player_ids),
                min_size=num_parts,
                max_size=num_parts,
                unique=True,
            )
        )
        for pid in chosen_player_ids:
            # Pick a deck belonging to this player
            player_decks = [d for d in decks if d["player_id"] == pid]
            chosen_deck = draw(st.sampled_from(player_decks))
            participations.append({
                "game_id": game["id"],
                "player_id": pid,
                "deck_id": chosen_deck["id"],
            })

    return {
        "color_identities": ci_names,
        "players": players,
        "decks": decks,
        "games": games,
        "participations": participations,
    }


# ---------------------------------------------------------------------------
# Reference Implementation
# ---------------------------------------------------------------------------


def reference_color_data(color_identities, decks, games, participations):
    """Simple reference calculation of color identity stats.

    Returns a dict mapping color identity name -> expected stats.

    Key semantics:
    - game_count per CI = count of participations where the participant's deck has
      that color identity AND deck.cedh == False
    - win_count per CI = count of participations where the participant's deck has
      that color identity AND deck.cedh == False AND game.winner_id == participant.player_id
    - winrate = round((wins * 100) / games, 2)
    - CIs with 0 qualifying games are excluded
    """
    # Build lookups
    deck_map = {d["id"]: d for d in decks}
    game_map = {g["id"]: g for g in games}

    results = {}
    for ci_name in color_identities:
        game_count = 0
        win_count = 0

        for part in participations:
            deck = deck_map[part["deck_id"]]
            # Only count participations where deck's color identity matches and cedh is False
            if deck["color_identity"] == ci_name and deck["cedh"] is False:
                game_count += 1
                # Check if this participant's player won the game
                game = game_map[part["game_id"]]
                if game["winner_id"] == part["player_id"]:
                    win_count += 1

        if game_count > 0:
            winrate = round((win_count * 100) / game_count, 2)
            results[ci_name] = {
                "games": game_count,
                "wins": win_count,
                "winrate_pct": winrate,
            }

    return results


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=color_data_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_color_identity_stats_aggregation(app, db_session, data):
    """Property 4: For any set of games involving decks with various color identities
    (mix of cEDH and non-cEDH), the color data query SHALL produce game counts and
    win counts that exclude cEDH games, compute winrate as (wins × 100 / games)
    rounded to 2 decimal places, and exclude any color identity with zero qualifying
    games.
    """
    with app.app_context():
        # Clean existing data
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert color identities
        for ci_name in data["color_identities"]:
            ci = ColorIdentity(name=ci_name, amount=1)
            db_session.add(ci)
        db_session.flush()

        # Insert players
        for p in data["players"]:
            player = Player(id=p["id"], name=p["name"])
            db_session.add(player)
        db_session.flush()

        # Insert decks
        for d in data["decks"]:
            deck = Deck(
                id=d["id"],
                name=f"Deck_{d['id']}",
                commander=f"Commander_{d['id']}",
                player_id=d["player_id"],
                active=True,
                color_identity=d["color_identity"],
                cedh=d["cedh"],
            )
            db_session.add(deck)
        db_session.flush()

        # Insert games
        for g in data["games"]:
            game = Game(
                id=g["id"],
                date=g["date"],
                winner_id=g["winner_id"],
            )
            db_session.add(game)
        db_session.flush()

        # Insert participations
        for part in data["participations"]:
            participant = Participant(
                game_id=part["game_id"],
                player_id=part["player_id"],
                deck_id=part["deck_id"],
            )
            db_session.add(participant)
        db_session.flush()

        # Call the function under test
        actual_results = get_color_data(db_session)

        # Compute reference
        expected = reference_color_data(
            data["color_identities"],
            data["decks"],
            data["games"],
            data["participations"],
        )

        # Verify: actual results should match reference
        actual_by_name = {r["name"]: r for r in actual_results}

        # Every CI in reference should appear in actual results
        for ci_name, exp_stats in expected.items():
            assert ci_name in actual_by_name, (
                f"Color identity '{ci_name}' expected in results but not found. "
                f"Actual CIs: {list(actual_by_name.keys())}"
            )
            actual = actual_by_name[ci_name]

            assert actual["games"] == exp_stats["games"], (
                f"CI '{ci_name}': games {actual['games']} != expected {exp_stats['games']}"
            )
            assert actual["wins"] == exp_stats["wins"], (
                f"CI '{ci_name}': wins {actual['wins']} != expected {exp_stats['wins']}"
            )
            assert actual["winrate_pct"] == exp_stats["winrate_pct"], (
                f"CI '{ci_name}': winrate_pct {actual['winrate_pct']} != expected {exp_stats['winrate_pct']}"
            )

        # No extra CIs in actual that aren't in reference
        for ci_name in actual_by_name:
            assert ci_name in expected, (
                f"Color identity '{ci_name}' in actual results but not in reference "
                f"(should be excluded due to 0 qualifying games). "
                f"Expected CIs: {list(expected.keys())}"
            )
