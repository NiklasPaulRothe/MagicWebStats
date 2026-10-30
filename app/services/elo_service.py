"""Deck strength-rating service (power-level model).

Computes a bounded deck *power level* on a fixed 0-1000 scale (centre 500) for a
multiplayer (3-5 player) Commander/EDH context. The number is an estimate of how
strong a deck is, deliberately decoupled from raw winrate: decks are usually
played into favourable matchups, so winrate hovers near even against comparable
decks. What matters is *whom* a deck beats, not how often it wins.

This is the model described in ideas/elo.md. Core rules:

- **One curve, power gap -> expected win share.** Against a reference power the
  deck's expected share of games rises with its rating gap: 25% at an even gap
  (one seat of four), climbing through the mid-range and reaching a wall at
  +/-400 where the lower deck is not expected to win at all. See
  ``expected_share``.

- **Expected = no movement, surprise = movement.** Each game moves a deck by the
  gap between what happened and the curve's expectation, scaled by a settling
  step. Winning when you were expected to, or losing when you were expected to,
  moves you ~nothing; an upset (weak deck wins / strong deck loses) moves you a
  lot, in proportion to how surprising it was.

- **One-sided 400 wall.** The wall only zeroes the *expected* side, never the
  surprise: a deck 400+ above the pod that wins does not move (expected), but a
  deck 400+ below the pod that wins moves up hard (big upset). Symmetrically a
  favourite losing to a far-weaker winner moves down, while an expected loss
  does not move.

- **Asymmetric attribution.** On a **win**, the reference is the *pod power* --
  the strongest deck, blended toward the pod average as the pod tightens (three
  strong decks are harder than one strong plus two irrelevant). On a **loss**,
  the reference is the *winner's rating alone* (you can lose to a strong deck no
  matter what the other seats did).

- **5-game bootstrap.** A deck's first rating is seeded after 5 games from the
  decks it beat / lost to (see ``bootstrap_seed``) rather than the per-game
  update, to avoid the cold-start bias of everyone sitting at 500.

- **Confidence interval.** A snapshot of how settled the score is: widest at the
  gate (5 games), linear to 0 once settled (~30 games). Stored, not a movement
  driver, and not displayed yet.

The scale is friendly to a future Commander *bracket* estimate, but no bracket
logic lives here.
"""

from dataclasses import dataclass


DECK_OWNER_OVERRIDE_PLAYER_ID: int = 24
"""Player ID whose decks are always included in rating calculations
even when played by a different player (community/shared decks)."""


# --- Scale ------------------------------------------------------------------
RATING_MIN: float = 0.0
RATING_MAX: float = 1000.0
RATING_CENTER: float = 500.0
"""Fixed 0-1000 scale; a deck with no information sits at the centre (500)."""

# --- The curve: power gap -> expected win share -----------------------------
# A deck's expected *share of games won* in a pod is a function of its rating
# gap to the reference power (pod power on a win, winner rating on a loss). The
# curve is pinned at an even gap -> EVEN_SHARE (0.25, one seat of four) and
# rises/falls with the gap, reaching ~0 win expectation at -WALL_GAP and
# saturating near its max at +WALL_GAP. Implemented as a logistic in the gap,
# shifted so gap 0 maps to EVEN_SHARE.
EVEN_SHARE: float = 0.25
"""Expected win share at a zero power gap (an even deck wins one pod in four)."""

WALL_GAP: float = 400.0
"""The gap beyond which the lower deck is not expected to win: the one-sided
movement wall (see ``movement``). Also the curve's effective saturation point."""

CURVE_SCALE: float = 230.0
"""Logistic width of the win-share curve, in rating points. Softened from 180
after validation showed the curve was slightly overconfident at the top (strong
decks won a bit less than predicted). Larger = gentler extremes / less
overconfidence. With EVEN_SHARE=0.25 this yields roughly +100 -> ~0.36,
+200 -> ~0.49, +300 -> ~0.62, +400 -> ~0.73. Smaller = steeper / more tier
separation."""

# --- Pod power (win-side reference) -----------------------------------------
POD_BLEND_SCALE: float = 150.0
"""Controls how pod power blends the strongest deck with the pod average. The
blend weight toward the average is ``1 / (1 + spread / POD_BLEND_SCALE)`` where
``spread = max_rating - mean_of_others``: a tight pod (small spread) -> weight
~1 -> pod power ~= the average (every deck matters); a lopsided pod (one giant,
weak rest) -> weight ~0 -> pod power ~= the max (only the big threat counts)."""

# --- Movement ---------------------------------------------------------------
STEP_MAX: float = 110.0
"""Largest rating change a brand-new deck (full step) can take in one game, at
maximum surprise. Shrinks with games via the settling schedule below."""

SETTLE_GAMES: int = 30
"""Games over which the per-game step shrinks from STEP_MAX to STEP_MIN. Matches
the confidence-interval horizon: a deck is settled around here."""

STEP_MIN: float = 12.0
"""Floor for the per-game step. A settled deck still drifts slowly if its real
power changes (living game) but never jumps. Never zero."""

# --- Confidence interval (stored snapshot, not a movement driver) -----------
CI_WIDEST: float = 200.0
"""The +/- confidence interval at the gate (CI_MIN_GAMES games), in points."""

CI_MIN_GAMES: int = 5
"""Games at which a deck becomes rated (the leaderboard gate) and is seeded by
the bootstrap. The confidence interval is at its widest here."""

CI_SETTLED_GAMES: int = 30
"""Games at which the confidence interval reaches 0 (fully settled)."""

# --- Bootstrap --------------------------------------------------------------
BOOTSTRAP_OFFSET: float = 200.0
"""Half the WALL_GAP: a deck is seeded no more than this above the best deck it
beat and no less than this below the worst deck it lost to."""

RECALC_PASSES: int = 4
"""Full-history replays. Pass 1 bootstraps + plays; later passes recompute
against the previous pass's ratings so the result is order-independent and decks
with identical records converge."""


def _clamp(value: float, low: float = RATING_MIN, high: float = RATING_MAX) -> float:
    """Clamp ``value`` into ``[low, high]`` (hard safety bound on the scale)."""
    return max(low, min(high, value))


def expected_share(gap: float) -> float:
    """Expected share of games won given a rating ``gap`` to the reference power.

    ``gap = deck_rating - reference`` (pod power on a win, winner rating on a
    loss). Pinned so ``gap == 0`` returns ``EVEN_SHARE`` (0.25) and the share
    rises toward ~1 as the gap approaches ``+WALL_GAP`` and toward ~0 as it
    approaches ``-WALL_GAP``. Logistic in the gap with width ``CURVE_SCALE``.

    Returns a value in (0, 1).
    """
    # Logistic centred at the gap that would give EVEN_SHARE. We want
    # f(0) = EVEN_SHARE, so shift the logistic by the point where a plain
    # logistic equals EVEN_SHARE.
    import math

    # plain logistic L(x) = 1 / (1 + e^(-x / CURVE_SCALE)); L(0) = 0.5.
    # We want f(0) = EVEN_SHARE, so offset the input so the curve passes through
    # (0, EVEN_SHARE): solve L(offset) = EVEN_SHARE.
    offset = CURVE_SCALE * math.log(EVEN_SHARE / (1 - EVEN_SHARE))
    return 1.0 / (1.0 + math.exp(-(gap + offset) / CURVE_SCALE))


def pod_power(deck_id: int, pod_ratings: dict[int, float]) -> float:
    """Reference power of a pod *from the perspective of a winning deck*.

    Blends the strongest opponent with the pod average: tight pods weight the
    average (all decks matter), lopsided pods weight the max (only the big
    threat counts). ``deck_id`` is excluded -- the reference is the field the
    deck beat, not itself.

    Args:
        deck_id: The winning deck (excluded from the reference field).
        pod_ratings: Mapping deck_id -> rating for every deck in the pod.

    Returns:
        The reference power the winner is measured against.
    """
    others = [r for did, r in pod_ratings.items() if did != deck_id]
    if not others:
        return pod_ratings[deck_id]
    top = max(others)
    mean_field = sum(others) / len(others)   # average of the opposing field
    spread = top - mean_field
    weight_to_mean = 1.0 / (1.0 + spread / POD_BLEND_SCALE)
    return top - weight_to_mean * (top - mean_field)


def _settle_step(games_so_far: int) -> float:
    """Per-game rating step for a deck that already has ``games_so_far`` games.

    Linearly shrinks from ``STEP_MAX`` (new deck) to ``STEP_MIN`` (settled) over
    ``SETTLE_GAMES`` games, then holds at ``STEP_MIN`` -- never zero, so a
    settled deck can still drift if its real power changes.
    """
    if games_so_far >= SETTLE_GAMES:
        return STEP_MIN
    frac = games_so_far / SETTLE_GAMES
    return STEP_MAX - (STEP_MAX - STEP_MIN) * frac


def movement(won: bool, gap: float, step: float) -> float:
    """Rating change for one game, given the result, the power ``gap`` and the
    current ``step`` size.

    ``gap = deck_rating - reference`` where the reference is the pod power on a
    win and the winner's rating on a loss. The change is the surprise
    (actual - expected) times the step. The one-sided ``WALL_GAP`` clamp zeroes
    only the *expected* side:

    - Win with ``gap >= +WALL_GAP`` (expected win): 0 -- you were supposed to.
    - Win with ``gap <= -WALL_GAP`` (huge upset): full credit, no cap.
    - Loss with ``gap <= -WALL_GAP`` (expected loss): 0.
    - Loss with ``gap >= +WALL_GAP`` (surprise loss): full penalty, no cap.

    Returns the signed rating delta (positive = up).
    """
    if won:
        # Expected side: already far above the field and you won -> no info.
        if gap >= WALL_GAP:
            return 0.0
        surprise = 1.0 - expected_share(gap)  # how unexpected the win was
        return step * surprise
    else:
        # Expected side: already far below the winner and you lost -> no info.
        if gap <= -WALL_GAP:
            return 0.0
        # Surprise of the loss: you were expected to win this share, but didn't.
        surprise = expected_share(gap)
        return -step * surprise


@dataclass
class EloResult:
    """Result of a rating recalculation for a single deck.

    Attributes:
        deck_id: The deck's database ID.
        new_rating: The deck's power-level estimate on the 0-1000 scale.
        games_played: The number of valid games the deck participated in.
        rd: The confidence interval half-width (see ``confidence_interval``);
            0 once the deck is settled.
    """

    deck_id: int
    new_rating: float
    games_played: int
    rd: float


def confidence_interval(games_played: int) -> float:
    """+/- confidence interval for a deck's current rating (snapshot statistic).

    Linear ramp from ``CI_WIDEST`` at ``CI_MIN_GAMES`` down to 0 at
    ``CI_SETTLED_GAMES``; 0 beyond. Does NOT move the rating.
    """
    if games_played <= CI_MIN_GAMES:
        return CI_WIDEST
    if games_played >= CI_SETTLED_GAMES:
        return 0.0
    span = CI_SETTLED_GAMES - CI_MIN_GAMES
    remaining = CI_SETTLED_GAMES - games_played
    return CI_WIDEST * remaining / span


def _valid_pod(game, participants, deck_owners, known_ids):
    """Return the list of valid participants for a game, or [] if the pod is not
    ratable (wrong size, too few valid decks).

    A participant is valid if the deck's owner matches the participant's player,
    or the owner is the community-override player.
    """
    if len(participants) < 3 or len(participants) > 5:
        return []
    valid = []
    for p in participants:
        owner = deck_owners.get(p.deck_id)
        if owner is None:
            continue
        if owner != p.player_id and owner != DECK_OWNER_OVERRIDE_PLAYER_ID:
            continue
        if p.deck_id in known_ids:
            valid.append(p)
    if len(valid) < 2:
        return []
    return valid


def _drop_base_when_mostly_rated(
    entries: list[tuple[float, bool]],
    total_entries: int,
    total_rated: int,
) -> list[float]:
    """Filter bootstrap evidence per the "ignore base-500 opponents" rule.

    ``entries`` are ``(rating, is_rated)`` for one side (beaten OR lost_to),
    where ``is_rated`` means the opponent had a real or shortened-estimate value
    (not a pure 500 base fallback). ``total_entries`` / ``total_rated`` are the
    pod-wide counts across BOTH sides, so the >=50% decision is made over the
    whole bootstrap evidence, not per side.

    If at least half of all evidence opponents are rated, drop the unrated
    (pure-base) ones and keep only real signal; otherwise keep everything (we
    do not have enough known opponents to be picky).
    """
    if total_entries and total_rated * 2 >= total_entries:
        kept = [r for (r, is_rated) in entries if is_rated]
        return kept
    return [r for (r, _is_rated) in entries]


def bootstrap_seed(
    deck_id: int,
    beaten: list[tuple[float, bool]],
    lost_to: list[tuple[float, bool]],
) -> float:
    """Seed a deck's rating from the decks it beat and lost to (5-game bootstrap).

    ``beaten`` / ``lost_to`` are lists of ``(rating, is_rated)`` for the
    opponents the deck beat / lost to during its first games. ``is_rated`` is
    True when that opponent had a genuine rating OR a shortened one-layer
    estimate, and False when it was only a flat 500 base fallback (no usable
    signal). Values were resolved by the caller.

    Per ideas/elo.md and the "ignore base evaluations" rule: if at least half of
    all evidence opponents are rated, the pure-base (unrated) opponents are
    dropped so the seed reflects only decks we actually know something about.
    Otherwise all evidence is used.

    Seeding (see ideas/elo.md 1.8), on the filtered evidence:
    - Both sides present: bracket ``[worst_loss - BOOTSTRAP_OFFSET,
      best_win + BOOTSTRAP_OFFSET]``; seed at its midpoint. If inverted
      (best beaten rated above worst lost-to), seed at the midpoint of
      (best_win, worst_loss).
    - Only wins: ``BOOTSTRAP_OFFSET`` above the best deck beaten.
    - Only losses: ``BOOTSTRAP_OFFSET`` below the worst deck lost to.
    - Neither: the centre.
    """
    total_entries = len(beaten) + len(lost_to)
    total_rated = sum(1 for _, r in beaten if r) + sum(1 for _, r in lost_to if r)

    beaten_vals = _drop_base_when_mostly_rated(beaten, total_entries, total_rated)
    lost_vals = _drop_base_when_mostly_rated(lost_to, total_entries, total_rated)

    best_win = max(beaten_vals) if beaten_vals else None
    worst_loss = min(lost_vals) if lost_vals else None

    if best_win is not None and worst_loss is not None:
        hi = best_win + BOOTSTRAP_OFFSET      # ceiling implied by wins
        lo = worst_loss - BOOTSTRAP_OFFSET    # floor implied by losses
        if lo <= hi:
            return _clamp((lo + hi) / 2.0)
        # Inverted / contradictory evidence: split the two signals directly.
        return _clamp((best_win + worst_loss) / 2.0)
    if best_win is not None:
        return _clamp(best_win + BOOTSTRAP_OFFSET)
    if worst_loss is not None:
        return _clamp(worst_loss - BOOTSTRAP_OFFSET)
    return RATING_CENTER


def recalculate_all_elo(
    decks: list,
    games: list,
    participants_by_game: dict[int, list],
) -> list[EloResult]:
    """Recalculate power-level ratings for all decks across all games.

    Processes games chronologically. The first ``CI_MIN_GAMES`` valid games a
    deck plays are collected and used to *bootstrap* its starting rating (via
    ``bootstrap_seed``) at the moment it reaches the gate; before that the deck
    contributes to opponents as the centre but is not itself updated by the
    per-game rule. From the gate onward the deck moves by the surprise rule
    (``movement``), with the win/loss attribution and one-sided wall.

    The whole history is replayed ``RECALC_PASSES`` times: later passes recompute
    against the previous pass's final ratings, which removes within-history order
    dependence and lets equal records converge.

    A deck's participant is valid if the deck's owner matches the participant's
    player, or the owner is ``DECK_OWNER_OVERRIDE_PLAYER_ID``. Pods outside 3-5
    participants, or with fewer than 2 valid decks, are skipped.

    Returns one ``EloResult`` per deck (rating, games_played, confidence
    interval). The caller persists and applies the min-games gate.
    """
    deck_owners: dict[int, int] = {deck.id: deck.player_id for deck in decks}
    known_ids = set(deck_owners)

    # Total valid games per deck (used to know whether an unrated opponent could
    # still reach the 5-game gate; the same every pass). Computed once.
    games_played: dict[int, int] = {deck.id: 0 for deck in decks}
    for game in games:
        valid0 = _valid_pod(game, participants_by_game.get(game.id, []), deck_owners, known_ids)
        for p in valid0:
            games_played[p.deck_id] += 1

    # Carried across passes:
    #   ratings[d]   -- the deck's rating (centre until first seeded).
    #   is_rated[d]  -- True once the deck reached its gate and got a real seed
    #                   (i.e. it has a genuine value, not the base centre).
    #   pre_evidence[d] -- the deck's own pre-gate (beaten, lost_to) evidence
    #                   lists (raw opponent reference values) from the LAST pass,
    #                   so an unrated opponent can be given a shortened one-layer
    #                   estimate from its own games this pass.
    ratings: dict[int, float] = {deck.id: RATING_CENTER for deck in decks}
    is_rated: dict[int, bool] = {deck.id: False for deck in decks}
    pre_evidence: dict[int, tuple[list[float], list[float]]] = {
        deck.id: ([], []) for deck in decks
    }

    for pass_index in range(RECALC_PASSES):
        # Frozen snapshots read during this pass (previous pass's results).
        prior = dict(ratings)
        prior_rated = dict(is_rated)
        prior_evidence = {d: (list(b), list(l)) for d, (b, l) in pre_evidence.items()}

        working: dict[int, float] = {deck.id: RATING_CENTER for deck in decks}
        working_rated: dict[int, bool] = {deck.id: False for deck in decks}
        seen: dict[int, int] = {deck.id: 0 for deck in decks}
        # (beaten, lost_to) evidence as (value, is_rated) tuples, collected this
        # pass and used to seed at the gate; the raw values are also carried to
        # the next pass for shortened estimates.
        pass_beaten: dict[int, list[tuple[float, bool]]] = {deck.id: [] for deck in decks}
        pass_lost: dict[int, list[tuple[float, bool]]] = {deck.id: [] for deck in decks}

        # Rebind the opponent_reference closure to this pass's frozen snapshots.
        def opp_ref(opp_id: int) -> tuple[float, bool]:
            if prior_rated.get(opp_id):
                return prior[opp_id], True
            beaten_prev, lost_prev = prior_evidence.get(opp_id, ([], []))
            if beaten_prev or lost_prev:
                est = bootstrap_seed(
                    opp_id,
                    [(v, True) for v in beaten_prev],
                    [(v, True) for v in lost_prev],
                )
                return est, True
            return RATING_CENTER, False

        for game in games:
            participants = participants_by_game.get(game.id, [])
            valid = _valid_pod(game, participants, deck_owners, known_ids)
            if not valid:
                continue

            winner_pid = game.winner_id
            pod_prior = {p.deck_id: prior[p.deck_id] for p in valid}
            winner_deck_id = None
            for p in valid:
                if p.player_id == winner_pid:
                    winner_deck_id = p.deck_id
                    break

            for p in valid:
                did = p.deck_id
                won = (p.player_id == winner_pid)
                seen[did] += 1
                g = seen[did]

                if g <= CI_MIN_GAMES:
                    # Pre-gate: gather bootstrap evidence, don't move yet.
                    if won:
                        # Beat the whole opposing field -> record the strongest
                        # opponent (by reference value), with its rated flag.
                        refs = [opp_ref(o.deck_id) for o in valid if o.deck_id != did]
                        if refs:
                            pass_beaten[did].append(max(refs, key=lambda t: t[0]))
                    else:
                        # Lost -> the winner's rating is the relevant signal.
                        if winner_deck_id is not None:
                            pass_lost[did].append(opp_ref(winner_deck_id))
                    if g == CI_MIN_GAMES:
                        working[did] = bootstrap_seed(did, pass_beaten[did], pass_lost[did])
                        working_rated[did] = True
                    continue

                # Post-gate: move by the surprise rule.
                rating = working[did]
                step = _settle_step(g - 1)
                if won:
                    reference = pod_power(did, pod_prior)
                    gap = rating - reference
                    delta = movement(True, gap, step)
                else:
                    reference = prior[winner_deck_id] if winner_deck_id is not None else rating
                    gap = rating - reference
                    delta = movement(False, gap, step)
                working[did] = _clamp(rating + delta)

        ratings = working
        is_rated = working_rated
        # Carry this pass's raw evidence values for next pass's estimates.
        pre_evidence = {
            d: ([v for v, _ in pass_beaten[d]], [v for v, _ in pass_lost[d]])
            for d in pre_evidence
        }

    return [
        EloResult(
            deck_id=deck_id,
            new_rating=ratings[deck_id],
            games_played=games_played[deck_id],
            rd=confidence_interval(games_played[deck_id]),
        )
        for deck_id in ratings
    ]
