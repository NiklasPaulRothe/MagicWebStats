"""Query layer for the API endpoints.

Contains TypedDict result schemas and ORM query functions that encapsulate
all database logic. Route handlers call these functions and format the results.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, TypedDict

from sqlalchemy import select, func, case, cast, exists, Numeric, Float, Integer
from sqlalchemy.orm import Session

from app.models import (
    Player,
    Game,
    Participant,
    Deck,
    DeckTag,
    Color,
    ColorComponent,
    ColorIdentity,
)


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _get_color_imgs_for_deck(session: Session, color_identity_name: str) -> list[str]:
    """Query color images for a given color identity, ordered by color name.

    Returns an empty list if no color components with non-null images exist.
    """
    stmt = (
        select(Color.img)
        .select_from(ColorComponent)
        .join(Color, Color.name == ColorComponent.color)
        .where(ColorComponent.color_identity == color_identity_name)
        .where(Color.img.isnot(None))
        .order_by(Color.name)
    )
    rows = session.execute(stmt).scalars().all()
    return list(rows)


def _get_tags_for_deck(session: Session, deck_id: int) -> list[str]:
    """Query tags for a given deck, ordered alphabetically.

    Returns an empty list if no tags exist.
    """
    stmt = (
        select(DeckTag.tag)
        .where(DeckTag.deck_id == deck_id)
        .order_by(DeckTag.tag)
    )
    rows = session.execute(stmt).scalars().all()
    return list(rows)


# ---------------------------------------------------------------------------
# Result Schemas (TypedDicts)
# ---------------------------------------------------------------------------


class PlayerStatsResult(TypedDict):
    name: str
    games: int
    early_sol_ring: int
    sol_ring_pct: float  # rounded to 2 decimal places
    wins: int
    winrate_pct: float  # rounded to 2 decimal places
    first: int
    first_pct: float  # rounded to 2 decimal places


class ColorDataResult(TypedDict):
    name: str
    games: int
    wins: int
    winrate_pct: float  # rounded to 2 decimal places


class DeckDataResult(TypedDict):
    deck_name: str
    player_name: str
    commander: str  # "commander + partner" or just "commander"
    color_identity: str
    games: int
    wins: int
    winrate_pct: Optional[float]  # None when games == 0
    avg_win_turns: Optional[float]  # None when no qualifying wins
    win_turns_count: int
    decklist: Optional[str]
    elo: Optional[float]
    color_imgs: list[str]
    tags: list[str]


class UserDeckResult(TypedDict):
    name: str
    commander: str
    color_identity: str
    games: int
    last_played: Optional[date]  # None if never played
    wins: int
    winrate_pct: Optional[float]  # None when games == 0
    decklist: Optional[str]
    color_imgs: list[str]
    tags: list[str]


class UserDeckArchiveResult(TypedDict):
    id: int
    name: str
    commander: str
    color_identity: str
    games: int
    wins: int
    winrate_pct: Optional[float]
    decklist: Optional[str]
    color_imgs: list[str]


# ---------------------------------------------------------------------------
# Query Functions
# ---------------------------------------------------------------------------


def get_user_decks_archive(session: Session, player_id: int) -> list[UserDeckArchiveResult]:
    """Return archived (inactive) decks for a given player with game/win stats.

    Replicates the raw SQL from the /api/userdecks/archive/<spieler> endpoint.
    Results are ordered by deck name ascending.
    Color images are queried separately per deck for SQLite compatibility.
    """

    # Correlated subquery: game count for this player-deck combination
    game_count = (
        select(func.count())
        .select_from(Participant)
        .where(Participant.deck_id == Deck.id)
        .where(Participant.player_id == player_id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Correlated subquery: win count for this player-deck combination
    win_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Game.winner_id == Participant.player_id)
        .where(Participant.deck_id == Deck.id)
        .where(Participant.player_id == player_id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Winrate: (wins * 100) / NULLIF(games, 0), cast to numeric(10,2)
    # Returns None when games is 0
    winrate = cast(
        cast(win_count, Float) * 100.0
        / func.nullif(cast(game_count, Float), 0),
        Numeric(10, 2),
    )

    # Main query: inactive decks for the specified player
    stmt = (
        select(
            Deck.id,
            Deck.name,
            Deck.commander,
            Deck.color_identity,
            game_count.label("games"),
            win_count.label("wins"),
            winrate.label("winrate_pct"),
            Deck.decklist,
        )
        .where(Deck.player_id == player_id)
        .where(Deck.active == False)  # noqa: E712
        .order_by(Deck.name)
    )

    rows = session.execute(stmt).all()

    results: list[UserDeckArchiveResult] = []
    for row in rows:
        # Query color images separately per deck for SQLite compatibility
        color_imgs_stmt = (
            select(Color.img)
            .select_from(ColorComponent)
            .join(Color, Color.name == ColorComponent.color)
            .where(ColorComponent.color_identity == row.color_identity)
            .where(Color.img.isnot(None))
            .order_by(Color.name)
        )
        color_imgs_rows = session.execute(color_imgs_stmt).scalars().all()
        color_imgs = list(color_imgs_rows) if color_imgs_rows else []

        results.append(
            UserDeckArchiveResult(
                id=row.id,
                name=row.name,
                commander=row.commander,
                color_identity=row.color_identity,
                games=row.games,
                wins=row.wins,
                winrate_pct=float(row.winrate_pct) if row.winrate_pct is not None else None,
                decklist=row.decklist,
                color_imgs=color_imgs,
            )
        )

    return results


def get_player_stats_by_year(session: Session, year: int) -> list[PlayerStatsResult]:
    """Return per-player statistics for a specific calendar year.

    All counts are filtered to games in the specified year.
    Sol ring percentage uses year-filtered non-cEDH games as denominator.
    Only includes players with at least one game in that year.
    Excludes "Precons" player.
    """

    year_filter = func.extract("year", Game.date) == year

    # Game count: participants joined to non-cEDH games in the specified year
    game_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .where(year_filter)
        .correlate(Player)
        .scalar_subquery()
    )

    # Win count: games where winner_id matches, non-cEDH, year-filtered
    win_count = (
        select(func.count())
        .select_from(Game)
        .where(Game.winner_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .where(year_filter)
        .correlate(Player)
        .scalar_subquery()
    )

    # First-player count: games where first_player_id matches, non-cEDH, year-filtered
    first_count = (
        select(func.count())
        .select_from(Game)
        .where(Game.first_player_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .where(year_filter)
        .correlate(Player)
        .scalar_subquery()
    )

    # Early sol ring count: year-filtered (all games, not just non-cEDH)
    early_sol_ring_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Participant.early_sol_ring == True)  # noqa: E712
        .where(year_filter)
        .correlate(Player)
        .scalar_subquery()
    )

    # Sol ring percentage denominator: non-cEDH games in the specified year
    # (same as game_count in the year-filtered version)
    sol_ring_denominator = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .where(year_filter)
        .correlate(Player)
        .scalar_subquery()
    )

    # Sol ring percentage: (early_sol_ring * 100) / NULLIF(denominator, 0), coalesce to 0.00
    sol_ring_pct = cast(
        func.coalesce(
            cast(early_sol_ring_count, Float) * 100.0
            / func.nullif(cast(sol_ring_denominator, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # Winrate: (wins * 100) / NULLIF(games, 0), coalesce to 0.00
    winrate_pct = cast(
        func.coalesce(
            cast(win_count, Float) * 100.0
            / func.nullif(cast(game_count, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # First-player percentage: (first * 100) / NULLIF(games, 0), coalesce to 0.00
    first_pct = cast(
        func.coalesce(
            cast(first_count, Float) * 100.0
            / func.nullif(cast(game_count, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # Activity filter: EXISTS subquery for any game in the specified year
    has_game_in_year = (
        select(Participant.player_id)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(year_filter)
        .correlate(Player)
        .exists()
    )

    # Main query
    stmt = (
        select(
            Player.name,
            game_count.label("games"),
            early_sol_ring_count.label("early_sol_ring"),
            sol_ring_pct.label("sol_ring_pct"),
            win_count.label("wins"),
            winrate_pct.label("winrate_pct"),
            first_count.label("first"),
            first_pct.label("first_pct"),
        )
        .where(Player.name != "Precons")
        .where(has_game_in_year)
    )

    rows = session.execute(stmt).all()

    return [
        PlayerStatsResult(
            name=row.name,
            games=row.games,
            early_sol_ring=row.early_sol_ring,
            sol_ring_pct=float(row.sol_ring_pct),
            wins=row.wins,
            winrate_pct=float(row.winrate_pct),
            first=row.first,
            first_pct=float(row.first_pct),
        )
        for row in rows
    ]


def get_color_data(session: Session) -> list[ColorDataResult]:
    """Compute game counts, win counts and winrate per color identity.

    Excludes games where the participant's deck has cedh=True.
    Excludes color identities with zero qualifying (non-cEDH) games.
    """

    # Correlated subquery: count of non-cEDH games for each color identity
    game_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .join(Deck, Deck.id == Participant.deck_id)
        .where(Deck.color_identity == ColorIdentity.name)
        .where(Deck.cedh == False)
        .correlate(ColorIdentity)
        .scalar_subquery()
    )

    # Correlated subquery: count of wins (non-cEDH) for each color identity
    win_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .join(Deck, Deck.id == Participant.deck_id)
        .where(Game.winner_id == Participant.player_id)
        .where(Deck.color_identity == ColorIdentity.name)
        .where(Deck.cedh == False)
        .correlate(ColorIdentity)
        .scalar_subquery()
    )

    # Winrate: (wins * 100) / games, rounded to 2 decimal places
    winrate = cast(
        cast(win_count, Float) * 100.0 / cast(game_count, Float),
        Numeric(10, 2),
    )

    stmt = (
        select(
            ColorIdentity.name,
            game_count.label("games"),
            win_count.label("wins"),
            winrate.label("winrate_pct"),
        )
        .where(game_count > 0)
    )

    rows = session.execute(stmt).all()

    return [
        ColorDataResult(
            name=row.name,
            games=row.games,
            wins=row.wins,
            winrate_pct=float(row.winrate_pct),
        )
        for row in rows
    ]


def get_deck_data(session: Session) -> list[DeckDataResult]:
    """Return statistics for all active decks.

    Replicates the raw SQL from the /api/deck-data endpoint using ORM constructs.
    Computes per-deck: game count, win count, winrate, average win turns,
    win-turns-count, and resolves color images and tags via post-processing.
    """

    # Correlated subquery: game count (total participations for this deck)
    game_count = (
        select(func.count())
        .select_from(Participant)
        .where(Participant.deck_id == Deck.id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Correlated subquery: win count (games where the deck's player won)
    win_count = (
        select(func.count())
        .select_from(Game)
        .join(Participant, Participant.game_id == Game.id)
        .where(Game.winner_id == Participant.player_id)
        .where(Participant.deck_id == Deck.id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Winrate: (wins * 100) / NULLIF(games, 0), cast to numeric(10,2)
    # Returns NULL when games is 0 (no COALESCE)
    winrate = cast(
        cast(win_count, Float) * 100.0
        / func.nullif(cast(game_count, Float), 0),
        Numeric(10, 2),
    )

    # Average win turns: round(avg(games.turns), 2) for winning games
    avg_win_turns = (
        select(func.round(func.avg(Game.turns), 2))
        .select_from(Game)
        .join(Participant, Participant.game_id == Game.id)
        .where(Game.winner_id == Participant.player_id)
        .where(Participant.deck_id == Deck.id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Win turns count: count of winning games where turns IS NOT NULL
    win_turns_count = (
        select(func.count())
        .select_from(Game)
        .join(Participant, Participant.game_id == Game.id)
        .where(Game.winner_id == Participant.player_id)
        .where(Participant.deck_id == Deck.id)
        .where(Game.turns.isnot(None))
        .correlate(Deck)
        .scalar_subquery()
    )

    # Commander formatted as "commander + partner" when partner exists
    commander_label = Deck.commander + func.coalesce(" + " + Deck.partner, "")

    # Main query: active decks joined with players
    stmt = (
        select(
            Deck.id.label("deck_id"),
            Deck.name.label("deck_name"),
            Player.name.label("player_name"),
            commander_label.label("commander"),
            Deck.color_identity,
            game_count.label("games"),
            win_count.label("wins"),
            winrate.label("winrate_pct"),
            avg_win_turns.label("avg_win_turns"),
            win_turns_count.label("win_turns_count"),
            Deck.decklist,
            Deck.elo_rating.label("elo"),
        )
        .join(Player, Player.id == Deck.player_id)
        .where(Deck.active == True)  # noqa: E712
        .order_by(commander_label)
    )

    rows = session.execute(stmt).all()

    # Post-process: resolve color images and tags for each deck
    results: list[DeckDataResult] = []
    for row in rows:
        color_imgs = _get_color_imgs_for_deck(session, row.color_identity)
        tags = _get_tags_for_deck(session, row.deck_id)

        results.append(
            DeckDataResult(
                deck_name=row.deck_name,
                player_name=row.player_name,
                commander=row.commander,
                color_identity=row.color_identity,
                games=row.games,
                wins=row.wins,
                winrate_pct=float(row.winrate_pct) if row.winrate_pct is not None else None,
                avg_win_turns=float(row.avg_win_turns) if row.avg_win_turns is not None else None,
                win_turns_count=row.win_turns_count,
                decklist=row.decklist,
                elo=row.elo,
                color_imgs=color_imgs,
                tags=tags,
            )
        )

    return results


def get_player_stats(session: Session) -> list[PlayerStatsResult]:
    """Return per-player statistics excluding cEDH for counts, with activity filter.

    Replicates the raw SQL from the /api/data endpoint using ORM constructs.
    """
    activity_cutoff = date.today() - timedelta(days=365)

    # Game count: participants joined to non-cEDH games
    game_count = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .correlate(Player)
        .scalar_subquery()
    )

    # Win count: games where winner_id matches, excluding cEDH
    win_count = (
        select(func.count())
        .select_from(Game)
        .where(Game.winner_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .correlate(Player)
        .scalar_subquery()
    )

    # First-player count: games where first_player_id matches, excluding cEDH
    first_count = (
        select(func.count())
        .select_from(Game)
        .where(Game.first_player_id == Player.id)
        .where(Game.cedh == False)  # noqa: E712
        .correlate(Player)
        .scalar_subquery()
    )

    # Early sol ring count: all games regardless of cEDH
    early_sol_ring_count = (
        select(func.count())
        .select_from(Participant)
        .where(Participant.player_id == Player.id)
        .where(Participant.early_sol_ring == True)  # noqa: E712
        .correlate(Player)
        .scalar_subquery()
    )

    # Sol ring percentage denominator: games after 2024-04-19 (regardless of cEDH)
    sol_ring_denominator = (
        select(func.count())
        .select_from(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Game.date > date(2024, 4, 19))
        .correlate(Player)
        .scalar_subquery()
    )

    # Sol ring percentage: (early_sol_ring * 100) / NULLIF(denominator, 0), coalesce to 0.00
    sol_ring_pct = cast(
        func.coalesce(
            cast(early_sol_ring_count, Float) * 100.0
            / func.nullif(cast(sol_ring_denominator, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # Winrate: (wins * 100) / NULLIF(games, 0), coalesce to 0.00
    winrate_pct = cast(
        func.coalesce(
            cast(win_count, Float) * 100.0
            / func.nullif(cast(game_count, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # First-player percentage: (first * 100) / NULLIF(games, 0), coalesce to 0.00
    first_pct = cast(
        func.coalesce(
            cast(first_count, Float) * 100.0
            / func.nullif(cast(game_count, Float), 0),
            0.0,
        ),
        Numeric(10, 2),
    )

    # Activity filter: EXISTS subquery for games within 365 days
    has_recent_game = (
        select(Participant.player_id)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == Player.id)
        .where(Game.date >= activity_cutoff)
        .correlate(Player)
        .exists()
    )

    # Main query
    stmt = (
        select(
            Player.name,
            game_count.label("games"),
            early_sol_ring_count.label("early_sol_ring"),
            sol_ring_pct.label("sol_ring_pct"),
            win_count.label("wins"),
            winrate_pct.label("winrate_pct"),
            first_count.label("first"),
            first_pct.label("first_pct"),
        )
        .where(Player.name != "Precons")
        .where(has_recent_game)
    )

    rows = session.execute(stmt).all()

    return [
        PlayerStatsResult(
            name=row.name,
            games=row.games,
            early_sol_ring=row.early_sol_ring,
            sol_ring_pct=float(row.sol_ring_pct),
            wins=row.wins,
            winrate_pct=float(row.winrate_pct),
            first=row.first,
            first_pct=float(row.first_pct),
        )
        for row in rows
    ]


def get_game_years(session: Session) -> list[int]:
    """Return distinct years from games where date is not NULL, ordered descending."""

    year_col = cast(func.extract('year', Game.date), Integer).label("year")

    stmt = (
        select(year_col)
        .where(Game.date.isnot(None))
        .distinct()
        .order_by(year_col.desc())
    )

    rows = session.execute(stmt).all()

    return [row.year for row in rows]


def get_user_decks(session: Session, player_id: int) -> list[UserDeckResult]:
    """Return active deck statistics for a specific player.

    Replicates the raw SQL from the /api/userdecks/<spieler> endpoint.
    Computes per-deck: name, commander, color identity, game count, last played
    date, win count, winrate, decklist URL, color images, and tags.

    Results are ordered by deck name ascending.
    """

    # Correlated subquery: game count for this player+deck combination
    game_count = (
        select(func.count())
        .select_from(Participant)
        .where(Participant.deck_id == Deck.id)
        .where(Participant.player_id == player_id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Correlated subquery: last played date (MAX of game dates across ALL
    # participants for that deck, not just this player)
    last_played = (
        select(func.max(Game.date))
        .select_from(Game)
        .join(Participant, Participant.game_id == Game.id)
        .where(Participant.deck_id == Deck.id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Correlated subquery: win count for this player+deck combination
    win_count = (
        select(func.count())
        .select_from(Game)
        .join(Participant, Participant.game_id == Game.id)
        .where(Game.winner_id == Participant.player_id)
        .where(Participant.deck_id == Deck.id)
        .where(Participant.player_id == player_id)
        .correlate(Deck)
        .scalar_subquery()
    )

    # Winrate: (wins * 100) / NULLIF(games, 0), cast to numeric(10,2)
    # Returns NULL when games is 0 (no COALESCE — per requirement 4.4)
    winrate = cast(
        cast(win_count, Float) * 100.0
        / func.nullif(cast(game_count, Float), 0),
        Numeric(10, 2),
    )

    # Main query: active decks belonging to the specified player
    stmt = (
        select(
            Deck.id.label("deck_id"),
            Deck.name,
            Deck.commander,
            Deck.color_identity,
            game_count.label("games"),
            last_played.label("last_played"),
            win_count.label("wins"),
            winrate.label("winrate_pct"),
            Deck.decklist,
        )
        .where(Deck.player_id == player_id)
        .where(Deck.active == True)  # noqa: E712
        .order_by(Deck.name)
    )

    rows = session.execute(stmt).all()

    # Post-process: resolve color images and tags for each deck
    results: list[UserDeckResult] = []
    for row in rows:
        color_imgs = _get_color_imgs_for_deck(session, row.color_identity)
        tags = _get_tags_for_deck(session, row.deck_id)

        results.append(
            UserDeckResult(
                name=row.name,
                commander=row.commander,
                color_identity=row.color_identity,
                games=row.games,
                last_played=row.last_played,
                wins=row.wins,
                winrate_pct=float(row.winrate_pct) if row.winrate_pct is not None else None,
                decklist=row.decklist,
                color_imgs=color_imgs,
                tags=tags,
            )
        )

    return results
