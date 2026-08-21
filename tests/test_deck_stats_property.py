# Feature: raw-sql-to-orm, Property 5: Deck Stats Aggregation
"""
Property test verifying that `get_deck_data` computes per-deck game count, win count,
winrate (wins × 100 / games, rounded to 2 decimals, NULL when games is 0), and
average win turns (mean of turns from winning games with non-null turns, rounded to 2
decimals, NULL when no qualifying wins exist).

**Validates: Requirements 3.1, 3.2, 3.4**
"""

import pytest
from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.api.queries import get_deck_data


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def deck_stats_scenario(draw):
    """Generate a scenario with players, active decks, games, and participations.

    Constraints:
    - 1-3 players, each with 1-2 active decks
    - Games with participants, various winners, various turn values (some null)
    - game_count counts ALL participations for the deck (not just the deck owner)
    """
    # Generate 1-3 players
    num_players = draw(st.integers(min_value=1, max_value=3))
    players = [{"id": i + 1, "name": f"Player_{i + 1}"} for i in range(num_players)]
    player_ids = [p["id"] for p in players]

    # Generate decks: each player gets 1-2 active decks
    decks = []
    deck_id = 1
    for player in players:
        num_decks = draw(st.integers(min_value=1, max_value=2))
        for _ in range(num_decks):
            decks.append({
                "id": deck_id,
                "player_id": player["id"],
                "name": f"Deck_{deck_id}",
                "commander": f"Commander_{deck_id}",
            })
            deck_id += 1

    deck_ids = [d["id"] for d in decks]

    # Generate 2-6 games with various winners and turn values
    num_games = draw(st.integers(min_value=2, max_value=6))
    games = []
    for i in range(num_games):
        winner_id = draw(st.sampled_from(player_ids + [None]))
        # turns can be None or a positive integer
        turns = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=20)))
        games.append({
            "id": i + 1,
            "date": date(2024, 6, 15),
            "winner_id": winner_id,
            "turns": turns,
        })

    # Generate participations: each game has 2-min(4, num_players) participants
    # Constraint: (game_id, player_id) must be unique (composite PK)
    participations = []
    for game in games:
        max_parts = min(4, num_players)
        num_parts = draw(st.integers(min_value=2, max_value=max_parts)) if max_parts >= 2 else num_players
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
            # Pick any deck (not necessarily belonging to this player) to test
            # that game_count counts ALL participations for the deck
            chosen_deck_id = draw(st.sampled_from(deck_ids))
            participations.append({
                "game_id": game["id"],
                "player_id": pid,
                "deck_id": chosen_deck_id,
            })

    return {
        "players": players,
        "decks": decks,
        "games": games,
        "participations": participations,
    }


# ---------------------------------------------------------------------------
# Reference Implementation
# ---------------------------------------------------------------------------


def reference_deck_stats(decks, games, participations):
    """Simple reference calculation of deck stats.

    Returns a dict mapping deck_id -> expected stats.

    Key semantics:
    - game_count = total participations for the deck (all players, not just owner)
    - win_count = participations where game.winner_id == participant.player_id AND
                  participant.deck_id == this deck
    - winrate = round((wins * 100) / games, 2) if games > 0, else None
    - avg_win_turns = round(mean(turns from winning games where turns is not null), 2)
                      if any qualifying wins exist, else None

    The win condition for avg_win_turns is:
      game.winner_id == participant.player_id AND participant.deck_id == this deck
      AND game.turns IS NOT NULL
    """
    game_map = {g["id"]: g for g in games}

    results = {}
    for deck in decks:
        deck_id = deck["id"]
        game_count = 0
        win_count = 0
        win_turns = []

        for part in participations:
            if part["deck_id"] == deck_id:
                game_count += 1
                game = game_map[part["game_id"]]
                # Win condition: game.winner_id == participant.player_id
                if game["winner_id"] == part["player_id"]:
                    win_count += 1
                    # Collect turns for avg_win_turns (only when turns is not null)
                    if game["turns"] is not None:
                        win_turns.append(game["turns"])

        # Winrate
        if game_count > 0:
            winrate = round((win_count * 100) / game_count, 2)
        else:
            winrate = None

        # Average win turns
        if win_turns:
            avg_win_turns = round(sum(win_turns) / len(win_turns), 2)
        else:
            avg_win_turns = None

        results[deck_id] = {
            "games": game_count,
            "wins": win_count,
            "winrate_pct": winrate,
            "avg_win_turns": avg_win_turns,
        }

    return results


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=deck_stats_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deck_stats_aggregation(app, db_session, data):
    """Property 5: For any set of active decks with game participations, the deck data
    query SHALL compute per-deck game count, win count, winrate (wins × 100 / games,
    rounded to 2 decimals, NULL when games is 0), and average win turns (mean of turns
    from winning games with non-null turns, rounded to 2 decimals, NULL when no
    qualifying wins exist).
    """
    with app.app_context():
        # Clean existing data
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert a color identity for all decks to reference
        ci = ColorIdentity(name="Azorius", amount=2)
        db_session.add(ci)
        db_session.flush()

        # Insert players
        for p in data["players"]:
            player = Player(id=p["id"], name=p["name"])
            db_session.add(player)
        db_session.flush()

        # Insert decks (all active)
        for d in data["decks"]:
            deck = Deck(
                id=d["id"],
                name=d["name"],
                commander=d["commander"],
                player_id=d["player_id"],
                active=True,
                color_identity="Azorius",
            )
            db_session.add(deck)
        db_session.flush()

        # Insert games
        for g in data["games"]:
            game = Game(
                id=g["id"],
                date=g["date"],
                winner_id=g["winner_id"],
                turns=g["turns"],
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
        actual_results = get_deck_data(db_session)

        # Compute reference
        expected = reference_deck_stats(
            data["decks"],
            data["games"],
            data["participations"],
        )

        # Build lookup by deck name (deck names are unique in our scenario)
        actual_by_name = {r["deck_name"]: r for r in actual_results}

        # Verify each deck
        for deck in data["decks"]:
            deck_name = deck["name"]
            deck_id = deck["id"]
            exp = expected[deck_id]

            assert deck_name in actual_by_name, (
                f"Deck '{deck_name}' expected in results but not found. "
                f"Actual decks: {list(actual_by_name.keys())}"
            )
            actual = actual_by_name[deck_name]

            # Verify game count
            assert actual["games"] == exp["games"], (
                f"Deck '{deck_name}': games {actual['games']} != expected {exp['games']}"
            )

            # Verify win count
            assert actual["wins"] == exp["wins"], (
                f"Deck '{deck_name}': wins {actual['wins']} != expected {exp['wins']}"
            )

            # Verify winrate
            if exp["winrate_pct"] is None:
                assert actual["winrate_pct"] is None, (
                    f"Deck '{deck_name}': winrate_pct should be None but got {actual['winrate_pct']}"
                )
            else:
                assert actual["winrate_pct"] is not None, (
                    f"Deck '{deck_name}': winrate_pct is None but expected {exp['winrate_pct']}"
                )
                assert abs(actual["winrate_pct"] - exp["winrate_pct"]) < 0.01, (
                    f"Deck '{deck_name}': winrate_pct {actual['winrate_pct']} != expected {exp['winrate_pct']}"
                )

            # Verify avg_win_turns
            if exp["avg_win_turns"] is None:
                assert actual["avg_win_turns"] is None, (
                    f"Deck '{deck_name}': avg_win_turns should be None but got {actual['avg_win_turns']}"
                )
            else:
                assert actual["avg_win_turns"] is not None, (
                    f"Deck '{deck_name}': avg_win_turns is None but expected {exp['avg_win_turns']}"
                )
                assert abs(actual["avg_win_turns"] - exp["avg_win_turns"]) < 0.01, (
                    f"Deck '{deck_name}': avg_win_turns {actual['avg_win_turns']} != expected {exp['avg_win_turns']}"
                )
