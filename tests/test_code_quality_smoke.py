"""Smoke tests verifying raw SQL has been fully removed from route handlers.

These are static analysis tests that read the source file and assert the absence
of raw SQL patterns. They don't need database fixtures or app context.
"""

import os


ROUTES_PATH = os.path.join(os.path.dirname(__file__), '..', 'app', 'api', 'routes.py')


def _read_routes() -> str:
    with open(ROUTES_PATH) as f:
        return f.read()


def test_no_multiline_text_blocks():
    """Verify routes.py contains no multi-line text() blocks (Requirement 8.1)."""
    content = _read_routes()
    assert "text('''" not in content, "Found text(''' multi-line block in routes.py"
    assert 'text("""' not in content, 'Found text(""" multi-line block in routes.py'


def test_no_magic_stats_owner_literal():
    """Verify no magic_stats_owner string literals in routes.py (Requirement 8.2)."""
    content = _read_routes()
    assert 'magic_stats_owner' not in content, "Found 'magic_stats_owner' literal in routes.py"
