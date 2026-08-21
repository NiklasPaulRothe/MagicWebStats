# Feature: raw-sql-to-orm, Task 6.1: get_user_decks
"""
Unit tests verifying that `get_user_decks` correctly returns active deck statistics
for a specific player with proper filtering, aggregation, and ordering.

**Validates: Requirements 4.1, 4.2, 4.3, 4.4**
"""

import pytest
from datetime import date

from app.models import (
    Player,
    Deck,
    Game,
    Participant,
    ColorIdentity,
    ColorComponent,
    Color,
    DeckTag,
)
from app.api.queries import get_user_decks


class TestGetUserDecks:
    """Tests for the get_user_decks query function."""

    def test_returns_only_active_decks_for_specified_player(self, app, db_session):
        """Should return only active decks belonging to the specified player."""
        with app.app_context():
            # Setup
            ci = ColorIdentity(name="Azorius", amount=2)
            db_session.add(ci)
            db_session.flush()

            player1 = Player(id=1, name="Alice")
            player2 = Player(id=2, name="Bob")
            db_session.add_all([player1, player2])
            db_session.flush()

            # Alice has 2 active decks and 1 inactive
            deck_active1 = Deck(id=1, name="Deck A", commander="Cmd A",
                                player_id=1, active=True, color_identity="Azorius")
            deck_active2 = Deck(id=2, name="Deck B", commander="Cmd B",
                                player_id=1, active=True, color_identity="Azorius")
            deck_inactive = Deck(id=3, name="Deck C", commander="Cmd C",
                                 player_id=1, active=False, color_identity="Azorius")
            # Bob has 1 active deck
            deck_bob = Deck(id=4, name="Deck D", commander="Cmd D",
                            player_id=2, active=True, color_identity="Azorius")
            db_session.add_all([deck_active1, deck_active2, deck_inactive, deck_bob])
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert len(results) == 2
            names = [r["name"] for r in results]
            assert "Deck A" in names
            assert "Deck B" in names
            assert "Deck C" not in names  # inactive
            assert "Deck D" not in names  # belongs to Bob

    def test_results_ordered_by_deck_name(self, app, db_session):
        """Results should be ordered by deck name ascending."""
        with app.app_context():
            ci = ColorIdentity(name="Gruul", amount=2)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck_z = Deck(id=1, name="Zebra Deck", commander="Cmd Z",
                          player_id=1, active=True, color_identity="Gruul")
            deck_a = Deck(id=2, name="Alpha Deck", commander="Cmd A",
                          player_id=1, active=True, color_identity="Gruul")
            deck_m = Deck(id=3, name="Middle Deck", commander="Cmd M",
                          player_id=1, active=True, color_identity="Gruul")
            db_session.add_all([deck_z, deck_a, deck_m])
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            names = [r["name"] for r in results]
            assert names == ["Alpha Deck", "Middle Deck", "Zebra Deck"]

    def test_game_count_per_player_deck(self, app, db_session):
        """Game count should count only participations for the specific player+deck."""
        with app.app_context():
            ci = ColorIdentity(name="Izzet", amount=2)
            db_session.add(ci)
            db_session.flush()

            player1 = Player(id=1, name="Alice")
            player2 = Player(id=2, name="Bob")
            db_session.add_all([player1, player2])
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Izzet")
            db_session.add(deck)
            db_session.flush()

            # Create 3 games; Alice participates with this deck in 2 of them
            game1 = Game(id=1, date=date(2024, 1, 1))
            game2 = Game(id=2, date=date(2024, 2, 1))
            game3 = Game(id=3, date=date(2024, 3, 1))
            db_session.add_all([game1, game2, game3])
            db_session.flush()

            # Alice in game1 and game2
            db_session.add(Participant(game_id=1, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=2, player_id=1, deck_id=1))
            # Bob in game3 with same deck (different player)
            db_session.add(Participant(game_id=3, player_id=2, deck_id=1))
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert len(results) == 1
            assert results[0]["games"] == 2

    def test_last_played_across_all_participants(self, app, db_session):
        """Last played should be MAX(game.date) across ALL participants for the deck."""
        with app.app_context():
            ci = ColorIdentity(name="Dimir", amount=2)
            db_session.add(ci)
            db_session.flush()

            player1 = Player(id=1, name="Alice")
            player2 = Player(id=2, name="Bob")
            db_session.add_all([player1, player2])
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Dimir")
            db_session.add(deck)
            db_session.flush()

            # Game with Alice on Jan 1
            game1 = Game(id=1, date=date(2024, 1, 1))
            # Game with Bob (using same deck) on March 15 - more recent
            game2 = Game(id=2, date=date(2024, 3, 15))
            db_session.add_all([game1, game2])
            db_session.flush()

            db_session.add(Participant(game_id=1, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=2, player_id=2, deck_id=1))
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["last_played"] == date(2024, 3, 15)

    def test_win_count_for_player_deck(self, app, db_session):
        """Win count should count only games where this player won with this deck."""
        with app.app_context():
            ci = ColorIdentity(name="Rakdos", amount=2)
            db_session.add(ci)
            db_session.flush()

            player1 = Player(id=1, name="Alice")
            player2 = Player(id=2, name="Bob")
            db_session.add_all([player1, player2])
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Rakdos")
            db_session.add(deck)
            db_session.flush()

            # Alice wins game1, Bob wins game2, no winner in game3
            game1 = Game(id=1, date=date(2024, 1, 1), winner_id=1)
            game2 = Game(id=2, date=date(2024, 2, 1), winner_id=2)
            game3 = Game(id=3, date=date(2024, 3, 1), winner_id=None)
            db_session.add_all([game1, game2, game3])
            db_session.flush()

            db_session.add(Participant(game_id=1, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=2, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=3, player_id=1, deck_id=1))
            # Bob also participates
            db_session.add(Participant(game_id=1, player_id=2, deck_id=1))
            db_session.add(Participant(game_id=2, player_id=2, deck_id=1))
            db_session.add(Participant(game_id=3, player_id=2, deck_id=1))
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["wins"] == 1
            assert results[0]["games"] == 3

    def test_winrate_calculation(self, app, db_session):
        """Winrate should be (wins * 100) / games, rounded to 2 decimal places."""
        with app.app_context():
            ci = ColorIdentity(name="Selesnya", amount=2)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Selesnya")
            db_session.add(deck)
            db_session.flush()

            # Alice plays 3 games, wins 1 -> winrate = 33.33
            game1 = Game(id=1, date=date(2024, 1, 1), winner_id=1)
            game2 = Game(id=2, date=date(2024, 2, 1), winner_id=None)
            game3 = Game(id=3, date=date(2024, 3, 1), winner_id=None)
            db_session.add_all([game1, game2, game3])
            db_session.flush()

            db_session.add(Participant(game_id=1, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=2, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=3, player_id=1, deck_id=1))
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["winrate_pct"] == pytest.approx(33.33, abs=0.01)

    def test_winrate_null_when_zero_games(self, app, db_session):
        """Winrate should be None when the deck has zero games for this player."""
        with app.app_context():
            ci = ColorIdentity(name="Boros", amount=2)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Boros")
            db_session.add(deck)
            db_session.flush()

            # No games at all
            results = get_user_decks(db_session, player_id=1)

            assert results[0]["games"] == 0
            assert results[0]["winrate_pct"] is None

    def test_color_imgs_ordered_by_color_name(self, app, db_session):
        """Color images should be ordered by color name."""
        with app.app_context():
            ci = ColorIdentity(name="Izzet", amount=2)
            db_session.add(ci)
            db_session.flush()

            # Colors: Blue and Red (alphabetically: Blue, Red)
            blue = Color(name="Blue", abbreviation="U", img="/img/blue.svg")
            red = Color(name="Red", abbreviation="R", img="/img/red.svg")
            db_session.add_all([blue, red])
            db_session.flush()

            # Color components for Izzet
            db_session.add(ColorComponent(color_identity="Izzet", color="Red"))
            db_session.add(ColorComponent(color_identity="Izzet", color="Blue"))
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Izzet")
            db_session.add(deck)
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["color_imgs"] == ["/img/blue.svg", "/img/red.svg"]

    def test_tags_ordered_alphabetically(self, app, db_session):
        """Tags should be ordered alphabetically."""
        with app.app_context():
            ci = ColorIdentity(name="Simic", amount=2)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Simic")
            db_session.add(deck)
            db_session.flush()

            # Add tags in non-alphabetical order
            db_session.add(DeckTag(deck_id=1, tag="Voltron"))
            db_session.add(DeckTag(deck_id=1, tag="Aggro"))
            db_session.add(DeckTag(deck_id=1, tag="Midrange"))
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["tags"] == ["Aggro", "Midrange", "Voltron"]

    def test_empty_color_imgs_when_no_components(self, app, db_session):
        """Should return empty list when no color components with images exist."""
        with app.app_context():
            ci = ColorIdentity(name="Mono", amount=1)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Mono")
            db_session.add(deck)
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["color_imgs"] == []

    def test_empty_tags_when_no_tags(self, app, db_session):
        """Should return empty list when no tags exist for the deck."""
        with app.app_context():
            ci = ColorIdentity(name="Esper", amount=3)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Esper")
            db_session.add(deck)
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["tags"] == []

    def test_returns_empty_list_for_nonexistent_player(self, app, db_session):
        """Should return empty list for a player that doesn't exist."""
        with app.app_context():
            results = get_user_decks(db_session, player_id=9999)
            assert results == []

    def test_last_played_none_when_no_games(self, app, db_session):
        """last_played should be None when the deck has never been played."""
        with app.app_context():
            ci = ColorIdentity(name="Golgari", amount=2)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Golgari")
            db_session.add(deck)
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["last_played"] is None

    def test_decklist_url_included(self, app, db_session):
        """Decklist URL should be passed through from the deck model."""
        with app.app_context():
            ci = ColorIdentity(name="Mardu", amount=3)
            db_session.add(ci)
            db_session.flush()

            player = Player(id=1, name="Alice")
            db_session.add(player)
            db_session.flush()

            deck = Deck(id=1, name="My Deck", commander="Cmd",
                        player_id=1, active=True, color_identity="Mardu",
                        decklist="https://moxfield.com/deck/xyz")
            db_session.add(deck)
            db_session.flush()

            results = get_user_decks(db_session, player_id=1)

            assert results[0]["decklist"] == "https://moxfield.com/deck/xyz"
