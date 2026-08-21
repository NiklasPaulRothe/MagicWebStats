"""Formatting helpers for API route handlers.

Each function transforms a typed query result into the JSON-serializable dict
format expected by the frontend. These preserve the existing output structure
(single-element list wrapping for most fields, dash substitution for None values).
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

    All values are wrapped in single-element lists to match existing output.
    """
    return {
        "Name": [r["name"]],
        "Games": [r["games"]],
        "Early Sol Ring": [r["early_sol_ring"]],
        "Sol Ring (in %)": [r["sol_ring_pct"]],
        "Wins": [r["wins"]],
        "Winrate (in %)": [r["winrate_pct"]],
        "First": [r["first"]],
        "First (in %)": [r["first_pct"]],
    }


def format_deck_data(r: DeckDataResult) -> dict:
    """Format a DeckDataResult into the /api/deck-data JSON structure.

    Most values are wrapped in single-element lists. ColorImgs and Tags are
    direct lists (not wrapped). Dash substitution applies to None winrate.
    """
    winrate: float | str = r["winrate_pct"] if r["winrate_pct"] is not None else "-"

    return {
        "Deckname": [r["deck_name"]],
        "Spieler": [r["player_name"]],
        "Commander": [r["commander"]],
        "Farbe": [r["color_identity"]],
        "Spiele": [r["games"]],
        "Siege": [r["wins"]],
        "Winrate (in %)": [winrate],
        "WTurns": [r["avg_win_turns"]],
        "WTurnsCount": [r["win_turns_count"]],
        "Decklist": [r["decklist"]],
        "elo": [r["elo"]],
        "ColorImgs": r["color_imgs"],
        "Tags": r["tags"],
    }


def format_user_deck(r: UserDeckResult) -> dict:
    """Format a UserDeckResult into the /api/userdecks/<spieler> JSON structure.

    Most values are wrapped in single-element lists. ColorImgs and Tags are
    direct lists. Dash substitution applies to None winrate and None last_played.
    """
    winrate: float | str = r["winrate_pct"] if r["winrate_pct"] is not None else "-"
    last_played: str = format_date_german(r["last_played"])

    return {
        "Name": [r["name"]],
        "Commander": [r["commander"]],
        "Color Identity": [r["color_identity"]],
        "Spiele": [r["games"]],
        "Zuletzt gespielt": [last_played],
        "Siege": [r["wins"]],
        "Winrate (in %)": [winrate],
        "Decklist": [r["decklist"]],
        "ColorImgs": r["color_imgs"],
        "Tags": r["tags"],
    }


def format_user_deck_archive(r: UserDeckArchiveResult) -> dict:
    """Format a UserDeckArchiveResult into the /api/userdecks/archive/<spieler> JSON structure.

    Archive endpoint does NOT wrap values in single-element lists — uses direct values.
    """
    winrate: Optional[float] = float(r["winrate_pct"]) if r["winrate_pct"] is not None else None

    return {
        "id": r["id"],
        "Name": r["name"],
        "Commander": r["commander"],
        "ColorImgs": r["color_imgs"],
        "Spiele": r["games"],
        "Siege": r["wins"],
        "Winrate (in %)": winrate,
        "Decklist": r["decklist"],
    }
