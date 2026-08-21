# Feature: service-layer-security-refactor, Property 8: Archive/dearchive round-trip
"""Property-based test for archive/dearchive round-trip.

**Validates: Requirements 6.2, 6.3**

For any Deck, calling archive_deck() followed by dearchive_deck() SHALL restore
deck.Active to True. Conversely, archive_deck() alone SHALL set deck.Active to False.
"""

from dataclasses import dataclass

from hypothesis import given, settings, strategies as st

from app.services.deck_service import archive_deck, dearchive_deck


@dataclass
class FakeDeck:
    """Minimal deck-like object with an active attribute for testing."""

    active: bool


# Strategy: generate a deck with an arbitrary initial active state
deck_strategy = st.booleans().map(lambda active: FakeDeck(active=active))


@given(deck=deck_strategy)
@settings(max_examples=100)
def test_archive_sets_active_false(deck):
    """Property 8a: archive_deck() SHALL set deck.active to False.

    Regardless of the initial active state, archiving always deactivates.
    """
    archive_deck(deck)
    assert deck.active is False, (
        f"archive_deck() should set active=False, got active={deck.active}"
    )


@given(deck=deck_strategy)
@settings(max_examples=100)
def test_dearchive_sets_active_true(deck):
    """Property 8b: dearchive_deck() SHALL set deck.active to True.

    Regardless of the initial active state, dearchiving always activates.
    """
    dearchive_deck(deck)
    assert deck.active is True, (
        f"dearchive_deck() should set active=True, got active={deck.active}"
    )


@given(deck=deck_strategy)
@settings(max_examples=100)
def test_archive_then_dearchive_roundtrip(deck):
    """Property 8c: archive_deck() followed by dearchive_deck() SHALL restore active to True.

    The full round-trip (archive then dearchive) always results in an active deck,
    regardless of the initial state.
    """
    archive_deck(deck)
    assert deck.active is False, (
        f"After archive_deck(), active should be False, got {deck.active}"
    )

    dearchive_deck(deck)
    assert deck.active is True, (
        f"After archive+dearchive round-trip, active should be True, got {deck.active}"
    )
