# Feature: service-layer-security-refactor, Property 7: Version bump arithmetic and history creation
"""
Property test verifying that version bump functions apply correct arithmetic
and create proper DeckVersionHistory entries.

- version_change() SHALL set (V, P, C) → (V, P, C+1) with matching history entry.
- version_patch() SHALL set (V, P, C) → (V, P+1, 0) with matching history entry.
- version_rework() SHALL set (V, P, C) → (V+1, 0, 0) with matching history entry.

**Validates: Requirements 6.1, 6.5**
"""
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, ColorIdentity, DeckVersionHistory
from app.services.deck_service import version_change, version_patch, version_rework
from app import db


# --- Strategies ---

# Non-negative integers for version components (keep small to avoid overflow edge cases)
version_component = st.integers(min_value=0, max_value=1000)

# Optional comment strings — either None or a short text
comment_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z'), min_codepoint=32, max_codepoint=126),
        min_size=0,
        max_size=50,
    ),
)


@st.composite
def version_state(draw):
    """Generate an arbitrary version tuple (V, P, C) and an optional comment."""
    v = draw(version_component)
    p = draw(version_component)
    c = draw(version_component)
    comment = draw(comment_strategy)
    return {'version': v, 'patch': p, 'change': c, 'comment': comment}


def _create_deck(db_session, version_data):
    """Helper to create a Deck with the given version state, satisfying FK constraints."""
    # Clear existing data
    db_session.query(DeckVersionHistory).delete()
    db_session.query(Deck).delete()
    db_session.query(Player).delete()
    db_session.query(ColorIdentity).delete()
    db_session.flush()

    # Insert FK dependencies
    ci = ColorIdentity(name='TestColor', amount=1)
    db_session.add(ci)
    db_session.flush()

    player = Player(id=1, name='TestPlayer')
    db_session.add(player)
    db_session.flush()

    # Create deck with specified version state
    deck = Deck(
        id=1,
        name='TestDeck',
        commander='TestCommander',
        player_id=1,
        color_identity='TestColor',
        active=True,
        version=version_data['version'],
        patch=version_data['patch'],
        change=version_data['change'],
    )
    db_session.add(deck)
    db_session.flush()

    return deck


@given(data=version_state())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_version_change_arithmetic_and_history(app, db_session, data):
    """Property 7 (version_change): For any Deck with version state (V, P, C),
    version_change() SHALL set the deck to (V, P, C+1) and create a DeckVersionHistory
    entry with previous=(V,P,C) and new=(V,P,C+1).
    """
    with app.app_context():
        V, P, C = data['version'], data['patch'], data['change']
        comment = data['comment']

        deck = _create_deck(db_session, data)

        # Call version_change
        result = version_change(deck, comment=comment)
        db_session.flush()

        # Verify deck version state
        assert deck.version == V, f"Expected Version={V}, got {deck.version}"
        assert deck.patch == P, f"Expected patch={P}, got {deck.patch}"
        assert deck.change == C + 1, f"Expected change={C + 1}, got {deck.change}"

        # Verify returned version string
        assert result == f"{V}.{P}.{C + 1}"

        # Verify DeckVersionHistory entry was created
        history = db_session.query(DeckVersionHistory).filter_by(deck_id=deck.id).one()
        assert history.change_type == 'change'
        assert history.previous_version == V
        assert history.previous_patch == P
        assert history.previous_change == C
        assert history.new_version == V
        assert history.new_patch == P
        assert history.new_change == C + 1
        assert history.comment == comment


@given(data=version_state())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_version_patch_arithmetic_and_history(app, db_session, data):
    """Property 7 (version_patch): For any Deck with version state (V, P, C),
    version_patch() SHALL set the deck to (V, P+1, 0) and create a DeckVersionHistory
    entry with previous=(V,P,C) and new=(V,P+1,0).
    """
    with app.app_context():
        V, P, C = data['version'], data['patch'], data['change']
        comment = data['comment']

        deck = _create_deck(db_session, data)

        # Call version_patch
        result = version_patch(deck, comment=comment)
        db_session.flush()

        # Verify deck version state
        assert deck.version == V, f"Expected Version={V}, got {deck.version}"
        assert deck.patch == P + 1, f"Expected patch={P + 1}, got {deck.patch}"
        assert deck.change == 0, f"Expected change=0, got {deck.change}"

        # Verify returned version string
        assert result == f"{V}.{P + 1}.0"

        # Verify DeckVersionHistory entry was created
        history = db_session.query(DeckVersionHistory).filter_by(deck_id=deck.id).one()
        assert history.change_type == 'patch'
        assert history.previous_version == V
        assert history.previous_patch == P
        assert history.previous_change == C
        assert history.new_version == V
        assert history.new_patch == P + 1
        assert history.new_change == 0
        assert history.comment == comment


@given(data=version_state())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_version_rework_arithmetic_and_history(app, db_session, data):
    """Property 7 (version_rework): For any Deck with version state (V, P, C),
    version_rework() SHALL set the deck to (V+1, 0, 0) and create a DeckVersionHistory
    entry with previous=(V,P,C) and new=(V+1,0,0).
    """
    with app.app_context():
        V, P, C = data['version'], data['patch'], data['change']
        comment = data['comment']

        deck = _create_deck(db_session, data)

        # Call version_rework
        result = version_rework(deck, comment=comment)
        db_session.flush()

        # Verify deck version state
        assert deck.version == V + 1, f"Expected Version={V + 1}, got {deck.version}"
        assert deck.patch == 0, f"Expected patch=0, got {deck.patch}"
        assert deck.change == 0, f"Expected change=0, got {deck.change}"

        # Verify returned version string
        assert result == f"{V + 1}.0.0"

        # Verify DeckVersionHistory entry was created
        history = db_session.query(DeckVersionHistory).filter_by(deck_id=deck.id).one()
        assert history.change_type == 'rework'
        assert history.previous_version == V
        assert history.previous_patch == P
        assert history.previous_change == C
        assert history.new_version == V + 1
        assert history.new_patch == 0
        assert history.new_change == 0
        assert history.comment == comment
