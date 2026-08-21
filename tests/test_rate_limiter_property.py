# Feature: service-layer-security-refactor, Property 16: Rate limiter enforcement
"""Property-based test for rate limiter enforcement.

**Validates: Requirements 18.2, 18.3**

For any client making N requests to `/auth/login` within the configured time
window, requests SHALL be rejected with HTTP 429 if and only if N exceeds the
configured limit (10/minute).
"""

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import create_app, db as _db


class RateLimitTestConfig:
    """Flask configuration for rate limiter testing.

    Uses in-memory storage for Flask-Limiter so rate limit state is isolated
    per test app instance. CSRF is disabled to simplify POST requests.
    """

    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_DOMAIN = False
    RATELIMIT_STORAGE_URI = "memory://"
    # Ensure rate limiting is enabled even in testing mode
    RATELIMIT_ENABLED = True


@pytest.fixture()
def rate_limit_app():
    """Create a fresh Flask app for each rate limit test.

    A fresh app is needed per test because the limiter state must be reset
    between test cases (in-memory storage is per-app-instance).
    """
    application = create_app(config_class=RateLimitTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@given(n=st.integers(min_value=1, max_value=10))
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_requests_within_limit_are_allowed(n):
    """Property 16a: When N <= 10 requests are made within the time window,
    all requests SHALL be allowed to reach the route handler (no 429 response).
    """
    application = create_app(config_class=RateLimitTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

        client = application.test_client()

        for i in range(n):
            response = client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "wrong",
            })
            assert response.status_code != 429, (
                f"Request {i + 1} of {n} was rate-limited (429) but "
                f"should be allowed (limit is 10/minute)"
            )

        _db.session.remove()
        _db.drop_all()


@given(n=st.integers(min_value=11, max_value=15))
@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_requests_exceeding_limit_are_rejected(n):
    """Property 16b: When N > 10 requests are made within the time window,
    requests beyond the 10th SHALL be rejected with HTTP 429.
    """
    application = create_app(config_class=RateLimitTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

        client = application.test_client()

        # First 10 requests should all be allowed
        for i in range(10):
            response = client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "wrong",
            })
            assert response.status_code != 429, (
                f"Request {i + 1} was rate-limited (429) but should be allowed "
                f"(within the 10/minute limit)"
            )

        # Requests 11 through N should all be rejected with 429
        for i in range(10, n):
            response = client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "wrong",
            })
            assert response.status_code == 429, (
                f"Request {i + 1} returned {response.status_code} but should be "
                f"rate-limited (429) since it exceeds the 10/minute limit"
            )

        _db.session.remove()
        _db.drop_all()


def test_exact_boundary_tenth_request_allowed():
    """Property 16c: The 10th request (exactly at the limit) SHALL be allowed."""
    application = create_app(config_class=RateLimitTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

        client = application.test_client()

        # Make exactly 10 requests
        for i in range(10):
            response = client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "wrong",
            })
            assert response.status_code != 429, (
                f"Request {i + 1} was rate-limited but the limit is 10/minute"
            )

        _db.session.remove()
        _db.drop_all()


def test_exact_boundary_eleventh_request_rejected():
    """Property 16d: The 11th request (one over the limit) SHALL be rejected with 429."""
    application = create_app(config_class=RateLimitTestConfig)

    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()

        client = application.test_client()

        # Exhaust the limit
        for i in range(10):
            client.post("/auth/login", data={
                "username": "nonexistent",
                "password": "wrong",
            })

        # The 11th request should be rejected
        response = client.post("/auth/login", data={
            "username": "nonexistent",
            "password": "wrong",
        })
        assert response.status_code == 429, (
            f"11th request returned {response.status_code} but should be 429"
        )

        _db.session.remove()
        _db.drop_all()
