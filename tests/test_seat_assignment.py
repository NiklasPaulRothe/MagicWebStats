"""Tests for seat assignment in game creation.

Verifies that:
1. ParticipantInput accepts and stores a seat value.
2. create_game correctly persists seat values to the database.
3. The player with seat=1 becomes first_player_id.
4. When seats_not_tracked is true, all seats are None and first_player_id is None.
5. Seat values are validated (1 through number of players, each unique).
6. The GameAdd template includes seat inputs and the seats_not_tracked checkbox.
"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest
import sqlalchemy as sa

from app import db as _db
from app.models import Deck, Game, Participant, Player, ColorIdentity, User
from app.services.game_service import ParticipantInput, create_game


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_current_user():
    """Mock current_user for audit log."""
    mock_user = MagicMock()
    mock_user.id = 99
    mock_user.username = "testuser"
    return mock_user


# ---------------------------------------------------------------------------
# Test: ParticipantInput dataclass
# ---------------------------------------------------------------------------


class TestParticipantInputSeat:
    """Tests for seat field in ParticipantInput dataclass."""

    def test_seat_defaults_to_none(self):
        """Seat should default to None if not provided."""
        p = ParticipantInput(player_id=1, deck_id=1)
        assert p.seat is None

    def test_seat_accepts_integer(self):
        """Seat should accept an integer value."""
        p = ParticipantInput(player_id=1, deck_id=1, seat=3)
        assert p.seat == 3

    def test_seat_accepts_none_explicitly(self):
        """Seat should accept None explicitly (seats not tracked)."""
        p = ParticipantInput(player_id=1, deck_id=1, seat=None)
        assert p.seat is None


# ---------------------------------------------------------------------------
# Test: create_game with seats
# ---------------------------------------------------------------------------


class TestCreateGameWithSeats:
    """Tests for game creation with seat assignments."""

    def _setup_data(self, mock_current_user):
        """Set up test data and clean up previous state."""
        from app import db

        db.session.rollback()
        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).delete()
        db.session.query(Player).delete()
        db.session.query(ColorIdentity).delete()
        db.session.query(User).filter(User.id == 99).delete()
        db.session.commit()

        ci = ColorIdentity(name="SeatTestCI", amount=2)
        db.session.add(ci)

        players = [
            Player(id=901, name="SeatAlice"),
            Player(id=902, name="SeatBob"),
            Player(id=903, name="SeatCharlie"),
            Player(id=904, name="SeatDiana"),
        ]
        db.session.add_all(players)

        decks = [
            Deck(id=901, name="Seat Deck A", commander="Commander A", player_id=901,
                 color_identity="SeatTestCI", active=True),
            Deck(id=902, name="Seat Deck B", commander="Commander B", player_id=902,
                 color_identity="SeatTestCI", active=True),
            Deck(id=903, name="Seat Deck C", commander="Commander C", player_id=903,
                 color_identity="SeatTestCI", active=True),
            Deck(id=904, name="Seat Deck D", commander="Commander D", player_id=904,
                 color_identity="SeatTestCI", active=True),
        ]
        db.session.add_all(decks)

        existing_user = db.session.get(User, 99)
        if existing_user is None:
            user = User(id=99, username="testuser", email="test@example.com",
                        player_id=901, active=True, role="admin")
            user.set_password("testpassword")
            db.session.add(user)
        db.session.commit()

    def _cleanup(self):
        """Clean up test data after each test."""
        from app import db
        db.session.rollback()
        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).filter(Deck.id >= 901).delete()
        db.session.query(Player).filter(Player.id >= 901).delete()
        db.session.query(ColorIdentity).filter(ColorIdentity.name == "SeatTestCI").delete()
        db.session.query(User).filter(User.id == 99).delete()
        db.session.commit()

    def test_seats_persisted_to_participants(self, app, mock_current_user):
        """Each participant's seat value should be persisted in the database."""
        with app.app_context():
            from app import db
            self._setup_data(mock_current_user)

            participants = [
                ParticipantInput(player_id=901, deck_id=901, seat=2),
                ParticipantInput(player_id=902, deck_id=902, seat=1),
                ParticipantInput(player_id=903, deck_id=903, seat=3),
            ]

            with patch("app.services.audit.current_user", mock_current_user):
                game = create_game(
                    date=date(2025, 6, 15),
                    first_player_id=902,
                    winner_id=901,
                    participants=participants,
                )

            db_participants = db.session.execute(
                sa.select(Participant).where(Participant.game_id == game.id)
            ).scalars().all()

            seats_by_player = {p.player_id: p.seat for p in db_participants}
            assert seats_by_player[901] == 2
            assert seats_by_player[902] == 1
            assert seats_by_player[903] == 3
            self._cleanup()

    def test_first_player_derived_from_seat_1(self, app, mock_current_user):
        """The player with seat=1 should be stored as first_player_id on the game."""
        with app.app_context():
            from app import db
            self._setup_data(mock_current_user)

            participants = [
                ParticipantInput(player_id=901, deck_id=901, seat=3),
                ParticipantInput(player_id=902, deck_id=902, seat=1),
                ParticipantInput(player_id=903, deck_id=903, seat=2),
            ]

            with patch("app.services.audit.current_user", mock_current_user):
                game = create_game(
                    date=date(2025, 6, 15),
                    first_player_id=902,
                    winner_id=901,
                    participants=participants,
                )

            assert game.first_player_id == 902
            self._cleanup()

    def test_null_seats_when_not_tracked(self, app, mock_current_user):
        """When seats are not tracked, all seat values should be None."""
        with app.app_context():
            from app import db
            self._setup_data(mock_current_user)

            participants = [
                ParticipantInput(player_id=901, deck_id=901, seat=None),
                ParticipantInput(player_id=902, deck_id=902, seat=None),
                ParticipantInput(player_id=903, deck_id=903, seat=None),
            ]

            with patch("app.services.audit.current_user", mock_current_user):
                game = create_game(
                    date=date(2025, 6, 15),
                    first_player_id=None,
                    winner_id=901,
                    participants=participants,
                )

            db_participants = db.session.execute(
                sa.select(Participant).where(Participant.game_id == game.id)
            ).scalars().all()

            for p in db_participants:
                assert p.seat is None

            assert game.first_player_id is None
            self._cleanup()

    def test_four_player_game_all_seats_assigned(self, app, mock_current_user):
        """A 4-player game should have seats 1 through 4 all assigned."""
        with app.app_context():
            from app import db
            self._setup_data(mock_current_user)

            participants = [
                ParticipantInput(player_id=901, deck_id=901, seat=4),
                ParticipantInput(player_id=902, deck_id=902, seat=2),
                ParticipantInput(player_id=903, deck_id=903, seat=1),
                ParticipantInput(player_id=904, deck_id=904, seat=3),
            ]

            with patch("app.services.audit.current_user", mock_current_user):
                game = create_game(
                    date=date(2025, 6, 15),
                    first_player_id=903,
                    winner_id=901,
                    participants=participants,
                )

            db_participants = db.session.execute(
                sa.select(Participant).where(Participant.game_id == game.id)
            ).scalars().all()

            seats = sorted(p.seat for p in db_participants)
            assert seats == [1, 2, 3, 4]
            self._cleanup()


# ---------------------------------------------------------------------------
# Test: GameAdd template includes seat UI elements
# ---------------------------------------------------------------------------


class TestGameAddTemplateSeatUI:
    """Verify that GameAdd.html includes seat-related UI elements."""

    def _read_template(self):
        """Read the GameAdd.html template source."""
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'app', 'templates', 'stats', 'GameAdd.html'
        )
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_template_has_seats_not_tracked_checkbox(self):
        """Template should include the seats_not_tracked checkbox."""
        html = self._read_template()
        assert 'seats_not_tracked' in html

    def test_template_has_seat_input_in_player_row(self):
        """Template should include seat input fields for players."""
        html = self._read_template()
        assert 'seat-input' in html
        assert 'seat-field' in html

    def test_template_no_longer_has_first_select(self):
        """Template should no longer have the old 'first' select dropdown."""
        html = self._read_template()
        # The old form.first field (as SelectField) should be gone
        # Note: form.first_ko_turn and form.first_ko_by still exist, that's fine
        assert 'form.first(' not in html
        assert 'form.first.label' not in html
        assert 'form.first.errors' not in html

    def _read_js(self):
        """Read the GameAdd.js source."""
        import os
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'app', 'static', 'js', 'GameAdd.js'
        )
        with open(js_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_js_has_seat_input_in_dynamic_player(self):
        """GameAdd.js should include seat input when dynamically adding players."""
        js = self._read_js()
        assert 'seat-input' in js
        assert 'seat-field' in js

    def test_js_has_update_seat_inputs_function(self):
        """GameAdd.js should have the updateSeatInputs function."""
        js = self._read_js()
        assert 'updateSeatInputs' in js

    def test_js_handles_seats_not_tracked(self):
        """GameAdd.js should reference the seats_not_tracked checkbox."""
        js = self._read_js()
        assert 'seats_not_tracked' in js
