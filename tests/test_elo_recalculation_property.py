# Feature: service-layer-security-refactor, Property 6: Elo recalculation equivalence
"""Property-based test for Elo recalculation equivalence.

**Validates: Requirements 4.2, 4.4, 17.1, 17.2**

For any set of Deck records, Game records, and Participant records,
`recalculate_all_elo()` SHALL produce the same final Elo rating per deck
as the original inline loop in `calculate_elo()` given the same input data,
using `DECK_OWNER_OVERRIDE_PLAYER_ID` in place of the literal `24`.
"""

import math
import statistics
from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.elo_service import (
    DECK_OWNER_OVERRIDE_PLAYER_ID,
    expected_score,
    expected_multiplayer_score,
    get_game_k_factor,
    recalculate_all_elo,
    EloResult,
)


# --- Simple dataclasses to represent records (no DB needed) ---


@dataclass
class MockDeck:
    id: int
    player_id: int


@dataclass
class MockGame:
    id: int
    winner_id: int


@dataclass
class MockParticipant:
    deck_id: int
    player_id: int


# --- Reference implementation (original inline loop from routes.py) ---


def reference_calculate_elo(decks, games, participants_by_game):
    """Reproduce the original calculate_elo() logic from app/decks/routes.py.

    Uses the literal 24 replaced by DECK_OWNER_OVERRIDE_PLAYER_ID to match
    the requirement that the constant replaces the magic number.
    """
    # Build deck ownership lookup (mirrors Deck.query.get(p.deck_id).player_id)
    deck_owners = {deck.id: deck.player_id for deck in decks}

    elo_ratings = {deck.id: {'elo_rating': 1500.0, 'games_played': 0} for deck in decks}

    for game in games:
        participants = participants_by_game.get(game.id, [])
        if len(participants) < 3 or len(participants) > 5:
            continue

        deck_ratings = {}
        valid_participants = []
        for p in participants:
            deck_player = deck_owners.get(p.deck_id)
            if deck_player is None:
                continue
            if deck_player != p.player_id and deck_player != DECK_OWNER_OVERRIDE_PLAYER_ID:
                continue
            if p.deck_id in elo_ratings:
                deck_ratings[p.deck_id] = elo_ratings[p.deck_id]['elo_rating']
                valid_participants.append(p)

        if len(deck_ratings) < 2:
            continue

        # Normalize expected scores
        raw_expected = {
            did: expected_multiplayer_score(did, deck_ratings)
            for did in deck_ratings
        }
        total_expected = sum(raw_expected.values())
        normalized_expected = {
            did: raw / total_expected
            for did, raw in raw_expected.items()
        }

        # Single K-factor
        games_played_list = [
            elo_ratings[p.deck_id]['games_played'] for p in valid_participants
        ]
        k = get_game_k_factor(games_played_list)

        # Apply updates
        for participant in valid_participants:
            did = participant.deck_id
            actual_score = 1.0 if game.winner_id == participant.player_id else 0.0

            rating = elo_ratings[did]['elo_rating']
            new_rating = rating + k * (actual_score - normalized_expected[did])

            elo_ratings[did]['elo_rating'] = new_rating
            elo_ratings[did]['games_played'] += 1

    return elo_ratings


# --- Hypothesis strategies ---


@st.composite
def elo_game_scenario(draw):
    """Generate a valid game scenario with decks, games, and participants.

    Constraints:
    - At least 3 decks (to form a valid game)
    - Each game has 3-5 participants drawn from available decks
    - Some decks owned by DECK_OWNER_OVERRIDE_PLAYER_ID (tests the override)
    - Winner is always one of the participants' player_ids
    """
    # Generate 3-8 unique player IDs
    num_players = draw(st.integers(min_value=3, max_value=8))
    player_ids = list(range(1, num_players + 1))

    # Generate 3-10 decks, each owned by a player
    num_decks = draw(st.integers(min_value=3, max_value=10))
    decks = []
    for i in range(num_decks):
        # Some decks owned by the override player ID to test that path
        owner = draw(st.sampled_from(
            player_ids + [DECK_OWNER_OVERRIDE_PLAYER_ID]
        ))
        decks.append(MockDeck(id=i + 1, player_id=owner))

    # Generate 1-6 games
    num_games = draw(st.integers(min_value=1, max_value=6))
    games = []
    participants_by_game = {}

    for game_idx in range(num_games):
        game_id = game_idx + 1

        # Pick 3-5 participants for this game
        num_participants = draw(st.integers(min_value=3, max_value=min(5, num_decks)))
        # Select unique decks for this game
        selected_decks = draw(
            st.lists(
                st.sampled_from(decks),
                min_size=num_participants,
                max_size=num_participants,
                unique_by=lambda d: d.id,
            )
        )

        # Assign player_ids to participants
        game_participants = []
        participant_player_ids = []
        for deck in selected_decks:
            # Most of the time, the participant plays their own deck
            # Sometimes they play someone else's deck (to test the filter)
            if draw(st.booleans()):
                pid = deck.player_id
            else:
                pid = draw(st.sampled_from(player_ids))
            game_participants.append(MockParticipant(deck_id=deck.id, player_id=pid))
            participant_player_ids.append(pid)

        # Winner must be one of the participant player_ids
        winner = draw(st.sampled_from(participant_player_ids))

        games.append(MockGame(id=game_id, winner_id=winner))
        participants_by_game[game_id] = game_participants

    return {'decks': decks, 'games': games, 'participants_by_game': participants_by_game}


# --- Property test ---


@given(scenario=elo_game_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_elo_recalculation_equivalence(scenario):
    """Property 6: Elo recalculation equivalence.

    For any set of Deck records, Game records, and Participant records,
    recalculate_all_elo() SHALL produce the same final Elo rating per deck
    as the original inline loop in calculate_elo() given the same input data,
    using DECK_OWNER_OVERRIDE_PLAYER_ID in place of the literal 24.
    """
    decks = scenario['decks']
    games = scenario['games']
    participants_by_game = scenario['participants_by_game']

    # Run the new service function
    results = recalculate_all_elo(decks, games, participants_by_game)

    # Run the reference implementation
    reference = reference_calculate_elo(decks, games, participants_by_game)

    # Convert results to a comparable dict
    result_map = {r.deck_id: r for r in results}

    # Verify equivalence for every deck
    for deck in decks:
        assert deck.id in result_map, (
            f"Deck {deck.id} missing from recalculate_all_elo() results"
        )
        ref_data = reference[deck.id]
        actual = result_map[deck.id]

        assert math.isclose(actual.new_rating, ref_data['elo_rating'], rel_tol=1e-9), (
            f"Deck {deck.id}: new_rating {actual.new_rating} != reference {ref_data['elo_rating']}"
        )
        assert actual.games_played == ref_data['games_played'], (
            f"Deck {deck.id}: games_played {actual.games_played} != reference {ref_data['games_played']}"
        )
