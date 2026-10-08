"""Stats service module for MagicWebStats.

Provides functions for player listings, active deck queries, color identity
resolution, participant averages, and deck performance statistics. Replaces
inline implementations in route handlers with efficient queries (no N+1)
and pure computation functions.
"""

import logging
import statistics
from collections import Counter, defaultdict

import sqlalchemy as sa
from sqlalchemy import func

from app import db
from app.models import (
    Player, Deck, ColorIdentity, ColorComponent, Color,
    Participant, Game, DeckComponent,
)

logger = logging.getLogger(__name__)


def get_players() -> list[str]:
    """Return all player names ordered alphabetically.

    Executes a single query against the Player table.

    Returns:
        Sorted list of player name strings.
    """
    return [p.name for p in db.session.scalars(sa.select(Player).order_by(Player.name)).all()]


def get_active_decks() -> list[tuple[str, str, str]]:
    """Return (deck_name, commander, player_name) for all active decks.

    Uses a single query with a join to Player, avoiding the N+1 pattern
    of querying each deck's player individually.

    Returns:
        List of (deck_name, commander, player_name) tuples, ordered by commander.
    """
    stmt = (
        sa.select(Deck.name, Deck.commander, Player.name)
        .join(Player, Player.id == Deck.player_id)
        .where(Deck.active == True)  # noqa: E712
        .order_by(Deck.commander)
    )
    rows = db.session.execute(stmt).all()
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
    colorless = db.session.scalar(sa.select(Color).where(Color.name == 'Colorless'))
    colorless_img = colorless.img if colorless and colorless.img else None

    # Fetch all components and colors in bulk
    components = db.session.scalars(sa.select(ColorComponent)).all()
    colors = {c.name: c.img for c in db.session.scalars(sa.select(Color)).all()}

    # Group images by identity
    identity_imgs: dict[str, list[str]] = {}
    for comp in components:
        img = colors.get(comp.color)
        if img:
            identity_imgs.setdefault(comp.color_identity, []).append(img)

    identities = db.session.scalars(sa.select(ColorIdentity)).all()
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
        sa.select(Deck.id)
        .where(Deck.decksite.contains('archidekt'), Deck.active == True)  # noqa: E712
        .scalar_subquery()
    )

    stmt = (
        sa.select(
            DeckComponent.name,
            func.sum(DeckComponent.count).label('total_count')
        )
        .where(
            DeckComponent.card_id.isnot(None),
            DeckComponent.deck_id.in_(active_deck_ids)
        )
        .group_by(DeckComponent.name)
        .having(func.sum(DeckComponent.count) > 0)
    )

    results = db.session.execute(stmt).all()

    return [{'name': name, 'count': int(total)} for name, total in results]


def compute_chart_data(exclude_cedh: bool = True) -> dict:
    """Compute chart data for the index page.

    Queries the database for turn data, first-KO data, final-blow counts,
    and first-KO-by counts, then computes Counter aggregations and statistical
    summaries.

    Parameters:
        exclude_cedh: Whether to exclude cEDH games (default True).

    Returns:
        dict with keys:
            - turn_data: list[dict] — [{"turn": int, "count": int}, ...]
            - ko_turn_data: list[dict] — [{"turn": int, "count": int}, ...]
            - avg_turns: float
            - median_turns: float
            - avg_ko_turns: float
            - median_ko_turns: float
            - final_blow_data: dict[str, int]
            - first_ko_data: dict[str, int]
    """
    # Build base filter for cedh exclusion
    cedh_filter = (Game.cedh != True,) if exclude_cedh else ()  # noqa: E712

    # === Turn Chart Data ===
    turns_stmt = sa.select(Game.turns).where(
        Game.turns.isnot(None),
        *cedh_filter
    )
    turns_list = list(db.session.scalars(turns_stmt).all())

    # Count per turn
    turn_counts = Counter(turns_list)
    sorted_turns = sorted(turn_counts.items())
    turn_data = [{"turn": t, "count": count} for t, count in sorted_turns]

    # === KO Turn Chart Data ===
    ko_turns_stmt = sa.select(Game.first_ko_turn).where(
        Game.first_ko_turn.isnot(None),
        *cedh_filter
    )
    ko_turns_list = list(db.session.scalars(ko_turns_stmt).all())

    # Count per ko_turn
    ko_turn_counts = Counter(ko_turns_list)
    sorted_ko_turns = sorted(ko_turn_counts.items())
    ko_turn_data = [{"turn": t, "count": count} for t, count in sorted_ko_turns]

    # Compute average and median for turns
    avg_turns = round(statistics.mean(turns_list), 2) if turns_list else 0
    median_turns = round(statistics.median(turns_list), 2) if turns_list else 0

    # Compute average and median for ko turns
    avg_ko_turns = round(statistics.mean(ko_turns_list), 2) if ko_turns_list else 0
    median_ko_turns = round(statistics.median(ko_turns_list), 2) if ko_turns_list else 0

    # === Final blow pie chart data ===
    final_blow_stmt = sa.select(Game.final_blow).where(
        Game.final_blow.isnot(None),
        *cedh_filter
    )
    final_blow_list = list(db.session.scalars(final_blow_stmt).all())
    final_blow_data = dict(Counter(final_blow_list))

    # === First KO pie chart data ===
    first_ko_stmt = sa.select(Game.first_ko_by).where(
        Game.first_ko_by.isnot(None),
        *cedh_filter
    )
    first_ko_list = list(db.session.scalars(first_ko_stmt).all())
    first_ko_data = dict(Counter(first_ko_list))

    return {
        "turn_data": turn_data,
        "ko_turn_data": ko_turn_data,
        "avg_turns": avg_turns,
        "median_turns": median_turns,
        "avg_ko_turns": avg_ko_turns,
        "median_ko_turns": median_ko_turns,
        "final_blow_data": final_blow_data,
        "first_ko_data": first_ko_data,
    }


def compute_player_overview(player_id: int) -> dict:
    """Compute overview stats for a player's profile page.

    Returns games, wins, winrate, first count, first percentage,
    winrate by seat, and color usage percentages.

    Args:
        player_id: The Player's database ID.

    Returns:
        Dict with keys:
            - games: total non-cEDH game count
            - wins: total non-cEDH win count
            - winrate: win percentage (float, 1 decimal)
            - first: times this player went first
            - first_pct: first percentage (float, 1 decimal)
            - winrate_by_seat: dict mapping seat number to {games, wins, winrate}
            - color_usage: dict with keys white, blue, black, red, green (percentages)
            - avg_colors: average number of colors across active decks
    """
    from app.viewmodels import ColorUsagePlayer

    # --- Total games & wins (excluding cEDH) ---
    game_ids_stmt = (
        sa.select(Participant.game_id)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    game_ids = list(db.session.scalars(game_ids_stmt).all())
    total_games = len(game_ids)

    if total_games == 0:
        return {
            'games': 0, 'wins': 0, 'winrate': 0.0,
            'first': 0, 'first_pct': 0.0,
            'avg_pod_size': 0.0,
            'winrate_by_seat': {},
            'color_usage': {'white': 0, 'blue': 0, 'black': 0, 'red': 0, 'green': 0},
            'avg_colors': 0.0,
        }

    # Count wins
    wins_stmt = (
        sa.select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == player_id)
        .where(Game.winner_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    wins = db.session.scalar(wins_stmt) or 0
    winrate = round((wins / total_games) * 100, 1) if total_games else 0.0

    # --- First player stats ---
    first_stmt = (
        sa.select(func.count())
        .select_from(Game)
        .where(Game.first_player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
        .where(Game.id.in_(game_ids))
    )
    first_count = db.session.scalar(first_stmt) or 0
    first_pct = round((first_count / total_games) * 100, 1) if total_games else 0.0

    # --- Average pod size (avg participants across this player's games) ---
    total_participants_stmt = (
        sa.select(func.count())
        .select_from(Participant)
        .where(Participant.game_id.in_(game_ids))
    )
    total_participants = db.session.scalar(total_participants_stmt) or 0
    avg_pod_size = round(total_participants / total_games, 1) if total_games else 0.0

    # --- Winrate by seat ---
    seat_stats_stmt = (
        sa.select(
            Participant.seat,
            func.count().label('games'),
            func.sum(sa.case((Game.winner_id == player_id, 1), else_=0)).label('wins'),
        )
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == player_id)
        .where(Participant.seat.isnot(None))
        .where(Game.cedh != True)  # noqa: E712
        .group_by(Participant.seat)
        .order_by(Participant.seat)
    )
    seat_rows = db.session.execute(seat_stats_stmt).all()
    winrate_by_seat = {}
    for row in seat_rows:
        seat_games = row.games
        seat_wins = row.wins
        seat_wr = round((seat_wins / seat_games) * 100, 1) if seat_games else 0.0
        winrate_by_seat[row.seat] = {
            'games': seat_games,
            'wins': seat_wins,
            'winrate': seat_wr,
        }

    # --- Color usage from the database view ---
    color_usage = {'white': 0.0, 'blue': 0.0, 'black': 0.0, 'red': 0.0, 'green': 0.0}
    avg_colors = 0.0

    player_name = db.session.scalar(sa.select(Player.name).where(Player.id == player_id))
    if player_name:
        color_row = db.session.scalar(
            sa.select(ColorUsagePlayer).where(ColorUsagePlayer.Player == player_name)
        )
        if color_row:
            color_usage = {
                'white': round(color_row.white or 0, 1),
                'blue': round(color_row.blue or 0, 1),
                'black': round(color_row.black or 0, 1),
                'red': round(color_row.red or 0, 1),
                'green': round(color_row.green or 0, 1),
            }
            avg_colors = round(color_row.avg_number_of_colors or 0, 1)

    return {
        'games': total_games,
        'wins': wins,
        'winrate': winrate,
        'first': first_count,
        'first_pct': first_pct,
        'avg_pod_size': avg_pod_size,
        'winrate_by_seat': winrate_by_seat,
        'color_usage': color_usage,
        'avg_colors': avg_colors,
    }


def get_recent_games(player_id: int, limit: int = 10) -> list[dict]:
    """Return the player's most recent non-cEDH games, newest first.

    Queries the player's participations joined to Game (excluding cEDH),
    ordered by Game.date DESC then Game.id DESC, limited to ``limit`` rows.
    Pod size is resolved with a single grouped count across the matched
    games to avoid an N+1 pattern.

    Args:
        player_id: The Player's database ID.
        limit: Maximum number of games to return (default 10).

    Returns:
        List of dicts (newest first), each with keys:
            - date: the game's date (datetime.date or None)
            - deck_name: name of the deck the player piloted (str or None)
            - result: 'win' when Game.winner_id == player_id, else 'loss'
            - pod_size: number of participants in that game (int)
            - turns: the game's turn count (int or None)
    """
    stmt = (
        sa.select(
            Game.id.label('game_id'),
            Game.date,
            Game.turns,
            Game.winner_id,
            Deck.name.label('deck_name'),
        )
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .join(Deck, Deck.id == Participant.deck_id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
        .order_by(Game.date.desc(), Game.id.desc())
        .limit(limit)
    )
    rows = db.session.execute(stmt).all()

    if not rows:
        return []

    # Resolve pod sizes for the matched games in a single grouped count.
    game_ids = [row.game_id for row in rows]
    pod_size_stmt = (
        sa.select(Participant.game_id, func.count().label('pod_size'))
        .where(Participant.game_id.in_(game_ids))
        .group_by(Participant.game_id)
    )
    pod_sizes = {gid: size for gid, size in db.session.execute(pod_size_stmt).all()}

    return [
        {
            'date': row.date,
            'deck_name': row.deck_name,
            'result': 'win' if row.winner_id == player_id else 'loss',
            'pod_size': pod_sizes.get(row.game_id, 0),
            'turns': row.turns,
        }
        for row in rows
    ]


def get_head_to_head(player_id: int, min_games: int = 10) -> list[dict]:
    """Return head-to-head records against frequently-faced opponents.

    An opponent is any other player who shared a non-cEDH ``game_id`` with the
    subject player. For each such opponent this computes how many games they
    shared with the subject, how many of those the subject won
    (``Game.winner_id == player_id``), the subject's losses in those games, and
    the subject's winrate. Only opponents with at least ``min_games`` shared
    games are returned.

    Queries are kept efficient (no N+1): one query resolves the subject's
    non-cEDH game ids, and a single grouped aggregation joined to ``Player``
    computes per-opponent counts and names.

    Args:
        player_id: The subject Player's database ID.
        min_games: Minimum shared games for an opponent to be included
            (default 10).

    Returns:
        List of dicts sorted by shared ``games`` descending (ties broken by
        ``opponent_name``), each with keys:
            - opponent_id: the opponent Player's database ID (int)
            - opponent_name: the opponent's name (str)
            - games: number of non-cEDH games shared with the subject (int)
            - wins: games (of those) the subject won (int)
            - losses: games - wins (int)
            - winrate: subject win percentage in shared games (float, 1 decimal)
        Empty list when no opponent meets the ``min_games`` threshold.
    """
    # 1. The subject's non-cEDH game ids.
    game_ids_stmt = (
        sa.select(Participant.game_id)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    game_ids = list(db.session.scalars(game_ids_stmt).all())
    if not game_ids:
        return []

    # 2. Group co-participants (other players) across those games, counting
    #    shared games and the subject's wins in a single aggregation.
    stmt = (
        sa.select(
            Participant.player_id.label('opponent_id'),
            Player.name.label('opponent_name'),
            func.count().label('games'),
            func.sum(
                sa.case((Game.winner_id == player_id, 1), else_=0)
            ).label('wins'),
        )
        .join(Game, Game.id == Participant.game_id)
        .join(Player, Player.id == Participant.player_id)
        .where(Participant.game_id.in_(game_ids))
        .where(Participant.player_id != player_id)
        .group_by(Participant.player_id, Player.name)
        .having(func.count() >= min_games)
        .order_by(func.count().desc(), Player.name)
    )
    rows = db.session.execute(stmt).all()

    result = []
    for row in rows:
        games = row.games
        wins = int(row.wins or 0)
        losses = games - wins
        winrate = round((wins / games) * 100, 1) if games else 0.0
        result.append({
            'opponent_id': row.opponent_id,
            'opponent_name': row.opponent_name,
            'games': games,
            'wins': wins,
            'losses': losses,
            'winrate': winrate,
        })
    return result


def get_deck_highlights(player_id: int, min_games_best: int = 5) -> dict:
    """Return the player's most-played and best-performing decks.

    Groups the player's non-cEDH participations by deck and computes per-deck
    games, wins (``Game.winner_id == player_id``), and winrate. From those:
      - ``most_played``: the deck with the most games (ties broken by higher
        winrate, then deck name).
      - ``best``: the deck with the highest winrate among decks with at least
        ``min_games_best`` games (ties broken by more games, then deck name).
        This threshold avoids rewarding a 100%-on-one-game deck (Req 5.2).

    Both highlights are drawn from the player's non-cEDH games (Req 5.4). The
    aggregation is a single grouped query joined to ``Deck`` (no N+1), mirroring
    the pattern used by ``get_head_to_head``.

    Args:
        player_id: The Player's database ID.
        min_games_best: Minimum games a deck must have to be eligible for the
            ``best`` highlight (default 5).

    Returns:
        Dict with keys ``most_played`` and ``best``. Each value is either None
        (when no qualifying deck exists) or a dict with keys:
            - deck_id: the Deck's database ID (int)
            - name: the deck name (str)
            - commander: the deck's commander (str or None)
            - games: non-cEDH games the player piloted this deck (int)
            - wins: games (of those) the player won (int)
            - winrate: win percentage (float, 1 decimal)
        ``best`` is None when no deck meets the ``min_games_best`` threshold.
    """
    stmt = (
        sa.select(
            Deck.id.label('deck_id'),
            Deck.name.label('name'),
            Deck.commander.label('commander'),
            func.count().label('games'),
            func.sum(
                sa.case((Game.winner_id == player_id, 1), else_=0)
            ).label('wins'),
        )
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .join(Deck, Deck.id == Participant.deck_id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
        .group_by(Deck.id, Deck.name, Deck.commander)
    )
    rows = db.session.execute(stmt).all()

    decks = []
    for row in rows:
        games = row.games
        wins = int(row.wins or 0)
        winrate = round((wins / games) * 100, 1) if games else 0.0
        decks.append({
            'deck_id': row.deck_id,
            'name': row.name,
            'commander': row.commander,
            'games': games,
            'wins': wins,
            'winrate': winrate,
        })

    # Highest rated: the player's active, non-cEDH deck with the top real Elo.
    # elo_rating > 0 excludes NULL and the 0 sentinel the Elo pipeline writes
    # for decks with fewer than 5 games (consistent with get_aggregate_elo).
    hr_row = db.session.execute(
        sa.select(Deck.id, Deck.name, Deck.commander, Deck.elo_rating)
        .where(Deck.player_id == player_id)
        .where(Deck.active == True)  # noqa: E712
        .where(Deck.cedh != True)  # noqa: E712
        .where(Deck.elo_rating > 0)
        .order_by(Deck.elo_rating.desc(), Deck.name)
        .limit(1)
    ).first()
    highest_rated = {
        'deck_id': hr_row.id,
        'name': hr_row.name,
        'commander': hr_row.commander,
        'elo': round(hr_row.elo_rating),
    } if hr_row else None

    if not decks:
        return {'most_played': None, 'best': None, 'highest_rated': highest_rated}

    # Most played: most games, ties broken by higher winrate then name.
    most_played = max(decks, key=lambda d: (d['games'], d['winrate'], _neg_name(d['name'])))

    # Best performing: highest winrate among decks meeting the games threshold,
    # ties broken by more games then name.
    eligible = [d for d in decks if d['games'] >= min_games_best]
    best = max(eligible, key=lambda d: (d['winrate'], d['games'], _neg_name(d['name']))) if eligible else None

    return {'most_played': most_played, 'best': best, 'highest_rated': highest_rated}


def get_win_trend(player_id: int, granularity: str = 'month') -> list[dict]:
    """Return the player's performance bucketed over time for charting.

    Buckets the player's non-cEDH games by period (month, per design) and
    computes games, wins (``Game.winner_id == player_id``), and winrate for each
    bucket. Buckets are returned in chronological order so the series can be fed
    directly to a line chart.

    The subject's game rows (date + whether they won) are fetched in a single
    query joined off ``Participant`` (anchored with ``select_from(Participant)``,
    mirroring the other profile aggregates); bucketing is done in Python so the
    result is identical across database backends (SQLite in tests, Postgres in
    production) without relying on dialect-specific date functions.

    Args:
        player_id: The Player's database ID.
        granularity: Bucket size. Only ``'month'`` is supported (per design);
            any other value currently falls back to monthly buckets.

    Returns:
        List of dicts in chronological order, one per period that has at least
        one game, each with keys:
            - period: the bucket label (``'YYYY-MM'`` for monthly) (str)
            - games: non-cEDH games the player played in that period (int)
            - wins: games (of those) the player won (int)
            - winrate: win percentage (float, 1 decimal)
        Empty list when the player has no non-cEDH games.

    Validates: Requirements 7.1, 7.2, 7.4
    """
    stmt = (
        sa.select(
            Game.date.label('date'),
            sa.case((Game.winner_id == player_id, 1), else_=0).label('won'),
        )
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    rows = db.session.execute(stmt).all()

    if not rows:
        return []

    # Aggregate games/wins per period label. Monthly granularity -> 'YYYY-MM'.
    games_by_period: dict[str, int] = defaultdict(int)
    wins_by_period: dict[str, int] = defaultdict(int)
    for row in rows:
        if row.date is None:
            continue
        label = f"{row.date.year:04d}-{row.date.month:02d}"
        games_by_period[label] += 1
        wins_by_period[label] += int(row.won or 0)

    if not games_by_period:
        return []

    result = []
    for label in sorted(games_by_period):
        games = games_by_period[label]
        wins = wins_by_period[label]
        winrate = round((wins / games) * 100, 1) if games else 0.0
        result.append({
            'period': label,
            'games': games,
            'wins': wins,
            'winrate': winrate,
        })
    return result


def get_aggregate_elo(player_id: int) -> int | None:
    """Return the player's aggregate Elo as the rounded average of deck ratings.

    Averages ``Deck.elo_rating`` over the player's **active**, non-cEDH decks
    that have a rating (``elo_rating IS NOT NULL``), then rounds the result to a
    whole number (Req 8.4). cEDH decks are excluded via the ``Deck.cedh`` flag
    to stay consistent with the rest of the profile (Req 8.2); the ``cedh``
    column is nullable, so ``Deck.cedh != True`` keeps decks whose flag is NULL
    or False.

    The average is computed in a single ``func.avg`` aggregate query (no row
    fetch). ``func.avg`` ignores NULL ratings, but the NULL filter is kept
    explicit so the intent is clear and the behaviour is backend-independent.

    Args:
        player_id: The Player's database ID.

    Returns:
        The rounded average Elo (int) over the player's qualifying decks, or
        ``None`` when the player has no active, non-cEDH, rated decks (Req 8.3).

    Validates: Requirements 8.1, 8.2, 8.3, 8.4
    """
    avg_elo = db.session.scalar(
        sa.select(func.avg(Deck.elo_rating))
        .where(Deck.player_id == player_id)
        .where(Deck.active == True)  # noqa: E712
        .where(Deck.cedh != True)  # noqa: E712
        .where(Deck.elo_rating > 0)  # exclude unrated decks (elo 0 = <5 games) and NULL
    )

    if avg_elo is None:
        return None
    return round(avg_elo)


def get_finisher_stats(player_id: int) -> dict:
    """Return how the player tends to close out the games they win.

    Looks at the games the player **won** (``Game.winner_id == player_id``),
    excluding cEDH (Req 9.3), and surfaces the player's closing style:
      - ``most_common_final_blow``: the most frequent non-empty ``Game.final_blow``
        across those wins (the mode); ``None`` when no win records a final blow.
      - ``fastest_win_turns``: the smallest non-null ``Game.turns`` among those
        wins (the notable extreme of Req 9.2); ``None`` when no win records turns.
      - ``avg_win_turns``: the mean of the non-null ``Game.turns`` among those
        wins, rounded to one decimal; ``None`` when no win records turns.

    All computation is null-safe (Req 9.4): NULL/empty ``final_blow`` values and
    NULL ``turns`` are ignored, and when the player has no wins (or all relevant
    fields are NULL) every value is ``None`` — a neutral empty state — rather
    than raising. ``first_ko_by`` / ``first_ko_turn`` are read as supporting
    signals but only the three documented keys are surfaced for the profile.

    Win rows (final_blow + turns) are fetched in a single query filtered by
    ``Game.winner_id`` (no join needed since the finisher fields live on Game).

    Args:
        player_id: The Player's database ID.

    Returns:
        Dict with keys ``most_common_final_blow`` (str | None),
        ``fastest_win_turns`` (int | None), and ``avg_win_turns`` (float | None).

    Validates: Requirements 9.1, 9.2, 9.3, 9.4
    """
    empty = {
        'most_common_final_blow': None,
        'fastest_win_turns': None,
        'avg_win_turns': None,
    }

    stmt = (
        sa.select(Game.final_blow, Game.turns)
        .where(Game.winner_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    rows = db.session.execute(stmt).all()
    if not rows:
        return empty

    # Most common final blow: ignore NULL/empty strings, then take the mode.
    final_blows = [
        row.final_blow for row in rows
        if row.final_blow is not None and str(row.final_blow).strip() != ''
    ]
    most_common_final_blow = Counter(final_blows).most_common(1)[0][0] if final_blows else None

    # Win-turn extremes: ignore NULL turns.
    win_turns = [row.turns for row in rows if row.turns is not None]
    fastest_win_turns = min(win_turns) if win_turns else None
    avg_win_turns = round(statistics.mean(win_turns), 1) if win_turns else None

    return {
        'most_common_final_blow': most_common_final_blow,
        'fastest_win_turns': fastest_win_turns,
        'avg_win_turns': avg_win_turns,
    }


def _neg_name(name) -> tuple:
    """Sort key helper: makes earlier names rank higher under ``max``.

    ``max`` prefers the lexicographically-later name on ties, so we invert the
    character ordinals to make an alphabetically-earlier name win instead,
    giving a deterministic tie-break. Returns a tuple so ``None`` sorts last.
    """
    if name is None:
        return (1,)
    return (0, tuple(-ord(c) for c in name))


def get_interaction_stats(player_id: int) -> dict:
    """Return the player's interaction profile from their own participations.

    Averages the only two retained playstyle fields (Req 11b.4),
    ``Participant.removal_played`` and ``Participant.targeted_by_removal``,
    across the subject player's own non-cEDH participation rows
    (``Participant.player_id == player_id``, joined to ``Game`` to exclude
    cEDH per Req 11b.2). NULL values are ignored when averaging (Req 11b.1),
    and each field exposes the number of non-null samples that went into its
    average (``n``) alongside the mean (``avg``, rounded to one decimal).

    When every value is NULL — or the player has no non-cEDH games at all —
    the function returns a neutral empty state (Req 11b.3): ``avg`` is ``None``
    and ``n`` is ``0`` for each field, without raising.

    No other single-player-only qualitative fields are read or returned
    (Req 11b.4).

    The subject's participation rows (removal_played + targeted_by_removal)
    are fetched in a single query that anchors ``FROM participants`` and joins
    ``games`` for the cEDH filter.

    Args:
        player_id: The Player's database ID.

    Returns:
        Dict shaped as::

            {
                'removal_played': {'avg': float | None, 'n': int},
                'targeted_by_removal': {'avg': float | None, 'n': int},
            }

    Validates: Requirements 11b.1, 11b.2, 11b.3, 11b.4
    """
    empty_field = {'avg': None, 'n': 0}

    stmt = (
        sa.select(Participant.removal_played, Participant.targeted_by_removal)
        .select_from(Participant)
        .join(Game, Participant.game_id == Game.id)
        .where(Participant.player_id == player_id)
        .where(Game.cedh != True)  # noqa: E712
    )
    rows = db.session.execute(stmt).all()

    if not rows:
        return {
            'removal_played': dict(empty_field),
            'targeted_by_removal': dict(empty_field),
        }

    def summarize(values: list) -> dict:
        non_null = [v for v in values if v is not None]
        if not non_null:
            return {'avg': None, 'n': 0}
        return {'avg': round(statistics.mean(non_null), 1), 'n': len(non_null)}

    return {
        'removal_played': summarize([row.removal_played for row in rows]),
        'targeted_by_removal': summarize([row.targeted_by_removal for row in rows]),
    }


def build_player_profile(player_id: int) -> dict:
    """Build the full profile context dict for a player.

    Orchestrator for the profile page (Req 13.1 — aggregate computations live
    in the services layer). Calls ``compute_player_overview`` plus the per-
    section aggregates (``get_recent_games``, ``get_deck_highlights``,
    ``get_head_to_head``, ``get_win_trend``, ``get_aggregate_elo``,
    ``get_finisher_stats``, ``get_interaction_stats``) and merges them into a
    single context dict keyed by section, following the design's naming:

        {
          'overview':      {...},   # from compute_player_overview
          'recent_games':  [...],
          'highlights':    {...},   # from get_deck_highlights
          'head_to_head':  [...],
          'win_trend':     [...],
          'aggregate_elo': int | None,
          'finishers':     {...},   # from get_finisher_stats
          'interaction':   {...},   # from get_interaction_stats
          'color_usage':   {...},   # mirrored from overview
        }

    All sections exclude cEDH because the underlying sub-functions already do
    (Req 13.3). The ``color_usage`` key mirrors ``overview['color_usage']`` so
    the color chart can read it directly (Req 3.2/3.3).

    Defensive composition: each section call is wrapped so that if one section
    raises, that section falls back to a safe neutral/empty default (the sub-
    function's own documented empty shape), the error is logged, the DB session
    is rolled back (matching the index route's pattern so a failed query doesn't
    poison later ones), and the rest of the profile still builds. One failing
    section never blanks the whole page.

    Args:
        player_id: The Player's database ID.

    Returns:
        The merged profile context dict described above.

    Validates: Requirements 3.1, 3.2, 3.3, 13.1, 13.3
    """
    # Neutral/empty defaults per section — each mirrors the sub-function's own
    # documented empty shape so templates see a consistent structure even when
    # a section fails.
    overview_default = {
        'games': 0, 'wins': 0, 'winrate': 0.0,
        'first': 0, 'first_pct': 0.0,
        'avg_pod_size': 0.0,
        'winrate_by_seat': {},
        'color_usage': {'white': 0, 'blue': 0, 'black': 0, 'red': 0, 'green': 0},
        'avg_colors': 0.0,
    }
    highlights_default = {'most_played': None, 'best': None}
    finishers_default = {
        'most_common_final_blow': None,
        'fastest_win_turns': None,
        'avg_win_turns': None,
    }
    interaction_default = {
        'removal_played': {'avg': None, 'n': 0},
        'targeted_by_removal': {'avg': None, 'n': 0},
    }

    def _section(name, fn, default):
        """Call ``fn`` defensively, returning ``default`` on any failure."""
        try:
            return fn()
        except Exception:
            logger.exception(
                "Failed to build profile section '%s' for player %s", name, player_id
            )
            db.session.rollback()
            return default

    overview = _section(
        'overview', lambda: compute_player_overview(player_id), overview_default
    )

    return {
        'overview': overview,
        'recent_games': _section(
            'recent_games', lambda: get_recent_games(player_id), []
        ),
        'highlights': _section(
            'highlights', lambda: get_deck_highlights(player_id), highlights_default
        ),
        'head_to_head': _section(
            'head_to_head', lambda: get_head_to_head(player_id), []
        ),
        'win_trend': _section(
            'win_trend', lambda: get_win_trend(player_id), []
        ),
        'aggregate_elo': _section(
            'aggregate_elo', lambda: get_aggregate_elo(player_id), None
        ),
        'finishers': _section(
            'finishers', lambda: get_finisher_stats(player_id), finishers_default
        ),
        'interaction': _section(
            'interaction', lambda: get_interaction_stats(player_id), interaction_default
        ),
        # color_usage mirrors the overview section (already computed above); if
        # overview failed it falls back to the neutral color map in its default.
        'color_usage': overview.get('color_usage', overview_default['color_usage']),
    }
