# Feature: codebase-normalization, Property 1: Game-history row building preserves game data
"""
Property test verifying that `build_game_history()` produces correct game-history
rows: row count equals number of games the deck participated in, each row's `datum`
matches the corresponding game's date, `is_win` correctly reflects whether the deck's
owner is the game winner, and `gegner` contains all opponents (participants whose
player_id differs from the deck's player_id).

**Validates: Requirements 2.2, 2.7**
"""

from datetime import date, timedelta
from types import SimpleNamespace

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.deck_service import build_game_history


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def game_history_scenario(draw):
    """Generate a scenario with a deck, its owner, games, and participants.

    Produces:
    - A deck with a specific player_id (the "owner")
    - 1-5 games the deck participated in
    - 2-4 opponents per game (different player_ids)
    - A winner_id for each game (may or may not be the deck owner)
    - Player and deck lookup dicts
    """
    # Generate player IDs: the owner plus 2-5 opponents
    owner_id = draw(st.integers(min_value=1, max_value=100))
    num_opponents = draw(st.integers(min_value=1, max_value=4))
    opponent_ids = draw(
        st.lists(
            st.integers(min_value=101, max_value=999),
            min_size=num_opponents,
            max_size=num_opponents,
            unique=True,
        )
    )
    all_player_ids = [owner_id] + opponent_ids

    # Generate the deck under test
    deck_id = draw(st.integers(min_value=1, max_value=100))
    deck = SimpleNamespace(
        id=deck_id,
        player_id=owner_id,
        name="TestDeck",
        image_uri=None,
    )

    # Generate opponent decks
    opponent_deck_ids = draw(
        st.lists(
            st.integers(min_value=101, max_value=999),
            min_size=num_opponents,
            max_size=num_opponents,
            unique=True,
        )
    )

    # Build players dict
    players = {owner_id: SimpleNamespace(id=owner_id, name=f"Player_{owner_id}")}
    for opp_id in opponent_ids:
        players[opp_id] = SimpleNamespace(id=opp_id, name=f"Player_{opp_id}")

    # Build decks dict
    decks = {deck_id: deck}
    for i, opp_deck_id in enumerate(opponent_deck_ids):
        decks[opp_deck_id] = SimpleNamespace(
            id=opp_deck_id,
            player_id=opponent_ids[i],
            name=f"OppDeck_{opp_deck_id}",
            image_uri=None,
        )

    # Generate 1-5 games
    num_games = draw(st.integers(min_value=1, max_value=5))
    base_date = date(2024, 1, 1)

    games = {}
    participants_by_game = {}
    owner_participants = []

    for game_idx in range(num_games):
        game_id = game_idx + 1
        game_date = base_date + timedelta(days=draw(st.integers(min_value=0, max_value=365)))
        # Winner is either the owner or one of the opponents
        winner_id = draw(st.sampled_from(all_player_ids))
        turns = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=20)))
        final_blow = draw(st.one_of(st.none(), st.sampled_from(["Combat", "Combo", "Commander"])))

        games[game_id] = SimpleNamespace(
            id=game_id,
            date=game_date,
            winner_id=winner_id,
            turns=turns,
            final_blow=final_blow,
        )

        # Create participants for this game: the owner + a subset of opponents
        num_game_opponents = draw(st.integers(min_value=1, max_value=num_opponents))
        game_opponent_ids = draw(
            st.lists(
                st.sampled_from(opponent_ids),
                min_size=num_game_opponents,
                max_size=num_game_opponents,
                unique=True,
            )
        )

        game_participants = []

        # Owner's participant
        owner_part = SimpleNamespace(
            game_id=game_id,
            player_id=owner_id,
            deck_id=deck_id,
            mulligans=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=5))),
            landdrops=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=10))),
            lands=draw(st.one_of(st.none(), st.integers(min_value=0, max_value=40))),
            enough_mana=draw(st.one_of(st.none(), st.booleans())),
            enough_gas=draw(st.one_of(st.none(), st.booleans())),
            deckplan=draw(st.one_of(st.none(), st.booleans())),
            unanswered_threats=draw(st.one_of(st.none(), st.booleans())),
            fun_moments=draw(st.one_of(st.none(), st.booleans())),
            loss_without_answer=draw(st.one_of(st.none(), st.booleans())),
            selfmade_win=draw(st.one_of(st.none(), st.booleans())),
            comments=draw(st.one_of(st.none(), st.text(min_size=0, max_size=20))),
        )
        game_participants.append(owner_part)
        owner_participants.append(owner_part)

        # Opponents' participants
        for opp_id in game_opponent_ids:
            opp_deck_id = opponent_deck_ids[opponent_ids.index(opp_id)]
            opp_part = SimpleNamespace(
                game_id=game_id,
                player_id=opp_id,
                deck_id=opp_deck_id,
                mulligans=None,
                landdrops=None,
                lands=None,
                enough_mana=None,
                enough_gas=None,
                deckplan=None,
                unanswered_threats=None,
                fun_moments=None,
                loss_without_answer=None,
                selfmade_win=None,
                comments=None,
            )
            game_participants.append(opp_part)

        participants_by_game[game_id] = game_participants

    return {
        "deck": deck,
        "owner_participants": owner_participants,
        "games": games,
        "participants_by_game": participants_by_game,
        "players": players,
        "decks": decks,
        "owner_id": owner_id,
        "num_games": num_games,
    }


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=game_history_scenario())
@settings(max_examples=100, deadline=None)
def test_game_history_row_building_preserves_game_data(data):
    """Property 1: For any deck with a set of games and participants,
    build_game_history() SHALL produce a list of game row dicts where:
    - row count equals the number of games the deck participated in
    - each row's `datum` matches the corresponding game's date
    - `is_win` correctly reflects whether the deck's owner is the game winner
    - the `gegner` list contains all opponents (participants whose player_id
      differs from the deck's player_id)
    """
    deck = data["deck"]
    owner_participants = data["owner_participants"]
    games = data["games"]
    participants_by_game = data["participants_by_game"]
    players = data["players"]
    decks = data["decks"]
    owner_id = data["owner_id"]
    num_games = data["num_games"]

    # Call the function under test
    rows = build_game_history(
        deck=deck,
        participants=owner_participants,
        games=games,
        participants_by_game=participants_by_game,
        players=players,
        decks=decks,
    )

    # --- Property: Row count equals number of games the deck participated in ---
    assert len(rows) == num_games, (
        f"Expected {num_games} rows but got {len(rows)}"
    )

    # --- Verify each row ---
    for i, row in enumerate(rows):
        participant = owner_participants[i]
        game_id = participant.game_id
        game = games[game_id]

        # Property: datum matches the game's date
        expected_date = game.date.strftime("%Y-%m-%d")
        assert row["datum"] == expected_date, (
            f"Row {i}: datum '{row['datum']}' != expected '{expected_date}'"
        )

        # Property: is_win correctly reflects whether the owner is the game winner
        expected_is_win = game.winner_id == owner_id
        assert row["is_win"] == expected_is_win, (
            f"Row {i}: is_win {row['is_win']} != expected {expected_is_win} "
            f"(winner_id={game.winner_id}, owner_id={owner_id})"
        )

        # Property: gegner contains all opponents
        all_game_participants = participants_by_game[game_id]
        expected_opponents = [p for p in all_game_participants if p.player_id != owner_id]
        assert len(row["gegner"]) == len(expected_opponents), (
            f"Row {i}: gegner count {len(row['gegner'])} != expected {len(expected_opponents)}"
        )

        # Verify opponent player names are in the gegner list
        expected_opponent_names = {
            players[opp.player_id].name for opp in expected_opponents
        }
        actual_opponent_names = {opp["player_name"] for opp in row["gegner"]}
        assert actual_opponent_names == expected_opponent_names, (
            f"Row {i}: opponent names {actual_opponent_names} != expected {expected_opponent_names}"
        )
