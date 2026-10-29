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

# --- Confidence (rating deviation) constants -------------------------------
RD_INITIAL: float = 350.0
"""RD of a brand-new deck: wide, so early games swing heavily."""

RD_MIN: float = 50.0
"""Floor for RD: a fully-settled deck still allows small movement so it can
react to a genuine shift in performance (no deck ever freezes completely)."""

RD_DECAY: float = 0.92
"""Multiplicative narrowing of RD per game played (0 < d < 1). Smaller =
confidence builds faster. RD approaches RD_MIN geometrically with games."""

# --- Update-strength constants ---------------------------------------------
# The per-game update is   new = rating + confidence * (STEP_SCALE * perf
#                                                        + CENTER_PULL * (CENTER - rating))
# where ``perf = actual - normalized_expected`` is the per-seat performance
# surplus (roughly in [-1, +1]) and ``confidence = rd / RD_INITIAL`` in (0, 1].
#
# Because both the push (STEP_SCALE * perf) and the pull (CENTER_PULL * distance)
# carry the same ``confidence`` factor, confidence cancels at equilibrium, so a
# deck with a *fixed* performance level settles around
#       rating_eq = CENTER + (STEP_SCALE / CENTER_PULL) * perf_eq
# regardless of how many games it has played. The ratio STEP_SCALE / CENTER_PULL
# therefore sets the span of the scale that performance can reach, and CENTER_PULL
# alone sets how fast a deck relaxes toward that equilibrium.
#
# perf is self-limiting: as a deck climbs, its expected score against a fixed
# field rises, so perf shrinks -- which is exactly why beating an *average* field
# plateaus well below the ceiling (the caps are reserved for decks that keep
# over-performing against *strong* fields, where expected stays low and perf
# stays large). The hard clamp to [0, 1000] is only a numerical safety net.
STEP_SCALE: float = 260.0
"""Rating points a full-confidence game moves per unit of performance surplus
(``perf``). With CENTER_PULL below, max sustained over-performance settles a
deck in the upper-middle of the scale, not at the cap."""

CENTER_PULL: float = 0.75
"""Per-game relaxation toward the centre, as a fraction of the deck's current
distance from it (scaled by confidence). Larger = stronger soft cap / harder to
reach the extremes and faster regression when a deck stops performing."""


LOGISTIC_SCALE: float = 200.0
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

    The soft cap (centring pull) does the real work of keeping ratings away
    from the extremes; this clamp only guarantees the invariant
    ``RATING_MIN <= rating <= RATING_MAX`` can never be violated by numerical
    overshoot.
    """
    return max(low, min(high, value))


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

    Processes games in chronological order (as supplied). For each valid pod it
    computes every participant's normalised expected finish, then moves each
    deck's rating toward the evidence of this game while applying the centring
    soft cap. Step size is governed by the deck's current RD, which narrows as
    the deck plays.

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
        RD. The caller persists the results (and decides the min-games gate).
    """
    # Initialise every deck at the centre with a wide RD (low confidence).
    state: dict[int, dict[str, float | int]] = {
        deck.id: {'rating': RATING_CENTER, 'rd': RD_INITIAL, 'games_played': 0}
        for deck in decks
    }

    deck_owners: dict[int, int] = {deck.id: deck.player_id for deck in decks}

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
            if p.deck_id in state:
                deck_ratings[p.deck_id] = state[p.deck_id]['rating']
                valid_participants.append(p)

        if len(deck_ratings) < 2:
            continue

        # Normalised expected finish for each deck (pod sums to 1). This is the
        # strength-of-schedule signal: a high value means you were expected to
        # win this particular pod.
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

            rating = state[did]['rating']
            rd = state[did]['rd']

            # Per-seat performance surplus for THIS pod, roughly in [-1, +1]:
            # actual finish (1 win / 0 loss) minus the deck's normalised
            # expectation. Beating a weak field (where you were already expected
            # to win) yields a small surplus; performing against a strong field
            # (low expectation) yields a large one. This is the strength-of-
            # schedule signal, and it shrinks as the deck climbs against a fixed
            # field, which is what makes an average-only schedule plateau.
            perf = won - normalized_expected[did]

            # Step size scales with confidence: a wide RD (new deck) moves far
            # (heavy early swings); a narrow RD (settled deck) barely moves.
            confidence = rd / RD_INITIAL

            # Push from this game's evidence + soft-cap pull toward the centre.
            # Both share the confidence factor, so they cancel at equilibrium
            # (see the STEP_SCALE / CENTER_PULL note above): a deck settles at a
            # rating set by its sustained performance, not by how long it played.
            push = STEP_SCALE * perf
            pull = CENTER_PULL * (RATING_CENTER - rating)
            new_rating = _clamp(rating + confidence * (push + pull))

            # Narrow RD toward its floor as the deck gains a game of evidence.
            new_rd = max(RD_MIN, rd * RD_DECAY)

            state[did]['rating'] = new_rating
            state[did]['rd'] = new_rd
            state[did]['games_played'] += 1

    return [
        EloResult(
            deck_id=deck_id,
            new_rating=values['rating'],
            games_played=values['games_played'],
            rd=values['rd'],
        )
        for deck_id, values in state.items()
    ]
