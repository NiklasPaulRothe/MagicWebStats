"""Formatting helpers for API route handlers.

Each function transforms a typed query result into the JSON-serializable dict
format expected by the frontend. All formatters return flat dicts with snake_case
keys. None values serialize to JSON null (no dash substitution).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.api.queries import (
    DeckDataResult,
    PlayerStatsResult,
    UserDeckArchiveResult,
    UserDeckResult,
)


def format_date_german(d: date | None) -> str:
    """Format a date as non-zero-padded "D.M.YYYY", or return "-" if None.

    Examples:
        date(2024, 3, 5) -> "5.3.2024"
        date(2024, 12, 25) -> "25.12.2024"
        None -> "-"
    """
    if d is None:
        return "-"
    return f"{d.day}.{d.month}.{d.year}"


def format_player_stats(r: PlayerStatsResult) -> dict:
    """Format a PlayerStatsResult into the /api/data JSON structure.

    Returns a flat dict with snake_case keys. No list wrapping.
    """
    return {
        "name": r["name"],
        "games": r["games"],
        "early_sol_ring": r["early_sol_ring"],
        "sol_ring_pct": r["sol_ring_pct"],
        "wins": r["wins"],
        "winrate_pct": r["winrate_pct"],
        "first": r["first"],
        "first_pct": r["first_pct"],
    }


def format_deck_data(r: DeckDataResult) -> dict:
    """Format a DeckDataResult into the /api/deck-data JSON structure.

    Returns a flat dict with snake_case keys. No list wrapping.
    None winrate is preserved as None (serializes to JSON null).
    """
    return {
        "deck_name": r["deck_name"],
        "player_name": r["player_name"],
        "commander": r["commander"],
        "color_identity": r["color_identity"],
        "games": r["games"],
        "wins": r["wins"],
        "winrate_pct": r["winrate_pct"],
        "avg_win_turns": r["avg_win_turns"],
        "win_turns_count": r["win_turns_count"],
        "decklist": r["decklist"],
        "elo": r["elo"],
        "color_imgs": r["color_imgs"],
        "tags": r["tags"],
    }


def format_user_deck(r: UserDeckResult) -> dict:
    """Format a UserDeckResult into the /api/userdecks/<spieler> JSON structure.

    Returns a flat dict with snake_case keys. No list wrapping.
    None winrate and None last_played are preserved as None (JSON null).
    last_played uses German date format (D.M.YYYY) when a date exists.
    """
    last_played_raw: str = format_date_german(r["last_played"])
    last_played: str | None = None if last_played_raw == "-" else last_played_raw

    return {
        "name": r["name"],
        "commander": r["commander"],
        "color_identity": r["color_identity"],
        "games": r["games"],
        "last_played": last_played,
        "wins": r["wins"],
        "winrate_pct": r["winrate_pct"],
        "decklist": r["decklist"],
        "color_imgs": r["color_imgs"],
        "tags": r["tags"],
    }


def format_user_deck_archive(r: UserDeckArchiveResult) -> dict:
    """Format a UserDeckArchiveResult into the /api/userdecks/archive/<spieler> JSON structure.

    Returns a flat dict with snake_case keys.
    """
    winrate: Optional[float] = float(r["winrate_pct"]) if r["winrate_pct"] is not None else None

    return {
        "id": r["id"],
        "name": r["name"],
        "commander": r["commander"],
        "color_imgs": r["color_imgs"],
        "games": r["games"],
        "wins": r["wins"],
        "winrate_pct": winrate,
        "decklist": r["decklist"],
    }
