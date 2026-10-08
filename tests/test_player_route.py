"""Route tests for the public player profile at /player/<identifier>.

Covers 200 for an existing player (by id and by legacy name) and 404 for a
missing player, exercised through the authenticated test client.

Validates: Requirements 1.1, 1.5
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
    profile route (Req 1.6).
    """
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=user)


def test_player_by_id_returns_200(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/player/1")
    assert resp.status_code == 200
    assert b"Alice" in resp.data


def test_player_by_legacy_name_returns_200(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/player/Bob")
    assert resp.status_code == 200
    assert b"Bob" in resp.data


def test_missing_player_returns_404(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/player/9999")
    assert resp.status_code == 404


def test_missing_player_by_name_returns_404(app, route_user, seeded_players):
    client = _client(app, route_user)
    resp = client.get("/player/Nobody")
    assert resp.status_code == 404


def test_profile_renders_sections(app, route_user, seeded_players):
    """The profile template renders its named sections (and empty states) for a
    player with no games, so the full layout is exercised without error.

    Validates: Requirements 2.1, 4.5, 10.3
    """
    client = _client(app, route_user)
    resp = client.get("/player/1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Identity header name (Req 2.1) and a couple of section headings render.
    assert "Alice" in body
    assert "Letzte Spiele" in body
    assert "Farbnutzung" in body
    # Zero-games player shows a neutral empty state, not a crash (Req 4.5).
    assert "Noch keine Spiele" in body


@pytest.fixture()
def two_users(app):
    """Two committed users: owner of Alice (id=1) and a non-owner (id=2).

    Mirrors the committed-fixture pattern used elsewhere in this module so the
    rows survive the request's session teardown. ``owner`` is linked to player
    id 1 (Alice); ``other`` is linked to player id 2 (Bob) and is therefore not
    the owner of Alice.
    """
    with app.app_context():
        _db.session.query(User).delete()
        _db.session.query(Player).delete()
        _db.session.commit()

        owner = User(
            id=1, username="owner", email="owner@example.com",
            player_id=1, active=True, role="admin",
        )
        owner.set_password("pw")
        other = User(
            id=2, username="other", email="other@example.com",
            player_id=2, active=True, role="admin",
        )
        other.set_password("pw")
        _db.session.add_all([owner, other])
        _db.session.commit()
        yield {"owner": owner, "other": other}

        _db.session.query(User).delete()
        _db.session.commit()


@pytest.fixture()
def two_user_players(app, two_users):
    """Seed Alice (id=1, owned) and Bob (id=2) for the owner/non-owner tests."""
    with app.app_context():
        _db.session.add(Player(id=1, name="Alice"))
        _db.session.add(Player(id=2, name="Bob"))
        _db.session.commit()
        yield _db.session

        _db.session.query(Player).delete()
        _db.session.commit()


def test_owner_sees_bio_edit_form(app, two_users, two_user_players):
    """Bio editing was removed from the profile overview: even the owner no
    longer sees a bio textarea on the profile page. The profile still renders
    normally for the owner."""
    client = _client(app, two_users["owner"])
    resp = client.get("/player/1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Profile still renders for the owner...
    assert "Alice" in body
    # ...but the bio editing control is no longer part of the profile.
    assert "<textarea" not in body


def test_non_owner_has_no_bio_edit_form(app, two_users, two_user_players):
    """A logged-in non-owner never sees an input control (Req 11.5)."""
    # ``other`` (user id 2) is not the owner of Alice (player id 1).
    client = _client(app, two_users["other"])
    resp = client.get("/player/1")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    # Profile still renders for the non-owner...
    assert "Alice" in body
    # ...but with no edit controls at all (Req 11.5).
    assert "<textarea" not in body
    assert "/user/1/bio" not in body
