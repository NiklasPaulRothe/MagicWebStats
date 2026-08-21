"""Shared test fixtures for MagicWebStats tests.

Uses SQLite in-memory database for fast, isolated test execution.
Handles the schema='magic_stats_owner' table args by attaching a 'magic_stats_owner' schema
in SQLite via ATTACH DATABASE.
"""

import pytest
from flask import Flask
from flask_login import LoginManager, FlaskLoginClient

from app import db as _db
from app.models import User


class TestConfig:
    """Flask configuration for testing with SQLite in-memory DB."""

    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_DOMAIN = False


@pytest.fixture(scope="session")
def app():
    """Create a Flask application configured for testing.

    Uses an in-memory SQLite database. Since our models use
    schema='magic_stats_owner', we attach a second in-memory DB as 'magic_stats_owner'
    so that SQLAlchemy table references like 'magic_stats_owner.users' resolve.
    """
    from app import create_app

    application = create_app(config_class=TestConfig)

    with application.app_context():
        # Attach a schema named 'magic_stats_owner' for SQLite compatibility
        # SQLite doesn't support schemas natively, but ATTACH works
        _db.session.execute(
            _db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner")
        )
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db_session(app):
    """Provide a clean database session for each test.

    Rolls back all changes after each test to maintain isolation.
    """
    with app.app_context():
        _db.session.begin_nested()
        yield _db.session
        _db.session.rollback()


@pytest.fixture()
def test_user(app, db_session):
    """Create and return a test user for authentication contexts."""
    user = User(
        id=1,
        username="testuser",
        email="test@example.com",
        player_id=1,
        active=True,
        role="admin",
    )
    user.set_password("testpassword")
    db_session.add(user)
    db_session.flush()
    return user
