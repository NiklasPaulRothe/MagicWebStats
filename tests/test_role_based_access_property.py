# Feature: service-layer-security-refactor, Property 13: Role-based access control
"""Property-based test for role-based access control.

**Validates: Requirements 13.2, 13.3**

For any authenticated user, access to admin-gated endpoints (audit_log,
deck_participant_averages) SHALL be granted if and only if user.role == 'admin'.
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from flask_login import login_user

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


# Roles that should be denied access to admin-gated endpoints
NON_ADMIN_ROLES = ["user", "maintainer", "viewer", "editor", "guest"]

# Strategy: generate a non-admin role
non_admin_role_strategy = st.sampled_from(NON_ADMIN_ROLES)

# Strategy: generate any role including admin
all_role_strategy = st.sampled_from(["admin"] + NON_ADMIN_ROLES)


def _create_app_and_db():
    """Create a fresh Flask app with an in-memory database."""
    application = create_app(config_class=RoleAccessTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

    return application


def _create_user(app, username, role, user_id):
    """Create a test user with the given role."""
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

        # Ensure Player and ColorIdentity exist for FK constraints
        if not Player.query.get(1):
            _db.session.add(Player(id=1, name="TestPlayer"))
        if not ColorIdentity.query.filter_by(name="Mono-Red").first():
            _db.session.add(ColorIdentity(name="Mono-Red", amount=1))

        # Ensure a deck exists for the deck_participant_averages endpoint
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
    with client.session_transaction() as sess:
        # Flask-Login uses _user_id in the session
        pass

    # Use the login route to establish a session
    response = client.post("/auth/login", data={
        "username": username,
        "password": password,
    }, follow_redirects=False)
    return response


@given(role=non_admin_role_strategy)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_admin_denied_audit_log(role):
    """Property 13a: Non-admin users SHALL be denied access to audit_log (403).

    For any role that is not 'admin', accessing /audit-log SHALL return 403.
    """
    application = _create_app_and_db()

    with application.app_context():
        user = _create_user(application, f"user_{role}", role, user_id=99)

        with application.test_client() as client:
            _login_user(client, f"user_{role}")

            response = client.get("/audit-log")
            assert response.status_code == 403, (
                f"User with role={role!r} got status {response.status_code} "
                f"on /audit-log but expected 403 (non-admin should be denied)"
            )

        _db.session.remove()
        _db.drop_all()


@given(role=non_admin_role_strategy)
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_admin_denied_deck_participant_averages(role):
    """Property 13b: Non-admin users SHALL be denied access to
    deck_participant_averages (403).

    For any role that is not 'admin', accessing /api/deck-participant-averages/<deckname>
    SHALL return 403.
    """
    application = _create_app_and_db()

    with application.app_context():
        user = _create_user(application, f"user_{role}", role, user_id=99)

        with application.test_client() as client:
            _login_user(client, f"user_{role}")

            response = client.get("/api/deck-participant-averages/TestDeck")
            assert response.status_code == 403, (
                f"User with role={role!r} got status {response.status_code} "
                f"on /api/deck-participant-averages/TestDeck but expected 403 "
                f"(non-admin should be denied)"
            )

        _db.session.remove()
        _db.drop_all()


def test_admin_granted_audit_log():
    """Property 13c: Admin users SHALL be granted access to audit_log (200).

    A user with role='admin' accessing /audit-log SHALL receive a 200 response.
    """
    application = _create_app_and_db()

    with application.app_context():
        user = _create_user(application, "adminuser", "admin", user_id=2)

        with application.test_client() as client:
            _login_user(client, "adminuser")

            response = client.get("/audit-log")
            assert response.status_code == 200, (
                f"Admin user got status {response.status_code} on /audit-log "
                f"but expected 200 (admin should be granted access)"
            )

        _db.session.remove()
        _db.drop_all()


def test_admin_granted_deck_participant_averages():
    """Property 13d: Admin users SHALL be granted access to
    deck_participant_averages (200).

    A user with role='admin' accessing /api/deck-participant-averages/<deckname>
    SHALL receive a 200 response.
    """
    application = _create_app_and_db()

    with application.app_context():
        user = _create_user(application, "adminuser", "admin", user_id=2)

        with application.test_client() as client:
            _login_user(client, "adminuser")

            response = client.get("/api/deck-participant-averages/TestDeck")
            assert response.status_code == 200, (
                f"Admin user got status {response.status_code} on "
                f"/api/deck-participant-averages/TestDeck but expected 200 "
                f"(admin should be granted access)"
            )

        _db.session.remove()
        _db.drop_all()


@given(role=all_role_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_access_granted_iff_admin(role):
    """Property 13e: For any authenticated user, access to admin-gated endpoints
    SHALL be granted if and only if user.role == 'admin'.

    This is the core biconditional property: admin <=> access granted.
    """
    application = _create_app_and_db()

    with application.app_context():
        user = _create_user(application, f"user_{role}", role, user_id=99)

        with application.test_client() as client:
            _login_user(client, f"user_{role}")

            # Test audit_log endpoint
            response = client.get("/audit-log")
            if role == "admin":
                assert response.status_code == 200, (
                    f"Admin user got {response.status_code} on /audit-log "
                    f"but expected 200"
                )
            else:
                assert response.status_code == 403, (
                    f"User with role={role!r} got {response.status_code} "
                    f"on /audit-log but expected 403"
                )

            # Test deck_participant_averages endpoint
            response = client.get("/api/deck-participant-averages/TestDeck")
            if role == "admin":
                assert response.status_code == 200, (
                    f"Admin user got {response.status_code} on "
                    f"/api/deck-participant-averages/TestDeck but expected 200"
                )
            else:
                assert response.status_code == 403, (
                    f"User with role={role!r} got {response.status_code} on "
                    f"/api/deck-participant-averages/TestDeck but expected 403"
                )

        _db.session.remove()
        _db.drop_all()


def test_unauthenticated_denied_audit_log():
    """Unauthenticated users should NOT be granted access (200) on admin endpoints.

    The role_required decorator denies unauthenticated users with 403,
    which is correct because they lack any role.
    """
    application = _create_app_and_db()

    with application.app_context():
        with application.test_client() as client:
            response = client.get("/audit-log")
            # Should be denied — either 302 (redirect to login), 401, or 403
            assert response.status_code != 200, (
                f"Unauthenticated user got 200 on /audit-log but should be denied"
            )

        _db.session.remove()
        _db.drop_all()


def test_unauthenticated_denied_deck_participant_averages():
    """Unauthenticated users should NOT be granted access (200) on admin endpoints.

    The role_required decorator denies unauthenticated users with 403,
    which is correct because they lack any role.
    """
    application = _create_app_and_db()

    with application.app_context():
        with application.test_client() as client:
            response = client.get("/api/deck-participant-averages/TestDeck")
            # Should be denied — either 302 (redirect to login), 401, or 403
            assert response.status_code != 200, (
                f"Unauthenticated user got 200 on "
                f"/api/deck-participant-averages/TestDeck but should be denied"
            )

        _db.session.remove()
        _db.drop_all()
