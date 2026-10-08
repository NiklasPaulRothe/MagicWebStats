"""Route tests for the deck overview at /user/<identifier>.

Covers 200 for an existing player (by id and by legacy name) and 404 for a
missing player, exercised through the authenticated test client.

Validates: Requirements 1.2, 1.6, 12.1
"""

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, User


@pytest.fixture()
def route_user(app):
    """A committed user that the FlaskLoginClient can authenticate.

    Route tests drive a real HTTP request through the test client, which runs
    the view in its own session scope and tears the session down after each
    request (``db.session.remove()``). That lifecycle is incompatible with the
    nested-savepoint isolation used by the shared ``db_session`` fixture, so
    this fixture seeds committed rows and cleans them up explicitly instead of
    relying on a nested transaction. ``player_id=1`` makes the user the owner
    of the ``Alice`` player seeded below.
    """
    with app.app_context():
        _db.session.query(User).delete()
        _db.session.query(Player).delete()
        _db.session.commit()

        user = User(
            id=1, username="routeuser", email="route@example.com",
            player_id=1, active=True, role="admin",
        )
        user.set_password("pw")
        _db.session.add(user)
        _db.session.commit()
        yield user

        _db.session.query(User).delete()
        _db.session.commit()


@pytest.fixture()
def seeded_players(app, route_user):
    """Seed a couple of players with known ids/names for the route.

    Committed (not nested) so the data survives the request's session teardown;
    cleaned up explicitly after the test.
    """
    with app.app_context():
        _db.session.add(Player(id=1, name="Alice"))
        _db.session.add(Player(id=2, name="Bob"))
        _db.session.commit()
        yield _db.session

        _db.session.query(Player).delete()
        _db.session.commit()


def _client(app, user):
    """Authenticated test client.

    The app factory doesn't register ``FlaskLoginClient`` as the default test
    client, so wire it up here. ``app.test_client(user=...)`` then logs the
    user in for every request, satisfying the ``login_required`` guard on the
    deck overview route (Req 1.6).
    """
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=user)


def test_user_by_id_returns_200(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/user/1")
    assert resp.status_code == 200
    assert b"Alice" in resp.data


def test_user_by_legacy_name_returns_200(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/user/Bob")
    assert resp.status_code == 200
    assert b"Bob" in resp.data


def test_missing_user_returns_404(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/user/9999")
    assert resp.status_code == 404


def test_missing_user_by_name_returns_404(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/user/Nobody")
    assert resp.status_code == 404
