"""Unit tests for app.main.routes.resolve_player.

Covers resolution by numeric id, resolution by name, and the None-on-miss
behaviour that callers turn into a 404.

Validates: Requirements 1.3, 1.4, 1.5
"""

import pytest

from app.models import Player
from app.main.routes import resolve_player


@pytest.fixture()
def seeded(app, db_session):
    """Seed two players with known ids and names."""
    with app.app_context():
        db_session.query(Player).delete()
        db_session.flush()

        db_session.add(Player(id=42, name="Alice"))
        db_session.add(Player(id=7, name="Bob"))
        db_session.flush()
        yield db_session


def test_numeric_string_resolves_by_id(app, seeded):
    with app.app_context():
        player = resolve_player("42")
        assert player is not None
        assert player.id == 42
        assert player.name == "Alice"


def test_int_resolves_by_id(app, seeded):
    with app.app_context():
        player = resolve_player(7)
        assert player is not None
        assert player.id == 7
        assert player.name == "Bob"


def test_name_resolves_by_name(app, seeded):
    with app.app_context():
        player = resolve_player("Alice")
        assert player is not None
        assert player.id == 42


def test_numeric_miss_returns_none(app, seeded):
    with app.app_context():
        assert resolve_player("9999") is None


def test_name_miss_returns_none(app, seeded):
    with app.app_context():
        assert resolve_player("Nobody") is None
