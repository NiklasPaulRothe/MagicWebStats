# Feature: service-layer-security-refactor, Property 2: Stats service equivalence (get_players)
"""Property-based test for get_players equivalence.

**Validates: Requirements 3.1, 3.6**

For any set of Player records in the database, get_players() SHALL return
the same sorted list of player names as iterating
Player.query.order_by(Player.name).all() and extracting each .name.
"""

import pytest
from hypothesis import given, settings, strategies as st

from app import db
from app.models import Player
from app.services.stats_service import get_players


# Strategy: generate unique, non-empty player names
# Use printable characters excluding control chars for realistic names
player_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"),
                           blacklist_characters="\x00"),
    min_size=1,
    max_size=50,
)

# Generate lists of unique player names (1 to 20 players)
player_names_strategy = st.lists(
    player_name_strategy,
    min_size=1,
    max_size=20,
    unique=True,
)


@given(names=player_names_strategy)
@settings(max_examples=100)
def test_get_players_returns_sorted_names(app, names):
    """Property 2: Stats service equivalence (get_players).

    For any set of Player records inserted into the database,
    get_players() returns the same sorted list as sorting the
    input names alphabetically.
    """
    with app.app_context():
        # Start clean
        db.session.rollback()

        # Remove any existing players
        db.session.query(Player).delete()
        db.session.flush()

        # Insert Player records with the generated names
        for name in names:
            player = Player(name=name)
            db.session.add(player)
        db.session.flush()

        # Call the service function under test
        result = get_players()

        # Compute expected result: same as the reference implementation
        expected = sorted(names)

        # Verify equivalence
        assert result == expected, (
            f"get_players() returned {result!r}, expected sorted names {expected!r}"
        )

        # Cleanup
        db.session.rollback()
