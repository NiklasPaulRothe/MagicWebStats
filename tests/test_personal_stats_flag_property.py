# Feature: service-layer-security-refactor, Property 14: Personal stats feature flag equivalence
"""Property-based test for personal stats feature flag equivalence.

**Validates: Requirements 13.4, 14.4**

For any authenticated user, has_personal_stats_access(user) SHALL return True
if and only if user.username == app.config['PERSONAL_STATS_USERNAME'], producing
the same boolean as the prior current_user.username == 'Niklas' check given
unchanged default configuration.
"""

from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app.auth import has_personal_stats_access


# Strategy for generating arbitrary usernames (non-empty printable strings)
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=64,
)

# Strategy for the configured personal stats username
config_username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=64,
)


def _make_user(username: str, is_authenticated: bool) -> MagicMock:
    """Create a mock user with the given username and authentication state."""
    user = MagicMock()
    user.username = username
    user.is_authenticated = is_authenticated
    return user


@given(
    username=username_strategy,
    config_username=config_username_strategy,
)
@settings(max_examples=100)
def test_personal_stats_access_matches_config(app, username, config_username):
    """Property 14: For any authenticated user, has_personal_stats_access returns
    True iff username matches the configured PERSONAL_STATS_USERNAME.
    """
    with app.app_context():
        # Override config to the generated value
        app.config['PERSONAL_STATS_USERNAME'] = config_username

        user = _make_user(username, is_authenticated=True)
        result = has_personal_stats_access(user)

        expected = (username == config_username)
        assert result == expected, (
            f"has_personal_stats_access returned {result} but expected {expected} "
            f"for username={username!r}, config={config_username!r}"
        )


@given(username=username_strategy)
@settings(max_examples=100)
def test_personal_stats_access_unauthenticated_always_false(app, username):
    """Property 14 (unauthenticated): Unauthenticated users never have access,
    regardless of username match.
    """
    with app.app_context():
        # Set config to match the username — even matching shouldn't grant access
        app.config['PERSONAL_STATS_USERNAME'] = username

        user = _make_user(username, is_authenticated=False)
        result = has_personal_stats_access(user)

        assert result is False, (
            f"has_personal_stats_access returned True for unauthenticated user "
            f"with username={username!r}"
        )


@given(username=username_strategy)
@settings(max_examples=100)
def test_personal_stats_default_config_equivalence(app, username):
    """Property 14 (default config): With default PERSONAL_STATS_USERNAME='Niklas',
    has_personal_stats_access produces the same result as the old hardcoded check
    `current_user.username == 'Niklas'`.
    """
    with app.app_context():
        # Use the default configuration value
        app.config['PERSONAL_STATS_USERNAME'] = 'Niklas'

        user = _make_user(username, is_authenticated=True)
        result = has_personal_stats_access(user)

        # The old hardcoded check
        old_check = (username == 'Niklas')

        assert result == old_check, (
            f"has_personal_stats_access returned {result} but old hardcoded check "
            f"returned {old_check} for username={username!r}"
        )
