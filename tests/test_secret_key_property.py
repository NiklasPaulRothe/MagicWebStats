# Feature: service-layer-security-refactor, Property 15: Secret key fail-fast
"""Property-based test for secret key fail-fast behavior.

**Validates: Requirements 15.2, 15.3**

For any value of the SECRET_KEY environment variable, Config SHALL raise a
RuntimeError during class definition if and only if the value is empty or unset.
For any non-empty string value, Config.SECRET_KEY SHALL equal that string.
"""

import importlib
import os
import sys
from unittest.mock import patch

import pytest
from hypothesis import given, settings, strategies as st, HealthCheck


def _reload_config_with_env(env_dict):
    """Reload config module with a controlled environment.

    Patches load_dotenv to prevent it from reading the .env file,
    and sets os.environ to the provided dict for SECRET_KEY resolution.
    """
    # Remove cached module so it re-evaluates
    if "config" in sys.modules:
        del sys.modules["config"]

    with patch("dotenv.load_dotenv", return_value=None):
        # Temporarily replace SECRET_KEY in environ
        old_val = os.environ.get("SECRET_KEY")
        has_old = "SECRET_KEY" in os.environ

        try:
            if "SECRET_KEY" in env_dict:
                os.environ["SECRET_KEY"] = env_dict["SECRET_KEY"]
            elif "SECRET_KEY" in os.environ:
                del os.environ["SECRET_KEY"]

            import config
            return config
        finally:
            # Restore original state
            if has_old:
                os.environ["SECRET_KEY"] = old_val
            elif "SECRET_KEY" in os.environ:
                del os.environ["SECRET_KEY"]


def _reload_config_raises(env_dict):
    """Reload config module expecting a RuntimeError.

    Same env manipulation as _reload_config_with_env but expects failure.
    """
    if "config" in sys.modules:
        del sys.modules["config"]

    with patch("dotenv.load_dotenv", return_value=None):
        old_val = os.environ.get("SECRET_KEY")
        has_old = "SECRET_KEY" in os.environ

        try:
            if "SECRET_KEY" in env_dict:
                os.environ["SECRET_KEY"] = env_dict["SECRET_KEY"]
            elif "SECRET_KEY" in os.environ:
                del os.environ["SECRET_KEY"]

            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                import config  # noqa: F401
        finally:
            # Restore original state
            if has_old:
                os.environ["SECRET_KEY"] = old_val
            elif "SECRET_KEY" in os.environ:
                del os.environ["SECRET_KEY"]


# Strategy: non-empty strings without null bytes (null bytes are invalid in env vars)
valid_secret_keys = st.text(
    alphabet=st.characters(blacklist_characters="\x00"),
    min_size=1,
)


@given(secret_key=valid_secret_keys)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_non_empty_secret_key_loads_successfully(secret_key):
    """Property 15a: For any non-empty string, Config.SECRET_KEY SHALL equal that string.

    When SECRET_KEY env var is set to a non-empty value, Config class definition
    succeeds and Config.SECRET_KEY holds the exact value.
    """
    config = _reload_config_with_env({"SECRET_KEY": secret_key})
    assert config.Config.SECRET_KEY == secret_key, (
        f"Expected Config.SECRET_KEY to be {secret_key!r}, "
        f"got {config.Config.SECRET_KEY!r}"
    )


def test_empty_secret_key_raises_runtime_error():
    """Property 15b: Empty SECRET_KEY SHALL raise RuntimeError.

    When SECRET_KEY env var is set to an empty string, Config class definition
    raises a RuntimeError.
    """
    _reload_config_raises({"SECRET_KEY": ""})


def test_unset_secret_key_raises_runtime_error():
    """Property 15c: Unset SECRET_KEY SHALL raise RuntimeError.

    When SECRET_KEY env var is not set at all, Config class definition
    raises a RuntimeError.
    """
    _reload_config_raises({})  # No SECRET_KEY key means unset


@given(secret_key=st.just(""))
@settings(max_examples=5, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_empty_string_always_raises(secret_key):
    """Property 15d: Empty string always triggers fail-fast.

    Validates that the empty string case consistently raises RuntimeError
    across multiple hypothesis iterations.
    """
    _reload_config_raises({"SECRET_KEY": secret_key})
