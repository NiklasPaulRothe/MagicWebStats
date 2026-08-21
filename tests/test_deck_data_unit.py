"""Unit tests for get_deck_data() in app/api/queries.py.

Verifies that:
- Only active decks are returned
- Game count, win count, winrate, avg_win_turns, win_turns_count are computed correctly
- Commander formatting includes partner when present
- Color images are ordered by color name and exclude NULLs
- Tags are ordered alphabetically
- Results are ordered by commander ascending
- NULL handling for winrate and avg_win_turns when no games/wins
"""

import pytest
from datetime import date

from app.models import (
    Player, Deck, Game, Participant, ColorIdentity,
    Color, ColorComponent, DeckTag,
)
from app.api.queries import get_deck_data


class TestGetDeckData:
    """Tests for the get_deck_data query function."""

    def test_returns_only_active_decks(self, app, db_session):
        """Only active decks should appear in results."""
        with app.app_context():
            # Setup
            ci = ColorIdentity(name="Gruul", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            active_deck = Deck(
                id=1, name="Active Deck", commander="Xenagos",
                player_id=1, active=True, color_identity="Gruul",
            )
            inactive_deck = Deck(
                id=2, name="Inactive Deck", commander="Borborygmos",
                player_id=1, active=False, color_identity="Gruul",
            )
            db_session.add_all([active_deck, inactive_deck])
            db_session.flush()

            results = get_deck_data(db_session)

            assert len(results) == 1
            assert results[0]["deck_name"] == "Active Deck"

    def test_game_count_and_win_count(self, app, db_session):
        """Game count = total participations for deck; win count = games where deck's player won."""
        with app.app_context():
            ci = ColorIdentity(name="Dimir", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Bob")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Test Deck", commander="Anowon",
                player_id=1, active=True, color_identity="Dimir",
            )
            db_session.add(deck)
            db_session.flush()

            # 3 games, player 1 wins 2 of them
            for i in range(1, 4):
                game = Game(id=i, date=date(2024, 6, i), winner_id=1 if i <= 2 else None)
                db_session.add(game)
            db_session.flush()

            for i in range(1, 4):
                part = Participant(game_id=i, player_id=1, deck_id=1)
                db_session.add(part)
            db_session.flush()

            results = get_deck_data(db_session)

            assert len(results) == 1
            assert results[0]["games"] == 3
            assert results[0]["wins"] == 2

    def test_winrate_calculation(self, app, db_session):
        """Winrate = (wins * 100) / games, rounded to 2 decimal places."""
        with app.app_context():
            ci = ColorIdentity(name="Izzet", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Charlie")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Test Deck", commander="Niv-Mizzet",
                player_id=1, active=True, color_identity="Izzet",
            )
            db_session.add(deck)
            db_session.flush()

            # 3 games, player wins 1 => winrate = 33.33%
            for i in range(1, 4):
                game = Game(id=i, date=date(2024, 6, i), winner_id=1 if i == 1 else None)
                db_session.add(game)
            db_session.flush()

            for i in range(1, 4):
                part = Participant(game_id=i, player_id=1, deck_id=1)
                db_session.add(part)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["winrate_pct"] == pytest.approx(33.33, abs=0.01)

    def test_winrate_null_when_no_games(self, app, db_session):
        """Winrate should be None when deck has zero games."""
        with app.app_context():
            ci = ColorIdentity(name="Selesnya", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Diana")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="No Games Deck", commander="Trostani",
                player_id=1, active=True, color_identity="Selesnya",
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["winrate_pct"] is None
            assert results[0]["games"] == 0

    def test_avg_win_turns(self, app, db_session):
        """Average win turns = mean of turns from winning games with non-null turns."""
        with app.app_context():
            ci = ColorIdentity(name="Rakdos", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Eve")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Test Deck", commander="Mogis",
                player_id=1, active=True, color_identity="Rakdos",
            )
            db_session.add(deck)
            db_session.flush()

            # 3 games, all won by player 1, turns: 8, 12, None
            game1 = Game(id=1, date=date(2024, 6, 1), winner_id=1, turns=8)
            game2 = Game(id=2, date=date(2024, 6, 2), winner_id=1, turns=12)
            game3 = Game(id=3, date=date(2024, 6, 3), winner_id=1, turns=None)
            db_session.add_all([game1, game2, game3])
            db_session.flush()

            for i in range(1, 4):
                part = Participant(game_id=i, player_id=1, deck_id=1)
                db_session.add(part)
            db_session.flush()

            results = get_deck_data(db_session)

            # avg of (8, 12) = 10.0
            assert results[0]["avg_win_turns"] == pytest.approx(10.0, abs=0.01)
            assert results[0]["win_turns_count"] == 2

    def test_avg_win_turns_null_when_no_wins(self, app, db_session):
        """avg_win_turns should be None when there are no qualifying wins."""
        with app.app_context():
            ci = ColorIdentity(name="Orzhov", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Frank")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Loser Deck", commander="Athreos",
                player_id=1, active=True, color_identity="Orzhov",
            )
            db_session.add(deck)
            db_session.flush()

            # 2 games, player never wins
            game1 = Game(id=1, date=date(2024, 6, 1), winner_id=None, turns=10)
            game2 = Game(id=2, date=date(2024, 6, 2), winner_id=None, turns=8)
            db_session.add_all([game1, game2])
            db_session.flush()

            for i in range(1, 3):
                part = Participant(game_id=i, player_id=1, deck_id=1)
                db_session.add(part)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["avg_win_turns"] is None
            assert results[0]["win_turns_count"] == 0

    def test_commander_with_partner(self, app, db_session):
        """Commander should be formatted as 'commander + partner' when partner exists."""
        with app.app_context():
            ci = ColorIdentity(name="Esper", amount=3)
            db_session.add(ci)
            player = Player(id=1, name="Grace")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Partner Deck", commander="Thrasios",
                partner="Tymna", player_id=1, active=True, color_identity="Esper",
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["commander"] == "Thrasios + Tymna"

    def test_commander_without_partner(self, app, db_session):
        """Commander without partner should just be the commander name."""
        with app.app_context():
            ci = ColorIdentity(name="Gruul", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Hank")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Solo Deck", commander="Xenagos",
                partner=None, player_id=1, active=True, color_identity="Gruul",
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["commander"] == "Xenagos"

    def test_color_images_ordered_by_name(self, app, db_session):
        """Color images should be ordered by color name, excluding NULL images."""
        with app.app_context():
            ci = ColorIdentity(name="Izzet", amount=2)
            db_session.add(ci)

            # Colors with images (Blue before Red alphabetically)
            blue = Color(name="Blue", abbreviation="U", img="/img/blue.svg")
            red = Color(name="Red", abbreviation="R", img="/img/red.svg")
            no_img = Color(name="Colorless", abbreviation="C", img=None)
            db_session.add_all([blue, red, no_img])

            # Color components for Izzet
            cc1 = ColorComponent(color_identity="Izzet", color="Red")
            cc2 = ColorComponent(color_identity="Izzet", color="Blue")
            db_session.add_all([cc1, cc2])

            player = Player(id=1, name="Ivy")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Izzet Deck", commander="Niv-Mizzet",
                player_id=1, active=True, color_identity="Izzet",
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            # Blue comes before Red alphabetically
            assert results[0]["color_imgs"] == ["/img/blue.svg", "/img/red.svg"]

    def test_tags_ordered_alphabetically(self, app, db_session):
        """Tags should be ordered alphabetically."""
        with app.app_context():
            ci = ColorIdentity(name="Gruul", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Jack")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Tagged Deck", commander="Xenagos",
                player_id=1, active=True, color_identity="Gruul",
            )
            db_session.add(deck)
            db_session.flush()

            # Add tags out of order
            tag1 = DeckTag(deck_id=1, tag="voltron")
            tag2 = DeckTag(deck_id=1, tag="aggro")
            tag3 = DeckTag(deck_id=1, tag="midrange")
            db_session.add_all([tag1, tag2, tag3])
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["tags"] == ["aggro", "midrange", "voltron"]

    def test_ordered_by_commander_ascending(self, app, db_session):
        """Results should be ordered by commander name ascending."""
        with app.app_context():
            ci = ColorIdentity(name="Gruul", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Kate")
            db_session.add(player)
            db_session.flush()

            deck_a = Deck(
                id=1, name="Deck A", commander="Xenagos",
                player_id=1, active=True, color_identity="Gruul",
            )
            deck_b = Deck(
                id=2, name="Deck B", commander="Atarka",
                player_id=1, active=True, color_identity="Gruul",
            )
            deck_c = Deck(
                id=3, name="Deck C", commander="Mogis",
                player_id=1, active=True, color_identity="Gruul",
            )
            db_session.add_all([deck_a, deck_b, deck_c])
            db_session.flush()

            results = get_deck_data(db_session)

            commanders = [r["commander"] for r in results]
            assert commanders == ["Atarka", "Mogis", "Xenagos"]

    def test_includes_deck_name_player_name_fields(self, app, db_session):
        """Results should include deck_name, player_name, color_identity, decklist, elo."""
        with app.app_context():
            ci = ColorIdentity(name="Simic", amount=2)
            db_session.add(ci)
            player = Player(id=1, name="Luna")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="My Deck", commander="Aesi",
                player_id=1, active=True, color_identity="Simic",
                decklist="https://example.com/deck", elo_rating=1600.0,
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["deck_name"] == "My Deck"
            assert results[0]["player_name"] == "Luna"
            assert results[0]["color_identity"] == "Simic"
            assert results[0]["decklist"] == "https://example.com/deck"
            assert results[0]["elo"] == 1600.0

    def test_empty_color_imgs_and_tags(self, app, db_session):
        """When no color components or tags exist, return empty lists."""
        with app.app_context():
            ci = ColorIdentity(name="Colorless", amount=0)
            db_session.add(ci)
            player = Player(id=1, name="Mike")
            db_session.add(player)
            db_session.flush()

            deck = Deck(
                id=1, name="Colorless Deck", commander="Kozilek",
                player_id=1, active=True, color_identity="Colorless",
            )
            db_session.add(deck)
            db_session.flush()

            results = get_deck_data(db_session)

            assert results[0]["color_imgs"] == []
            assert results[0]["tags"] == []
