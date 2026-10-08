"""Route tests for the bio update endpoint at POST /user/<identifier>/bio.

Covers the owner happy path (302 redirect + persisted bio), the server-side
ownership check (403 for a non-owner), the length limit (400 for over-length
input), and stored-XSS safety (raw text persisted, escaped on render).

These tests drive real HTTP requests through the authenticated test client, so
they seed committed rows (not the nested ``db_session`` savepoint) and clean up
explicitly, matching ``tests/test_player_route.py``. CSRF is disabled under the
testing config (``WTF_CSRF_ENABLED = False``), so form POSTs need no token.

Validates: Requirements 11.6, 11.7, 11.8
"""

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, User


@pytest.fixture()
def route_users(app):
    """Two committed users: the owner of Alice (id=1) and a non-owner.

    ``owner`` is linked to player id 1 (Alice) via ``player_id``; ``other`` is
    linked to player id 2 (Bob) and is therefore not the owner of Alice. Rows
    are committed so they survive the request's session teardown and cleaned up
    explicitly afterwards.
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
def seeded_players(app, route_users):
    """Seed Alice (id=1, owned) and Bob (id=2) for the bio route."""
    with app.app_context():
        _db.session.add(Player(id=1, name="Alice"))
        _db.session.add(Player(id=2, name="Bob"))
        _db.session.commit()
        yield _db.session

        _db.session.query(Player).delete()
        _db.session.commit()


def _client(app, user):
    """Authenticated test client that logs ``user`` in for every request."""
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=user)


def _read_bio(app, user_id):
    """Read the persisted bio for a user id in a fresh session scope."""
    with app.app_context():
        return _db.session.get(User, user_id).bio


def test_owner_post_redirects_and_persists(app, route_users, seeded_players):
    client = _client(app, route_users["owner"])
    resp = client.post("/user/1/bio", data={"bio": "  Hello, world  "})

    # Redirects back to the canonical profile page (Req 11.6).
    assert resp.status_code == 302
    assert "/player/1" in resp.headers["Location"]
    # Stored stripped (Req 11.8 strip) and visible on reload (Req 11.6).
    assert _read_bio(app, 1) == "Hello, world"


def test_non_owner_post_is_forbidden(app, route_users, seeded_players):
    # ``other`` (user id 2) is not the owner of Alice (player id 1).
    client = _client(app, route_users["other"])
    resp = client.post("/user/1/bio", data={"bio": "I should not be allowed"})

    # Server-side ownership check rejects the non-owner (Req 11.7).
    assert resp.status_code == 403
    # Nothing was persisted to the owner's bio.
    assert _read_bio(app, 1) is None


def test_over_length_post_is_rejected(app, route_users, seeded_players):
    client = _client(app, route_users["owner"])
    too_long = "x" * 1001
    resp = client.post("/user/1/bio", data={"bio": too_long})

    # Over the 1000-char column limit -> 400 (Req 11.8).
    assert resp.status_code == 400
    assert _read_bio(app, 1) is None


def test_boundary_length_is_accepted(app, route_users, seeded_players):
    client = _client(app, route_users["owner"])
    exactly_max = "y" * 1000
    resp = client.post("/user/1/bio", data={"bio": exactly_max})

    assert resp.status_code == 302
    assert _read_bio(app, 1) == exactly_max


def test_html_bio_stored_raw_not_pre_escaped(app, route_users, seeded_players):
    """A bio containing HTML is persisted raw, not pre-escaped at write time.

    The route stores the raw stripped text and relies on Jinja autoescaping at
    render time to prevent stored XSS (Req 11.8); it must not HTML-escape the
    value on the way in. (The escaped-on-render behavior is exercised by the
    profile template tests once the bio section is rendered.)
    """
    client = _client(app, route_users["owner"])
    payload = "<script>alert('xss')</script>"
    resp = client.post("/user/1/bio", data={"bio": payload})
    assert resp.status_code == 302

    # Stored raw, not pre-escaped.
    assert _read_bio(app, 1) == payload
