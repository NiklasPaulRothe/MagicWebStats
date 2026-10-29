"""Deck strength-rating service (capped, confidence-weighted).

Computes a bounded "strength rating" for every deck in a multiplayer
(3-5 player) Commander/EDH context. This replaces the old chess-style Elo,
which was additive and unbounded and therefore inflated over time: a deck
accumulated rating simply by playing many games, and new decks entering at a
fixed seed fed points to established decks.

The new system treats a deck's rating as an *estimate of its strength on a
fixed 0-1000 scale (centred at 500)*, not as an accumulated bank balance:

- **Bounded scale with a soft cap.** Every update includes a gentle pull back
  toward the centre (500) proportional to how far the deck currently sits from
  it. That centring force is what caps both ends: the further out you are, the
  harder it pulls back, so results have to keep justifying your position and no
  amount of extra games lets you drift past what your record supports. Stop
  performing and you regress toward the middle. Points are not conserved or
  created; the rating settles at the equilibrium between your results and the
  centring pull.

- **Opponent-relative performance (strength of schedule).** A deck's expected
  finish in a pod is its averaged pairwise win probability against the pod,
  normalised so the pod sums to 1 (unchanged from the old system). The update
  is driven by ``actual - expected``. Beating a weak field yields a small
  surplus (you were expected to win), so rating gains shrink and plateau below
  the ceiling for an average-only schedule. Taking games off a strong field
  yields a large surplus, pushing you up fast. The asymmetry you want is
  inherent to opponent-relative scoring.

- **Confidence / rating deviation (RD).** Each deck carries its own RD: wide
  for a new deck (few games -> large step size -> heavy swings) and narrowing
  as it plays (settled estimate -> small steps). RD replaces the old
  median-experience K-factor and doubles as the deck's internal *range*
  (e.g. "rating +/- RD"), stored for later use.

The scale is deliberately friendly to a downstream Commander *bracket* estimate
(mapping rating bands to brackets), but no bracket logic lives here.
"""

from dataclasses import dataclass


DECK_OWNER_OVERRIDE_PLAYER_ID: int = 24
"""Player ID whose decks are always included in rating calculations
even when played by a different player (community/shared decks)."""


# --- Scale constants -------------------------------------------------------
RATING_MIN: float = 0.0
RATING_MAX: float = 1000.0
RATING_CENTER: float = 500.0
"""Fixed 0-1000 scale; new decks start at the centre (500)."""

# --- Movement (step-size) constants ----------------------------------------
# These control HOW FAST the rating moves, which is a separate concern from the
# reported confidence interval below. A deck's step size shrinks as it plays
# (new decks swing hard, settled decks drift slowly) but never reaches zero:
# this is a *living game*, so a deck whose real strength shifts (power creep, a
# rework) must always be able to move, just gradually once it is settled.
RD_INITIAL: float = 300.0
"""Internal step scale for a brand-new deck (0 games): wide, so early games
swing heavily. The per-game step scales with ``movement_rd / RD_INITIAL``."""

RD_MIN: float = 45.0
"""Floor for the internal step scale -- NOT a displayed value. Calibrated to
this group's volume (the most-played deck is ~50 games): by ~30 games the step
has essentially reached this floor, so a settled deck still drifts slowly if its
real performance changes but never jumps. A deck never freezes completely."""

RD_DECAY: float = 0.955
"""Per-game shrink of the internal step scale (0 < d < 1). At 0.955 the step
reaches ~RD_MIN by roughly 30 games -- tuned to this group's volume rather than
the hundreds-of-games timescale a slower decay would imply."""

# --- Displayed confidence interval (stored, not a movement driver) ---------
# elo_rd is a *snapshot* statistic: "how settled is this score right now",
# reported as a +/- interval, NOT something that moves the rating. Per the
# design it ramps linearly from its widest at the gate (CI_MIN_GAMES games) down
# to exactly 0 once a deck is settled (CI_SETTLED_GAMES games), and stays 0
# after. "Settled" therefore means a zero-width interval -- a single trusted
# number -- while the rating itself can still drift via the movement rules above.
CI_WIDEST: float = 200.0
"""The +/- confidence interval at the gate (CI_MIN_GAMES games), in rating
points. Cosmetic for now (not displayed); rescale freely later."""

CI_MIN_GAMES: int = 5
"""Games at which a deck becomes rated (the leaderboard gate). The confidence
interval is at its widest (CI_WIDEST) here."""

CI_SETTLED_GAMES: int = 30
"""Games at which the confidence interval reaches 0 (fully settled). Chosen for
this group's volume: a 30-game sample is treated as a trustworthy single value.
Beyond this the interval stays 0 (the rating can still drift, but we no longer
express uncertainty about the current number)."""

# --- Update-strength constants ---------------------------------------------
# The per-game update is   new = rating + k * perf + CENTER_PULL * (CENTER - rating)
# where:
#   perf = (won - normalized_expected) * n / (n - 1)   -- per-seat performance
#          surplus, scaled so a win is ~+1 and a loss ~-1/(n-1) against an even
#          pod; positive when you do better than your rating predicted.
#   k    = K_SCALE * (rd / RD_INITIAL) * edge_damp(rating)   -- step size, large
#          while the deck is new (wide rd) and shrinking as it settles.
#   CENTER_PULL * (CENTER - rating)  -- a small, confidence-INDEPENDENT mean
#          reversion. It does NOT compress the mid-range (it is tiny there), but
#          over many games it (a) cancels the small order-dependent offsets that
#          equal decks would otherwise accumulate from sequential updates, and
#          (b) caps a relentless winner: the pull grows with distance until it
#          balances the per-game gains, so an average-field all-winner plateaus
#          in the upper-middle rather than pinning to 1000.
#
# perf is additionally self-limiting: as a deck climbs, its expected score
# against a fixed field rises, so perf shrinks -- reserving the extremes for
# decks that keep over-performing against *strong* fields.
K_SCALE: float = 120.0
"""Max rating points a brand-new deck (full rd) moves in one game at perf = 1."""

CENTER_PULL: float = 0.035
"""Confidence-independent per-game mean reversion toward the centre. Small, so
the mid-range stays spread out; see the note above for what it buys."""

EDGE_DAMP_WIDTH: float = 150.0
"""Within this many points of either cap, the step size is linearly damped to
0, so no deck can be shoved past the boundary and ratings ease into the extremes
instead of slamming them."""

# --- Fixed-point iteration -------------------------------------------------
RECALC_PASSES: int = 6
"""Number of times the full game history is replayed. Each pass starts from the
previous pass's ratings and a progressively narrower RD (see PASS_RD_ANNEAL), so
later passes compute every deck's expectation against (near-)converged opponent
ratings and merely settle. This makes the result a fixed point that no longer
depends on the within-history ordering of games -- in particular, decks with
identical records converge to (near-)identical ratings."""

PASS_RD_ANNEAL: float = 0.68
"""Per-pass shrink factor for the starting RD: pass p begins at
``RD_INITIAL * PASS_RD_ANNEAL**p`` (floored at RD_MIN). The first pass learns
from a wide RD; refinement passes move progressively less."""


LOGISTIC_SCALE: float = 240.0
"""Divisor in the logistic expected-score curve, the 0-1000-scale analogue of
classic Elo's 400 (which is tuned for a ~0-3000 scale). Smaller = rating gaps
are more decisive, so strength-of-schedule separates decks more sharply: a
~200-point edge here already implies a strong favourite. This sets how much
beating a strong field is worth relative to beating a weak one."""


def expected_score(rating: float, opponent_rating: float) -> float:
    """Pairwise expected score (logistic, same shape as classic Elo).

    Args:
        rating: The deck's current rating.
        opponent_rating: The opponent deck's current rating.

    Returns:
        A float in (0, 1): the probability the deck beats the opponent.
        ``LOGISTIC_SCALE`` (200) replaces classic Elo's 400 because the scale
        is now 0-1000, so a given rating gap stays comparably decisive.
    """
    return 1 / (1 + 10 ** ((opponent_rating - rating) / LOGISTIC_SCALE))


def expected_multiplayer_score(deck_id: int, deck_ratings: dict[int, float]) -> float:
    """Average pairwise expected score against all opponents in a pod.

    Args:
        deck_id: The deck to compute the expected score for.
        deck_ratings: Mapping of deck_id -> current rating for all participants.

    Returns:
        The mean pairwise expected score (unnormalised).
    """
    opponents = {did: r for did, r in deck_ratings.items() if did != deck_id}
    my_rating = deck_ratings[deck_id]
    pairwise_sum = sum(expected_score(my_rating, opp_r) for opp_r in opponents.values())
    return pairwise_sum / len(opponents)


def _clamp(value: float, low: float = RATING_MIN, high: float = RATING_MAX) -> float:
    """Clamp ``value`` into ``[low, high]`` (hard safety bound on the scale).

    The soft cap (centring pull) and edge damping do the real work of keeping
    ratings away from the extremes; this clamp only guarantees the invariant
    ``RATING_MIN <= rating <= RATING_MAX`` can never be violated by numerical
    overshoot.
    """
    return max(low, min(high, value))


def _edge_damp(rating: float) -> float:
    """Step-size multiplier that fades from 1 in the mid-range to 0 at the caps.

    Returns 1.0 while the rating is at least ``EDGE_DAMP_WIDTH`` away from both
    bounds, then falls linearly to 0 at the bound itself. This lets ratings ease
    into the extremes (and never be pushed past them) while leaving the whole
    middle of the scale undamped, so the mid-range keeps its spread.
    """
    distance = min(rating - RATING_MIN, RATING_MAX - rating)
    if distance >= EDGE_DAMP_WIDTH:
        return 1.0
    return max(0.0, distance / EDGE_DAMP_WIDTH)


def confidence_interval(games_played: int) -> float:
    """Return the +/- confidence interval for a deck's current rating.

    This is a *snapshot* statistic describing how settled the score is right
    now -- it does NOT move the rating (the movement rules in
    ``recalculate_all_elo`` do that). It ramps linearly from ``CI_WIDEST`` at
    the gate (``CI_MIN_GAMES`` games) down to exactly ``0`` once the deck is
    settled (``CI_SETTLED_GAMES`` games), and stays 0 beyond that.

    A settled deck therefore has a zero-width interval -- a single trusted
    number -- even though its rating can still drift slowly if its real
    performance changes (a living game never fully freezes a score).

    Args:
        games_played: The deck's count of valid games.

    Returns:
        The half-width of the confidence interval in rating points. Decks below
        ``CI_MIN_GAMES`` return ``CI_WIDEST`` (they are not rated yet anyway);
        decks at or beyond ``CI_SETTLED_GAMES`` return ``0.0``.
    """
    if games_played <= CI_MIN_GAMES:
        return CI_WIDEST
    if games_played >= CI_SETTLED_GAMES:
        return 0.0
    span = CI_SETTLED_GAMES - CI_MIN_GAMES
    remaining = CI_SETTLED_GAMES - games_played
    return CI_WIDEST * remaining / span


@dataclass
class EloResult:
    """Result of a rating recalculation for a single deck.

    Attributes:
        deck_id: The deck's database ID.
        new_rating: The deck's mean strength estimate on the 0-1000 scale.
        games_played: The number of valid games the deck participated in.
        rd: The deck's rating deviation (confidence / internal range). A low RD
            means a settled estimate; a high RD means few games / heavy swings.
    """

    deck_id: int
    new_rating: float
    games_played: int
    rd: float


def recalculate_all_elo(
    decks: list,
    games: list,
    participants_by_game: dict[int, list],
) -> list[EloResult]:
    """Recalculate bounded strength ratings for all decks across all games.

    Replays the full game history ``RECALC_PASSES`` times (a fixed-point
    iteration). Each pass starts from the previous pass's ratings and a
    progressively narrower starting RD (``PASS_RD_ANNEAL``), so later passes
    compute every deck's expectation against (near-)converged opponent ratings
    and merely settle. The benefit is order-independence: the result no longer
    depends on the within-history ordering of games, and decks with identical
    records converge to (near-)identical ratings.

    Within a pass, games are processed in the supplied (chronological) order.
    For each valid pod every participant's normalised expected finish is
    computed, then each deck's rating moves by ``k * perf`` (RD- and
    edge-scaled) plus a small centring pull (see the update note above).

    A deck's participant is valid if:
    - the deck's owner (``player_id``) matches the participant's ``player_id``, OR
    - the deck's owner is ``DECK_OWNER_OVERRIDE_PLAYER_ID`` (shared/community deck).

    Games with fewer than 3 or more than 5 participants are skipped. Games with
    fewer than 2 valid participants after filtering are skipped.

    Args:
        decks: Deck objects with ``.id`` and ``.player_id`` attributes.
        games: Game objects with ``.id`` and ``.winner_id`` attributes, in the
            order they should be processed (chronological).
        participants_by_game: Mapping game_id -> list of participant objects
            with ``.deck_id`` and ``.player_id`` attributes.

    Returns:
        One ``EloResult`` per deck with the final mean rating, games_played and
        the confidence interval ``rd`` (see ``confidence_interval``: the +/-
        half-width of the current score, 0 once the deck is settled at
        ``CI_SETTLED_GAMES`` games -- distinct from the internal movement step
        and from the per-pass annealing RD). The caller persists the results
        (and decides the min-games gate).
    """
    deck_owners: dict[int, int] = {deck.id: deck.player_id for deck in decks}

    # Ratings carried across passes; RD/games are recomputed each pass.
    ratings: dict[int, float] = {deck.id: RATING_CENTER for deck in decks}
    games_played: dict[int, int] = {deck.id: 0 for deck in decks}

    for pass_index in range(RECALC_PASSES):
        # The first pass learns from a wide RD; refinement passes start narrower
        # so they settle toward the fixed point instead of re-introducing noise.
        start_rd = max(RD_MIN, RD_INITIAL * (PASS_RD_ANNEAL ** pass_index))
        rd: dict[int, float] = {deck.id: start_rd for deck in decks}
        games_this_pass: dict[int, int] = {deck.id: 0 for deck in decks}

        for game in games:
            participants = participants_by_game.get(game.id, [])
            if len(participants) < 3 or len(participants) > 5:
                continue

            # Resolve this pod's valid participants and their current ratings.
            deck_ratings: dict[int, float] = {}
            valid_participants = []
            for p in participants:
                deck_owner = deck_owners.get(p.deck_id)
                if deck_owner is None:
                    continue
                if deck_owner != p.player_id and deck_owner != DECK_OWNER_OVERRIDE_PLAYER_ID:
                    continue
                if p.deck_id in ratings:
                    deck_ratings[p.deck_id] = ratings[p.deck_id]
                    valid_participants.append(p)

            if len(deck_ratings) < 2:
                continue

            n = len(deck_ratings)

            # Normalised expected finish for each deck (pod sums to 1). This is
            # the strength-of-schedule signal: a high value means you were
            # expected to win this particular pod.
            raw_expected = {
                did: expected_multiplayer_score(did, deck_ratings)
                for did in deck_ratings
            }
            total_expected = sum(raw_expected.values())
            normalized_expected = {
                did: raw / total_expected
                for did, raw in raw_expected.items()
            }

            for participant in valid_participants:
                did = participant.deck_id
                won = 1.0 if game.winner_id == participant.player_id else 0.0

                rating = ratings[did]

                # Per-seat performance surplus, scaled by n/(n-1) so a win is
                # ~+1 and a loss ~-1/(n-1) against an even pod. Positive when the
                # deck did better than its rating predicted; large when it did so
                # against a strong field (low expectation), small against a weak
                # one -- the strength-of-schedule signal, self-limiting as a deck
                # climbs against a fixed field.
                perf = (won - normalized_expected[did]) * n / (n - 1)

                # Step size: large while the deck is new (wide rd), shrinking as
                # it settles, and damped near the caps so it eases into extremes.
                k = K_SCALE * (rd[did] / RD_INITIAL) * _edge_damp(rating)

                # Small, confidence-independent mean reversion (see update note).
                pull = CENTER_PULL * (RATING_CENTER - rating)

                ratings[did] = _clamp(rating + k * perf + pull)
                rd[did] = max(RD_MIN, rd[did] * RD_DECAY)
                games_this_pass[did] += 1

        games_played = games_this_pass

    return [
        EloResult(
            deck_id=deck_id,
            new_rating=ratings[deck_id],
            games_played=games_played[deck_id],
            rd=confidence_interval(games_played[deck_id]),
        )
        for deck_id in ratings
    ]
