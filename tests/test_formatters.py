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
            "avg_removal_played": 2.5,
            "avg_removal_targeted": 1.5,
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
            "avg_removal_played": 2.5,
            "avg_removal_targeted": 1.5,
        }

    def test_removal_averages_none_preserved(self):
        """When <5 tracked games, removal averages are None (JSON null)."""
        result = format_player_stats({
            "name": "Bob", "games": 3, "early_sol_ring": 0, "sol_ring_pct": 0.0,
            "wins": 1, "winrate_pct": 33.3, "first": 1, "first_pct": 33.3,
            "avg_removal_played": None, "avg_removal_targeted": None,
        })
        assert result["avg_removal_played"] is None
        assert result["avg_removal_targeted"] is None


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
        assert result["last_played_iso"] == "2024-03-05"
        assert result["winrate_pct"] == 37.5
        assert result["color_imgs"] == ["/img/B.svg", "/img/G.svg"]
        assert result["tags"] == ["tribal"]

    def test_card_fields(self):
        result = format_user_deck({
            "deck_id": 3, "name": "Elves", "commander": "Lathril", "color_identity": "BG",
            "games": 8, "last_played": None, "wins": 3, "winrate_pct": 37.5,
            "avg_win_turns": 6.33, "win_turns_count": 3, "decklist": None,
            "image_uri": "https://img/e.jpg", "color_imgs": [], "tags": [],
        })
        assert result["id"] == 3
        assert result["image_uri"] == "https://img/e.jpg"
        assert result["avg_win_turns"] == 6.33
        assert result["win_turns_count"] == 3
        assert result["last_played_iso"] is None

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
            # Card fields default to null/0/[] when the result omits them.
            "tags": [],
            "image_uri": None,
            "avg_win_turns": None,
            "win_turns_count": 0,
            "last_played_iso": None,
        }

    def test_card_fields_passed_through(self):
        result = format_user_deck_archive({
            "id": 7, "name": "Old", "commander": "Cmd", "color_identity": "R",
            "games": 4, "wins": 1, "winrate_pct": 25.0, "decklist": None,
            "color_imgs": [], "tags": ["aggro"], "image_uri": "https://img/x.jpg",
            "avg_win_turns": 7.5, "win_turns_count": 1, "last_played": date(2025, 2, 3),
        })
        assert result["tags"] == ["aggro"]
        assert result["image_uri"] == "https://img/x.jpg"
        assert result["avg_win_turns"] == 7.5
        assert result["win_turns_count"] == 1
        assert result["last_played_iso"] == "2025-02-03"

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
