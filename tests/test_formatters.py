"""Unit tests for app/api/formatters.py formatting helpers."""

from datetime import date

from app.api.formatters import (
    format_date_german,
    format_deck_data,
    format_player_stats,
    format_user_deck,
    format_user_deck_archive,
)


class TestFormatDateGerman:
    def test_single_digit_day_and_month(self):
        assert format_date_german(date(2024, 3, 5)) == "5.3.2024"

    def test_double_digit_day_and_month(self):
        assert format_date_german(date(2024, 12, 25)) == "25.12.2024"

    def test_none_returns_dash(self):
        assert format_date_german(None) == "-"

    def test_first_day_of_year(self):
        assert format_date_german(date(2023, 1, 1)) == "1.1.2023"


class TestFormatPlayerStats:
    def test_returns_flat_dict_with_snake_case_keys(self):
        result = format_player_stats({
            "name": "Alice",
            "games": 10,
            "early_sol_ring": 3,
            "sol_ring_pct": 30.0,
            "wins": 4,
            "winrate_pct": 40.0,
            "first": 2,
            "first_pct": 20.0,
        })
        assert result == {
            "name": "Alice",
            "games": 10,
            "early_sol_ring": 3,
            "sol_ring_pct": 30.0,
            "wins": 4,
            "winrate_pct": 40.0,
            "first": 2,
            "first_pct": 20.0,
        }


class TestFormatDeckData:
    def test_with_valid_winrate(self):
        result = format_deck_data({
            "deck_name": "Storm",
            "player_name": "Bob",
            "commander": "Kess, Dissident Mage",
            "color_identity": "UBR",
            "games": 5,
            "wins": 2,
            "winrate_pct": 40.0,
            "avg_win_turns": 8.5,
            "win_turns_count": 2,
            "decklist": "https://example.com",
            "elo": 1200.0,
            "color_imgs": ["/img/B.svg", "/img/R.svg", "/img/U.svg"],
            "tags": ["combo", "storm"],
        })
        assert result["winrate_pct"] == 40.0
        assert result["color_imgs"] == ["/img/B.svg", "/img/R.svg", "/img/U.svg"]
        assert result["tags"] == ["combo", "storm"]
        assert result["deck_name"] == "Storm"

    def test_none_winrate_becomes_null(self):
        result = format_deck_data({
            "deck_name": "New Deck",
            "player_name": "Bob",
            "commander": "Commander",
            "color_identity": "W",
            "games": 0,
            "wins": 0,
            "winrate_pct": None,
            "avg_win_turns": None,
            "win_turns_count": 0,
            "decklist": None,
            "elo": None,
            "color_imgs": [],
            "tags": [],
        })
        assert result["winrate_pct"] is None


class TestFormatUserDeck:
    def test_with_valid_date_and_winrate(self):
        result = format_user_deck({
            "name": "Elves",
            "commander": "Lathril",
            "color_identity": "BG",
            "games": 8,
            "last_played": date(2024, 3, 5),
            "wins": 3,
            "winrate_pct": 37.5,
            "decklist": "https://example.com",
            "color_imgs": ["/img/B.svg", "/img/G.svg"],
            "tags": ["tribal"],
        })
        assert result["last_played"] == "5.3.2024"
        assert result["winrate_pct"] == 37.5
        assert result["color_imgs"] == ["/img/B.svg", "/img/G.svg"]
        assert result["tags"] == ["tribal"]

    def test_none_winrate_becomes_null(self):
        result = format_user_deck({
            "name": "New Deck",
            "commander": "Commander",
            "color_identity": "W",
            "games": 0,
            "last_played": date(2024, 1, 1),
            "wins": 0,
            "winrate_pct": None,
            "decklist": None,
            "color_imgs": [],
            "tags": [],
        })
        assert result["winrate_pct"] is None

    def test_none_last_played_becomes_null(self):
        result = format_user_deck({
            "name": "New Deck",
            "commander": "Commander",
            "color_identity": "W",
            "games": 5,
            "last_played": None,
            "wins": 2,
            "winrate_pct": 40.0,
            "decklist": None,
            "color_imgs": [],
            "tags": [],
        })
        assert result["last_played"] is None


class TestFormatUserDeckArchive:
    def test_returns_flat_dict_with_snake_case_keys(self):
        result = format_user_deck_archive({
            "id": 42,
            "name": "Old Deck",
            "commander": "Arcum",
            "color_identity": "U",
            "games": 10,
            "wins": 3,
            "winrate_pct": 30.0,
            "decklist": "https://example.com",
            "color_imgs": ["/img/U.svg"],
        })
        assert result == {
            "id": 42,
            "name": "Old Deck",
            "commander": "Arcum",
            "color_imgs": ["/img/U.svg"],
            "games": 10,
            "wins": 3,
            "winrate_pct": 30.0,
            "decklist": "https://example.com",
        }

    def test_none_winrate_stays_none(self):
        """Archive endpoint passes None through (no dash substitution)."""
        result = format_user_deck_archive({
            "id": 1,
            "name": "Deck",
            "commander": "Cmd",
            "color_identity": "W",
            "games": 0,
            "wins": 0,
            "winrate_pct": None,
            "decklist": None,
            "color_imgs": [],
        })
        assert result["winrate_pct"] is None
