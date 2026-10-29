# Feature: capped confidence-weighted deck rating
"""Property-based tests for the bounded strength-rating recalculation.

The old chess-style Elo was additive, unbounded and zero-sum; it inflated over
time. The replacement (``app/services/elo_service.recalculate_all_elo``) treats
a deck's rating as a bounded *estimate of strength* on a fixed 0-1000 scale
(centre 500) with a per-deck confidence (RD). These tests assert the invariants
that make the new system fair, instead of the old zero-sum equivalence:

1. Every rating stays within [RATING_MIN, RATING_MAX] (the cap holds).
2. RD (the internal range / confidence) starts at RD_INITIAL and narrows
   monotonically toward RD_MIN as a deck plays — never widens.
3. The recalculation is deterministic (same input -> same output).
4. games_played only counts valid pods (3-5 participants, >=2 valid decks).
5. Strength-of-schedule asymmetry: winning every game against a *strong* field
   lands a deck higher than winning every game against a *weak* field.
"""

import math

from dataclasses import dataclass

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.services.elo_service import (
    DECK_OWNER_OVERRIDE_PLAYER_ID,
    RATING_MIN,
    RATING_MAX,
    RATING_CENTER,
    RD_INITIAL,
    RD_MIN,
    RD_DECAY,
    recalculate_all_elo,
)


# --- Simple record stand-ins (no DB needed) --------------------------------


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


# --- Hypothesis strategy: a valid multi-game scenario ----------------------


@st.composite
def elo_game_scenario(draw):
    """Generate decks, games and participants resembling real pods.

    - 3-8 players, 3-10 decks (some owned by the override player id 24).
    - 1-6 games, each with 3-5 unique decks.
    - Winner is always one of the pod's participant player_ids.
    """
    num_players = draw(st.integers(min_value=3, max_value=8))
    player_ids = list(range(1, num_players + 1))

    num_decks = draw(st.integers(min_value=3, max_value=10))
    decks = []
    for i in range(num_decks):
        owner = draw(st.sampled_from(player_ids + [DECK_OWNER_OVERRIDE_PLAYER_ID]))
        decks.append(MockDeck(id=i + 1, player_id=owner))

    num_games = draw(st.integers(min_value=1, max_value=6))
    games = []
    participants_by_game = {}

    for game_idx in range(num_games):
        game_id = game_idx + 1
        num_participants = draw(st.integers(min_value=3, max_value=min(5, num_decks)))
        selected_decks = draw(
            st.lists(
                st.sampled_from(decks),
                min_size=num_participants,
                max_size=num_participants,
                unique_by=lambda d: d.id,
            )
        )

        game_participants = []
        participant_player_ids = []
        for deck in selected_decks:
            if draw(st.booleans()):
                pid = deck.player_id
            else:
                pid = draw(st.sampled_from(player_ids))
            game_participants.append(MockParticipant(deck_id=deck.id, player_id=pid))
            participant_player_ids.append(pid)

        winner = draw(st.sampled_from(participant_player_ids))
        games.append(MockGame(id=game_id, winner_id=winner))
        participants_by_game[game_id] = game_participants

    return {'decks': decks, 'games': games, 'participants_by_game': participants_by_game}


# --- Property tests --------------------------------------------------------


@given(scenario=elo_game_scenario())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_ratings_stay_within_bounds(scenario):
    """Invariant 1: no rating ever escapes the 0-1000 scale (the cap holds)."""
    results = recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )
    for r in results:
        assert RATING_MIN <= r.new_rating <= RATING_MAX, (
            f"Deck {r.deck_id} rating {r.new_rating} outside [{RATING_MIN}, {RATING_MAX}]"
        )


@given(scenario=elo_game_scenario())
@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_rd_narrows_monotonically_with_games(scenario):
    """Invariant 2: RD equals RD_INITIAL decayed once per counted game, floored
    at RD_MIN. A deck with more games is never *less* confident (higher RD) than
    one with fewer, and RD never exceeds its starting width."""
    results = recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )
    for r in results:
        # RD is bounded by its start and its floor.
        assert RD_MIN <= r.rd <= RD_INITIAL
        # RD is exactly the geometric decay of the counted games (floored).
        expected_rd = max(RD_MIN, RD_INITIAL * (RD_DECAY ** r.games_played))
        assert math.isclose(r.rd, expected_rd, rel_tol=1e-9), (
            f"Deck {r.deck_id}: rd {r.rd} != expected {expected_rd} "
            f"for {r.games_played} games"
        )


@given(scenario=elo_game_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_recalculation_is_deterministic(scenario):
    """Invariant 3: the recompute is a pure function of its input."""
    a = recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )
    b = recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )
    ma = {r.deck_id: r for r in a}
    mb = {r.deck_id: r for r in b}
    assert ma.keys() == mb.keys()
    for did in ma:
        assert math.isclose(ma[did].new_rating, mb[did].new_rating, rel_tol=1e-12)
        assert math.isclose(ma[did].rd, mb[did].rd, rel_tol=1e-12)
        assert ma[did].games_played == mb[did].games_played


@given(scenario=elo_game_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_unplayed_decks_remain_at_center(scenario):
    """A deck that never appears in a valid pod keeps the seed rating (centre)
    and the initial RD, with zero counted games."""
    played = set()
    for parts in scenario['participants_by_game'].values():
        if 3 <= len(parts) <= 5:
            for p in parts:
                played.add(p.deck_id)

    results = {r.deck_id: r for r in recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )}
    for deck in scenario['decks']:
        r = results[deck.id]
        if r.games_played == 0:
            assert math.isclose(r.new_rating, RATING_CENTER, rel_tol=1e-9)
            assert math.isclose(r.rd, RD_INITIAL, rel_tol=1e-9)


def _establish_field_and_play(opponents_are_strong: bool) -> dict:
    """Shared scenario for the strength-of-schedule tests.

    Two parallel universes, identical except for the opposition's *established*
    strength. Opponents 2/3/4 are first driven strong or weak by farming (or
    being farmed by) external fodder decks 90/91, then the subject (deck 1)
    plays the same fixed 20-game pattern against them, winning the same share in
    both universes. Returns the ``{deck_id: EloResult}`` map.
    """
    decks = [MockDeck(id=i, player_id=i) for i in range(1, 7)]
    decks += [MockDeck(id=90, player_id=90), MockDeck(id=91, player_id=91)]
    games = []
    parts = {}
    gid = 0

    # Phase 1: establish opponent strength via fodder 90/91.
    for _ in range(20):
        for champ in (2, 3, 4):
            gid += 1
            if opponents_are_strong:
                pod, winner = [champ, 90, 91], champ   # champ climbs
            else:
                pod, winner = [champ, 90, 91], 90      # champ sinks
            parts[gid] = [MockParticipant(deck_id=d, player_id=d) for d in pod]
            games.append(MockGame(id=gid, winner_id=winner))

    # Phase 2: subject plays the SAME 20 games vs 2/3/4 in both universes,
    # winning 4 of them (a fixed, identical record).
    winners = [2, 3, 1, 4, 2, 1, 3, 4, 2, 1, 3, 4, 2, 1, 3, 4, 2, 3, 4, 2]
    for w in winners:
        gid += 1
        parts[gid] = [MockParticipant(deck_id=d, player_id=d) for d in [1, 2, 3, 4]]
        games.append(MockGame(id=gid, winner_id=w))

    return {r.deck_id: r for r in recalculate_all_elo(decks, games, parts)}


def test_strength_of_schedule_asymmetry():
    """Invariant 5: the SAME record is worth more against a stronger field.

    With an identical 20-game, 4-win record, the subject ends up rated higher
    when its opponents are established as strong than when they are weak. This
    is the core fairness property the user asked for -- taking games off good
    decks counts for more than taking games off weak ones -- and it holds even
    though the subject's own win/loss sequence is byte-for-byte identical in
    both universes.
    """
    strong = _establish_field_and_play(opponents_are_strong=True)[1].new_rating
    weak = _establish_field_and_play(opponents_are_strong=False)[1].new_rating

    assert strong > weak, (
        f"Identical record vs a strong field ({strong:.1f}) should rate higher "
        f"than vs a weak field ({weak:.1f})"
    )


def test_average_field_winner_plateaus_below_cap():
    """A deck that wins EVERY game against an average (near-centre) field should
    plateau comfortably below the ceiling -- winning a lot against unremarkable
    opposition must not, on its own, reach the top of the scale. Also asserts
    the plateau is volume-independent: 5 wins and 40 wins land at the same
    rating (no inflation from simply playing more)."""
    def subject_after(n_wins: int) -> float:
        decks = [MockDeck(id=i, player_id=i) for i in range(1, 5)]
        games, parts = [], {}
        for gid in range(1, n_wins + 1):
            parts[gid] = [MockParticipant(deck_id=d, player_id=d) for d in [1, 2, 3, 4]]
            games.append(MockGame(id=gid, winner_id=1))
        return {r.deck_id: r for r in recalculate_all_elo(decks, games, parts)}[1].new_rating

    r5 = subject_after(5)
    r40 = subject_after(40)

    # Plateaus below the cap (reserves the ceiling for strong-field dominance).
    assert r40 < RATING_MAX - 100, (
        f"All-wins vs an average field reached {r40:.1f}, too close to the cap "
        f"{RATING_MAX}"
    )
    # And clearly above the centre (winning everything is still good).
    assert r40 > RATING_CENTER
    # Volume-independent: more games at the same performance => same rating.
    assert math.isclose(r5, r40, abs_tol=1.0), (
        f"Plateau drifted with volume: 5 wins -> {r5:.1f}, 40 wins -> {r40:.1f}"
    )
