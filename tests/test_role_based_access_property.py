# Feature: role-tiers (user < maintainer < admin), role-based access control
"""Property-based tests for the hierarchical role model.

Roles are hierarchical: ``user`` < ``maintainer`` < ``admin`` (admin is a
superset of maintainer, which is a superset of user). Access is checked by
LEVEL, so a higher tier inherits every lower-tier capability, and unknown roles
fail closed (denied everywhere).

Endpoint tiers under test:
  • /audit-log                              -> admin only
  • /decks/elo (recalculate)                -> admin only
  • /api/deck-participant-averages/<deck>   -> maintainer or higher
  • /PlayerAdd, /DeckAdd, /game-add, /manage/games -> maintainer or higher
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import create_app, db as _db
from app.models import User, Player, Deck, ColorIdentity


class RoleAccessTestConfig:
    """Flask configuration for role-based access control testing."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_DOMAIN = False
    RATELIMIT_ENABLED = False
    PERSONAL_STATS_USERNAME = "Niklas"


# Roles that rank BELOW maintainer (plus some unknown roles that must fail
# closed). These are denied every maintainer+ and admin-only endpoint.
BELOW_MAINTAINER_ROLES = ["user", "viewer", "editor", "guest", ""]

# Roles at maintainer level but BELOW admin — granted maintainer+ endpoints,
# denied admin-only endpoints.
MAINTAINER_ONLY_ROLES = ["maintainer"]

below_maintainer_strategy = st.sampled_from(BELOW_MAINTAINER_ROLES)
# Any non-admin role (used for admin-only endpoint denial).
non_admin_strategy = st.sampled_from(BELOW_MAINTAINER_ROLES + MAINTAINER_ONLY_ROLES)
# Any role including admin (for the biconditional admin test).
all_role_strategy = st.sampled_from(["admin"] + BELOW_MAINTAINER_ROLES + MAINTAINER_ONLY_ROLES)


def _create_app_and_db():
    """Create a fresh Flask app with an in-memory database."""
    application = create_app(config_class=RoleAccessTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

    return application


def _create_user(app, username, role, user_id):
    """Create a test user with the given role (+ FK fixtures)."""
    with app.app_context():
        user = User(
            id=user_id,
            username=username,
            email=f"{username}@test.com",
            player_id=1,
            active=True,
            role=role,
        )
        user.set_password("testpassword")
        _db.session.add(user)

        if not Player.query.get(1):
            _db.session.add(Player(id=1, name="TestPlayer"))
        if not ColorIdentity.query.filter_by(name="Mono-Red").first():
            _db.session.add(ColorIdentity(name="Mono-Red", amount=1))
        if not Deck.query.filter_by(name="TestDeck").first():
            _db.session.add(Deck(
                id=1,
                name="TestDeck",
                active=True,
                commander="Test Commander",
                player_id=1,
                color_identity="Mono-Red",
            ))

        _db.session.commit()
        return user


def _login_user(client, username, password="testpassword"):
    """Login a user via the test client session."""
    return client.post("/auth/login", data={
        "username": username,
        "password": password,
    }, follow_redirects=False)


# Endpoints by tier for the parametrized checks.
ADMIN_ONLY_ENDPOINTS = ["/audit-log", "/decks/elo"]
MAINTAINER_PLUS_ENDPOINTS = [
    "/api/deck-participant-averages/TestDeck",
    "/PlayerAdd",
    "/DeckAdd",
    "/game-add",
    "/manage/games",
]


# ── Admin-only endpoints ─────────────────────────────────────────────────────

@given(role=non_admin_strategy)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_admin_denied_admin_endpoints(role):
    """Any non-admin role (including maintainer) is denied admin-only endpoints."""
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, f"u_{role or 'empty'}", role, user_id=99)
        with application.test_client() as client:
            _login_user(client, f"u_{role or 'empty'}")
            for path in ADMIN_ONLY_ENDPOINTS:
                resp = client.get(path, follow_redirects=False)
                assert resp.status_code == 403, (
                    f"role={role!r} got {resp.status_code} on {path}, expected 403"
                )
        _db.session.remove()
        _db.drop_all()


def test_admin_granted_admin_endpoints():
    """An admin is granted the admin-only endpoints.

    /audit-log renders (200). /decks/elo performs a recompute and redirects
    (302) — both are "granted" (not 403).
    """
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, "adminuser", "admin", user_id=2)
        with application.test_client() as client:
            _login_user(client, "adminuser")
            assert client.get("/audit-log").status_code == 200
            assert client.get("/decks/elo", follow_redirects=False).status_code in (200, 302)
        _db.session.remove()
        _db.drop_all()


# ── Maintainer-or-higher endpoints ───────────────────────────────────────────

@given(role=below_maintainer_strategy)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_below_maintainer_denied_maintainer_endpoints(role):
    """Roles below maintainer are denied maintainer+ endpoints (403)."""
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, f"u_{role or 'empty'}", role, user_id=99)
        with application.test_client() as client:
            _login_user(client, f"u_{role or 'empty'}")
            for path in MAINTAINER_PLUS_ENDPOINTS:
                resp = client.get(path, follow_redirects=False)
                assert resp.status_code == 403, (
                    f"role={role!r} got {resp.status_code} on {path}, expected 403"
                )
        _db.session.remove()
        _db.drop_all()


@pytest.mark.parametrize("role", ["maintainer", "admin"])
def test_maintainer_and_admin_granted_maintainer_endpoints(role):
    """Maintainer AND admin are granted maintainer+ endpoints (not 403).

    GET on the add-forms renders (200); the averages API returns 200. We only
    assert access is NOT forbidden (status != 403) to stay robust to the exact
    success code of each handler.
    """
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, f"m_{role}", role, user_id=3)
        with application.test_client() as client:
            _login_user(client, f"m_{role}")
            for path in MAINTAINER_PLUS_ENDPOINTS:
                resp = client.get(path, follow_redirects=False)
                assert resp.status_code != 403, (
                    f"role={role!r} got 403 on {path}, expected access granted"
                )
        _db.session.remove()
        _db.drop_all()


def test_maintainer_denied_admin_endpoints_explicit():
    """A maintainer is explicitly denied the admin-only endpoints (403)."""
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, "maint", "maintainer", user_id=4)
        with application.test_client() as client:
            _login_user(client, "maint")
            for path in ADMIN_ONLY_ENDPOINTS:
                assert client.get(path, follow_redirects=False).status_code == 403
        _db.session.remove()
        _db.drop_all()


# ── Biconditional + unauthenticated ──────────────────────────────────────────

@given(role=all_role_strategy)
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_admin_endpoint_granted_iff_admin(role):
    """Admin-only endpoint access is granted iff the role is admin."""
    application = _create_app_and_db()
    with application.app_context():
        _create_user(application, f"u_{role or 'empty'}", role, user_id=99)
        with application.test_client() as client:
            _login_user(client, f"u_{role or 'empty'}")
            resp = client.get("/audit-log", follow_redirects=False)
            if role == "admin":
                assert resp.status_code == 200
            else:
                assert resp.status_code == 403
        _db.session.remove()
        _db.drop_all()


def test_unauthenticated_denied_admin_and_maintainer_endpoints():
    """Unauthenticated users are never granted (status != 200) any gated endpoint."""
    application = _create_app_and_db()
    with application.app_context():
        with application.test_client() as client:
            for path in ADMIN_ONLY_ENDPOINTS + MAINTAINER_PLUS_ENDPOINTS:
                resp = client.get(path, follow_redirects=False)
                assert resp.status_code != 200, (
                    f"unauthenticated got 200 on {path}, should be denied"
                )
        _db.session.remove()
        _db.drop_all()
