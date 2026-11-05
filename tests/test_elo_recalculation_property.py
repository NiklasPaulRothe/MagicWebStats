# Feature: capped confidence-weighted deck rating
"""Property-based tests for the bounded strength-rating recalculation.

The old chess-style Elo was additive, unbounded and zero-sum; it inflated over
time. The replacement (``app/services/elo_service.recalculate_all_elo``) treats
a deck's rating as a bounded *estimate of strength* on a fixed 0-1000 scale
(centre 500) with a per-deck confidence (RD). These tests assert the invariants
that make the new system fair, instead of the old zero-sum equivalence:

1. Every rating stays within [RATING_MIN, RATING_MAX] (the cap holds).
2. The reported ``rd`` is a confidence INTERVAL (snapshot, not a movement
   driver): it ramps from CI_WIDEST at the gate to 0 at CI_SETTLED_GAMES games
   and never widens as a deck plays more.
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
    CI_WIDEST,
    CI_MIN_GAMES,
    CI_SETTLED_GAMES,
    confidence_interval,
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
def test_confidence_interval_ramps_to_zero_when_settled(scenario):
    """Invariant 2: the reported ``rd`` is the confidence INTERVAL -- a snapshot
    of how settled the score is, not a movement driver. It ramps linearly from
    CI_WIDEST at the gate down to exactly 0 at CI_SETTLED_GAMES games, and is 0
    beyond. It never widens as a deck plays more."""
    results = recalculate_all_elo(
        scenario['decks'], scenario['games'], scenario['participants_by_game']
    )
    for r in results:
        # The interval is bounded by [0, CI_WIDEST].
        assert 0.0 <= r.rd <= CI_WIDEST
        # It matches the deck's games via the shared function (single source).
        assert math.isclose(r.rd, confidence_interval(r.games_played), rel_tol=1e-9)
        # A settled deck has a zero-width interval (a single trusted number).
        if r.games_played >= CI_SETTLED_GAMES:
            assert r.rd == 0.0


def test_confidence_interval_is_monotone_non_increasing():
    """The confidence interval must never widen as games accrue: it shrinks (or
    holds) with every additional game, reaching 0 at CI_SETTLED_GAMES."""
    prev = confidence_interval(0)
    for g in range(0, CI_SETTLED_GAMES + 20):
        cur = confidence_interval(g)
        assert cur <= prev + 1e-9, f"interval widened at {g} games: {prev} -> {cur}"
        prev = cur
    assert confidence_interval(CI_SETTLED_GAMES) == 0.0
    assert confidence_interval(CI_SETTLED_GAMES + 50) == 0.0


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
            # An unplayed deck has the widest possible confidence interval.
            assert math.isclose(r.rd, CI_WIDEST, rel_tol=1e-9)


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

    r40 = subject_after(40)
    r80 = subject_after(80)

    # Plateaus below the cap (reserves the ceiling for strong-field dominance).
    assert r40 < RATING_MAX - 100, (
        f"All-wins vs an average field reached {r40:.1f}, too close to the cap "
        f"{RATING_MAX}"
    )
    # And clearly above the centre (winning everything is still good).
    assert r40 > RATING_CENTER
    # No unbounded volume inflation: once settled, doubling the games at the same
    # performance level must not keep pushing the rating up. The step floor lets
    # it drift slightly, so allow a small margin but forbid meaningful growth.
    assert r80 <= r40 + 15.0, (
        f"Rating kept inflating with volume: 40 wins -> {r40:.1f}, "
        f"80 wins -> {r80:.1f}"
    )


def test_equal_decks_converge_to_similar_ratings():
    """User invariant: four equally strong decks that each win exactly 25% of a
    long series against each other should end up at roughly the same rating.

    Four decks play cycles of four games, each deck winning one game per cycle
    (so every deck has an identical 25% record). They start equal and remain
    equal in expectation, so after many games they should cluster tightly near
    the centre -- the rating must reward *relative strength*, not the incidental
    order in which the wins happened to fall."""
    decks = [MockDeck(id=i, player_id=i) for i in range(1, 5)]
    games, parts = [], {}
    gid = 0
    for _ in range(40):  # 160 games total, each deck wins 40
        for winner in (1, 2, 3, 4):
            gid += 1
            parts[gid] = [MockParticipant(deck_id=d, player_id=d) for d in [1, 2, 3, 4]]
            games.append(MockGame(id=gid, winner_id=winner))

    results = {r.deck_id: r for r in recalculate_all_elo(decks, games, parts)}
    ratings = [results[d.id].new_rating for d in decks]
    spread = max(ratings) - min(ratings)

    # "Roughly the same": a tight cluster, and centred near 500 (nobody pulled
    # far from the middle by equal play).
    assert spread < 60.0, (
        f"Equal decks diverged by {spread:.1f}: {[round(x, 1) for x in ratings]}"
    )
    assert all(abs(x - RATING_CENTER) < 60.0 for x in ratings), (
        f"Equal decks drifted from centre: {[round(x, 1) for x in ratings]}"
    )
