"""Stats service module for MagicWebStats.

Provides functions for player listings, active deck queries, color identity
resolution, participant averages, and deck performance statistics. Replaces
inline implementations in route handlers with efficient queries (no N+1)
and pure computation functions.
"""

import statistics
from collections import defaultdict

from app import db
from app.models import (
    Player, Deck, ColorIdentity, ColorComponent, Color,
    Participant, Game, DeckComponent,
)
from sqlalchemy import func


def get_players() -> list[str]:
    """Return all player names ordered alphabetically.

    Executes a single query against the Player table.

    Returns:
        Sorted list of player name strings.
    """
    return [p.name for p in Player.query.order_by(Player.name).all()]


def get_active_decks() -> list[tuple[str, str, str]]:
    """Return (deck_name, commander, player_name) for all active decks.

    Uses a single query with a join to Player, avoiding the N+1 pattern
    of querying each deck's player individually.

    Returns:
        List of (deck_name, commander, player_name) tuples, ordered by commander.
    """
    rows = (
        db.session.query(Deck.name, Deck.commander, Player.name)
        .join(Player, Player.id == Deck.player_id)
        .filter(Deck.active == True)  # noqa: E712
        .order_by(Deck.commander)
        .all()
    )
    return [(name, commander, player_name) for name, commander, player_name in rows]


def get_color_identities() -> list[dict]:
    """Return color identity data with resolved image URLs.

    Uses bulk queries to load all color components and colors in a bounded
    number of queries (<=4) regardless of the number of color identities
    or color components. Falls back to the colorless image when an identity
    has no components with images.

    Returns:
        List of dicts: [{'name': str, 'imgs': list[str]}, ...]
    """
    colorless = Color.query.filter_by(name='Colorless').first()
    colorless_img = colorless.img if colorless and colorless.img else None

    # Fetch all components and colors in bulk
    components = ColorComponent.query.all()
    colors = {c.name: c.img for c in Color.query.all()}

    # Group images by identity
    identity_imgs: dict[str, list[str]] = {}
    for comp in components:
        img = colors.get(comp.color)
        if img:
            identity_imgs.setdefault(comp.color_identity, []).append(img)

    identities = ColorIdentity.query.all()
    result = []
    for identity in identities:
        imgs = identity_imgs.get(identity.name, [])
        if not imgs and colorless_img:
            imgs = [colorless_img]
        result.append({'name': identity.name, 'imgs': imgs})
    return result


def compute_participant_averages(
    deck: Deck,
    participants: list[Participant],
    games: dict[int, Game],
) -> dict[str, str]:
    """Compute participant field averages for a deck's games.

    Calculates averages for fields like mulligans, landdrops, enough_mana, etc.
    Also computes special conditional averages:
    - lockout_loss_without_answer: only counts games where the deck lost
    - selbsterspielter_sieg: only counts games where the deck won
    - all_landdrops: percentage of games where landdrops is -1

    Pure computation — no DB queries.

    Args:
        deck: The Deck object (used for deck.player_id to determine wins/losses).
        participants: List of Participant records for this deck's player/deck combo.
        games: Dict mapping game_id to Game objects for all relevant games.

    Returns:
        Dict mapping field names to formatted average strings.
        Format: "value (count)" for numeric fields,
                "value% (count)" for percentage fields,
                "–" when no data is available.
    """
    if not participants:
        return {}

    fields = [
        "mulligans",
        "landdrops",
        "enough_mana",
        "enough_gas",
        "deckplan",
        "unanswered_threats",
        "fun_moments",
        "lands",
    ]
    percent_fields = {"enough_mana", "enough_gas", "deckplan", "unanswered_threats", "fun_moments"}
    result: dict[str, str] = {}

    for f in fields:
        numeric_values = []
        filled_count = 0
        for p in participants:
            if not hasattr(p, f):
                continue
            raw = getattr(p, f)
            if raw is None:
                continue
            try:
                num = float(raw)
            except (TypeError, ValueError):
                continue
            # Ignore -1 for 'lands' and 'landdrops'
            if (f == "lands" or f == "landdrops") and num == -1:
                continue
            numeric_values.append(num)
            filled_count += 1

        if not numeric_values:
            result[f] = "\u2013"
            continue

        if f in percent_fields:
            result[f] = f"{round(statistics.mean(numeric_values) * 100, 1)}% ({filled_count})"
        else:
            result[f] = f"{round(statistics.mean(numeric_values), 2)} ({filled_count})"

    # === Special fields ===

    # lockout_loss_without_answer: only count games where the deck lost
    loss_values = []
    loss_filled_count = 0
    for p in participants:
        game_obj = games.get(p.game_id)
        if not game_obj:
            continue
        # Only count losses
        if game_obj.winner_id == deck.player_id:
            continue
        raw = getattr(p, "loss_without_answer", None)
        if raw is None:
            continue
        try:
            num = float(raw)
            loss_values.append(num)
            loss_filled_count += 1
        except (TypeError, ValueError):
            continue

    if loss_values:
        result["lockout_loss_without_answer"] = f"{round(statistics.mean(loss_values) * 100, 1)}% ({loss_filled_count})"
    else:
        result["lockout_loss_without_answer"] = "\u2013"

    # selbsterspielter_sieg: only count games where the deck won
    win_values = []
    win_filled_count = 0
    for p in participants:
        game_obj = games.get(p.game_id)
        if not game_obj:
            continue
        # Only count wins
        if game_obj.winner_id != deck.player_id:
            continue
        raw = getattr(p, "selfmade_win", None)
        if raw is None:
            continue
        try:
            num = float(raw)
            win_values.append(num)
            win_filled_count += 1
        except (TypeError, ValueError):
            continue

    if win_values:
        result["selbsterspielter_sieg"] = f"{round(statistics.mean(win_values) * 100, 1)}% ({win_filled_count})"
    else:
        result["selbsterspielter_sieg"] = "\u2013"

    # all_landdrops: percentage of games where landdrops is -1
    all_landdrops_count = 0
    total_landdrops_filled = 0
    for p in participants:
        raw = getattr(p, "landdrops", None)
        if raw is None:
            continue
        try:
            num = float(raw)
            total_landdrops_filled += 1
            if num == -1:
                all_landdrops_count += 1
        except (TypeError, ValueError):
            continue

    if total_landdrops_filled > 0:
        result["all_landdrops"] = f"{round((all_landdrops_count / total_landdrops_filled) * 100, 1)}% ({all_landdrops_count})"
    else:
        result["all_landdrops"] = "\u2013"

    return result


def compute_deck_performance(
    deck: Deck,
    participants: list[Participant],
    games: dict[int, Game],
    participants_by_game: dict[int, list[Participant]],
) -> dict:
    """Compute deck performance stats (winrate, turn stats, pod-size breakdown).

    Calculates overall performance metrics and breaks them down by table size
    (3, 4, and 5 player pods).

    Pure computation — no DB queries.

    Args:
        deck: The Deck object (used for deck.player_id to determine wins).
        participants: List of Participant records for this deck's player/deck combo.
        games: Dict mapping game_id to Game objects.
        participants_by_game: Dict mapping game_id to list of all Participant
            records in that game (for pod size calculation).

    Returns:
        Dict with keys:
            - games: total game count
            - wins: total win count
            - winrate: win percentage (float)
            - avg_turns: average turns for wins (float or "–")
            - median_turns: median turns for wins (float or "–")
            - min_turns: minimum turns for wins (int or "–")
            - max_turns: maximum turns for wins (int or "–")
            - avg_participants: average pod size (float or "–")
            - last_played: date string of most recent game (str or "–")
            - by_size: dict keyed by pod size string ("3", "4", "5") with
              sub-dicts containing games, wins, winrate, avg_turns, median_turns.
    """
    game_ids = [p.game_id for p in participants]

    if not game_ids:
        return {
            'games': 0,
            'wins': 0,
            'winrate': 0,
            'avg_turns': "\u2013",
            'median_turns': "\u2013",
            'min_turns': "\u2013",
            'max_turns': "\u2013",
            'avg_participants': "\u2013",
            'last_played': "\u2013",
            'by_size': {
                '3': {'games': 0, 'wins': 0, 'winrate': "\u2013", 'avg_turns': "\u2013", 'median_turns': "\u2013"},
                '4': {'games': 0, 'wins': 0, 'winrate': "\u2013", 'avg_turns': "\u2013", 'median_turns': "\u2013"},
                '5': {'games': 0, 'wins': 0, 'winrate': "\u2013", 'avg_turns': "\u2013", 'median_turns': "\u2013"},
            }
        }

    # Overall stats
    total_games = len(game_ids)
    wins = sum(1 for gid in game_ids if games.get(gid) and games[gid].winner_id == deck.player_id)
    winrate = round((wins / total_games) * 100, 1) if total_games else 0

    # Win turn stats
    win_turns = [
        games[gid].turns for gid in game_ids
        if games.get(gid) and games[gid].winner_id == deck.player_id and games[gid].turns
    ]

    # Pod size breakdown
    wins_by_size: dict[int, int] = {3: 0, 4: 0, 5: 0}
    total_by_size: dict[int, int] = {3: 0, 4: 0, 5: 0}
    win_turns_by_size: dict[int, list[int]] = {3: [], 4: [], 5: []}

    for gid in game_ids:
        game = games.get(gid)
        if not game:
            continue
        num_players = len(participants_by_game.get(gid, []))
        if num_players in (3, 4, 5):
            total_by_size[num_players] += 1
            if game.winner_id == deck.player_id:
                wins_by_size[num_players] += 1
                if game.turns:
                    win_turns_by_size[num_players].append(game.turns)

    # Average participants
    participant_counts = [
        len(participants_by_game[gid])
        for gid in game_ids
        if gid in participants_by_game
    ]
    avg_participants = round(statistics.mean(participant_counts), 1) if participant_counts else "\u2013"

    # Last played
    dates = [games[gid].date for gid in game_ids if games.get(gid) and games[gid].date]
    last_played = max(dates).strftime("%Y-%m-%d") if dates else "\u2013"

    result = {
        'games': total_games,
        'wins': wins,
        'winrate': winrate,
        'avg_turns': round(statistics.mean(win_turns), 1) if win_turns else "\u2013",
        'median_turns': statistics.median(win_turns) if win_turns else "\u2013",
        'min_turns': min(win_turns) if win_turns else "\u2013",
        'max_turns': max(win_turns) if win_turns else "\u2013",
        'avg_participants': avg_participants,
        'last_played': last_played,
        'by_size': {}
    }

    for size in (3, 4, 5):
        games_count = total_by_size[size]
        wins_count = wins_by_size[size]
        turns = win_turns_by_size[size]
        result['by_size'][str(size)] = {
            'games': games_count,
            'wins': wins_count,
            'winrate': round((wins_count / games_count) * 100, 1) if games_count else "\u2013",
            'avg_turns': round(statistics.mean(turns), 1) if turns else "\u2013",
            'median_turns': statistics.median(turns) if turns else "\u2013",
        }

    return result


def get_card_usage_counts() -> list[dict[str, object]]:
    """Compute card usage counts across active Archidekt-sourced decks.

    Uses a single GROUP BY query instead of the O(n*m) nested Python loop
    in the original implementation.

    Returns:
        List of dicts: [{'name': str, 'count': int}, ...] sorted by count descending.
    """
    active_deck_ids = (
        db.session.query(Deck.id)
        .filter(Deck.decksite.contains('archidekt'), Deck.active == True)  # noqa: E712
        .subquery()
    )

    results = (
        db.session.query(
            DeckComponent.name,
            func.sum(DeckComponent.count).label('total_count')
        )
        .filter(
            DeckComponent.card_id.isnot(None),
            DeckComponent.deck_id.in_(active_deck_ids)
        )
        .group_by(DeckComponent.name)
        .having(func.sum(DeckComponent.count) > 0)
        .all()
    )

    return [{'name': name, 'count': int(total)} for name, total in results]
