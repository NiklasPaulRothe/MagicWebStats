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
    def test_wraps_values_in_lists(self):
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
            "Name": ["Alice"],
            "Games": [10],
            "Early Sol Ring": [3],
            "Sol Ring (in %)": [30.0],
            "Wins": [4],
            "Winrate (in %)": [40.0],
            "First": [2],
            "First (in %)": [20.0],
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
        assert result["Winrate (in %)"] == [40.0]
        assert result["ColorImgs"] == ["/img/B.svg", "/img/R.svg", "/img/U.svg"]
        assert result["Tags"] == ["combo", "storm"]
        assert result["Deckname"] == ["Storm"]

    def test_none_winrate_becomes_dash(self):
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
        assert result["Winrate (in %)"] == ["-"]


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
        assert result["Zuletzt gespielt"] == ["5.3.2024"]
        assert result["Winrate (in %)"] == [37.5]
        assert result["ColorImgs"] == ["/img/B.svg", "/img/G.svg"]
        assert result["Tags"] == ["tribal"]

    def test_none_winrate_becomes_dash(self):
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
        assert result["Winrate (in %)"] == ["-"]

    def test_none_last_played_becomes_dash(self):
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
        assert result["Zuletzt gespielt"] == ["-"]


class TestFormatUserDeckArchive:
    def test_does_not_wrap_in_lists(self):
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
            "Name": "Old Deck",
            "Commander": "Arcum",
            "ColorImgs": ["/img/U.svg"],
            "Spiele": 10,
            "Siege": 3,
            "Winrate (in %)": 30.0,
            "Decklist": "https://example.com",
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
        assert result["Winrate (in %)"] is None
