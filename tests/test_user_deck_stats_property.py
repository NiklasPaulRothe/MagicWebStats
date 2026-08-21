# Feature: raw-sql-to-orm, Property 7: User Deck Stats Correctness
"""
Property test verifying that `get_user_decks` returns only active decks belonging
to the target player, and computes game count, win count, and winrate using only
participations for that specific player-deck combination.

**Validates: Requirements 4.1, 4.2, 4.3**
"""

import pytest
from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.api.queries import get_user_decks


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

color_identity_names = st.sampled_from([
    "Azorius", "Dimir", "Rakdos", "Gruul", "Selesnya",
    "Orzhov", "Izzet", "Golgari", "Boros", "Simic",
])


@st.composite
def user_deck_scenario(draw):
    """Generate a scenario with 2-3 players, each having active and inactive decks,
    games with participants using various decks, and a target player to query.

    Constraints:
    - 2-3 players
    - Each player has 1-3 decks with mixed active/inactive status
    - 2-6 games with participants drawn from all players
    - Some games have winners (matching a participant), some have None
    - Target player is randomly chosen from the player list
    """
    # Generate 2-3 players
    num_players = draw(st.integers(min_value=2, max_value=3))
    players = [{"id": i + 1, "name": f"Player_{i + 1}"} for i in range(num_players)]
    player_ids = [p["id"] for p in players]

    # Pick color identities for decks
    ci_names = draw(
        st.lists(
            color_identity_names,
            min_size=2,
            max_size=4,
            unique=True,
        )
    )

    # Generate decks: each player gets 1-3 decks with random active status
    decks = []
    deck_id = 1
    for player in players:
        num_decks = draw(st.integers(min_value=1, max_value=3))
        for d_idx in range(num_decks):
            ci = draw(st.sampled_from(ci_names))
            active = draw(st.booleans())
            decks.append({
                "id": deck_id,
                "name": f"Deck_{deck_id}",
                "commander": f"Commander_{deck_id}",
                "player_id": player["id"],
                "color_identity": ci,
                "active": active,
            })
            deck_id += 1

    # Generate 2-6 games
    num_games = draw(st.integers(min_value=2, max_value=6))
    games = []
    for i in range(num_games):
        winner_id = draw(st.sampled_from(player_ids + [None]))
        games.append({
            "id": i + 1,
            "date": date(2024, 1, 1 + i),
            "winner_id": winner_id,
        })

    # Generate participations: each game has 2-num_players participants
    # (game_id, player_id) must be unique (composite PK)
    participations = []
    for game in games:
        num_parts = draw(st.integers(min_value=2, max_value=num_players))
        chosen_player_ids = draw(
            st.lists(
                st.sampled_from(player_ids),
                min_size=num_parts,
                max_size=num_parts,
                unique=True,
            )
        )
        for pid in chosen_player_ids:
            # Pick any deck (not necessarily belonging to this player, but
            # for realism pick from player's own decks when possible)
            player_decks = [d for d in decks if d["player_id"] == pid]
            if player_decks:
                chosen_deck = draw(st.sampled_from(player_decks))
            else:
                chosen_deck = draw(st.sampled_from(decks))
            participations.append({
                "game_id": game["id"],
                "player_id": pid,
                "deck_id": chosen_deck["id"],
            })

    # Pick a target player
    target_player_id = draw(st.sampled_from(player_ids))

    return {
        "color_identities": ci_names,
        "players": players,
        "decks": decks,
        "games": games,
        "participations": participations,
        "target_player_id": target_player_id,
    }


# ---------------------------------------------------------------------------
# Reference Implementation
# ---------------------------------------------------------------------------


def reference_user_decks(decks, games, participations, target_player_id):
    """Simple reference calculation of user deck stats.

    Returns a list of expected results for active decks belonging to the target player.

    Key semantics:
    - Only active decks belonging to the target player are returned
    - game_count = number of participations where player_id = target AND deck_id = deck
    - win_count = number of those participations where game.winner_id = target player
      AND participant.player_id = target AND participant.deck_id = deck
    - winrate = round((wins * 100) / games, 2) when games > 0, else None
    """
    game_map = {g["id"]: g for g in games}

    results = []
    for deck in decks:
        # Only active decks belonging to the target player
        if deck["player_id"] != target_player_id or not deck["active"]:
            continue

        # Count games for this player+deck
        game_count = 0
        win_count = 0
        for part in participations:
            if part["player_id"] == target_player_id and part["deck_id"] == deck["id"]:
                game_count += 1
                game = game_map[part["game_id"]]
                if game["winner_id"] == target_player_id:
                    win_count += 1

        if game_count > 0:
            winrate = round((win_count * 100) / game_count, 2)
        else:
            winrate = None

        results.append({
            "name": deck["name"],
            "game_count": game_count,
            "win_count": win_count,
            "winrate_pct": winrate,
        })

    # Sort by deck name ascending (matching query ordering)
    results.sort(key=lambda r: r["name"])
    return results


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=user_deck_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_deck_stats_correctness(app, db_session, data):
    """Property 7: For any player ID and set of decks (some active, some inactive,
    some belonging to other players), the user decks query SHALL return only active
    decks belonging to that player, and compute game count, win count, and winrate
    using only participations for that specific player-deck combination.
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
                name=d["name"],
                commander=d["commander"],
                player_id=d["player_id"],
                active=d["active"],
                color_identity=d["color_identity"],
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

        target_player_id = data["target_player_id"]

        # Call the function under test
        actual_results = get_user_decks(db_session, target_player_id)

        # Compute reference
        expected = reference_user_decks(
            data["decks"],
            data["games"],
            data["participations"],
            target_player_id,
        )

        # Verify: correct number of results (only active decks for target player)
        assert len(actual_results) == len(expected), (
            f"Expected {len(expected)} active decks for player {target_player_id}, "
            f"got {len(actual_results)}. "
            f"Expected names: {[r['name'] for r in expected]}, "
            f"Actual names: {[r['name'] for r in actual_results]}"
        )

        # Verify: no inactive decks are returned
        active_deck_ids_for_target = {
            d["id"] for d in data["decks"]
            if d["player_id"] == target_player_id and d["active"]
        }
        inactive_deck_names = {
            d["name"] for d in data["decks"]
            if d["player_id"] == target_player_id and not d["active"]
        }
        actual_names = {r["name"] for r in actual_results}
        assert actual_names.isdisjoint(inactive_deck_names), (
            f"Inactive decks should not appear in results. "
            f"Found: {actual_names & inactive_deck_names}"
        )

        # Verify: no decks from other players are returned
        other_player_deck_names = {
            d["name"] for d in data["decks"]
            if d["player_id"] != target_player_id
        }
        assert actual_names.isdisjoint(other_player_deck_names), (
            f"Decks from other players should not appear in results. "
            f"Found: {actual_names & other_player_deck_names}"
        )

        # Verify: game_count, win_count, and winrate match reference for each deck
        for i, (actual, exp) in enumerate(zip(actual_results, expected)):
            assert actual["name"] == exp["name"], (
                f"Deck name mismatch at position {i}: "
                f"actual='{actual['name']}' vs expected='{exp['name']}'"
            )

            assert actual["games"] == exp["game_count"], (
                f"Deck '{actual['name']}': game_count {actual['games']} != "
                f"expected {exp['game_count']} "
                f"(should count only participations for player {target_player_id})"
            )

            assert actual["wins"] == exp["win_count"], (
                f"Deck '{actual['name']}': win_count {actual['wins']} != "
                f"expected {exp['win_count']} "
                f"(should count only wins where winner_id = {target_player_id} "
                f"AND participant uses this deck)"
            )

            if exp["winrate_pct"] is None:
                assert actual["winrate_pct"] is None, (
                    f"Deck '{actual['name']}': winrate should be None when "
                    f"games == 0, got {actual['winrate_pct']}"
                )
            else:
                assert actual["winrate_pct"] == pytest.approx(exp["winrate_pct"], abs=0.01), (
                    f"Deck '{actual['name']}': winrate_pct {actual['winrate_pct']} != "
                    f"expected {exp['winrate_pct']} "
                    f"(should be round((wins * 100) / games, 2))"
                )
