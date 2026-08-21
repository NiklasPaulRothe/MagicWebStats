# Feature: service-layer-security-refactor, Property 3: Stats service equivalence (get_active_decks)
"""
Property test verifying that `get_active_decks()` returns the same list of
(name, commander, player_name) tuples as the original N+1 implementation
that queries each deck's player individually.

**Validates: Requirements 3.2, 3.6**
"""
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, ColorIdentity
from app.services.stats_service import get_active_decks


# --- Strategies ---

# Short non-empty strings for names (avoiding problematic characters)
name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=15,
)


@st.composite
def deck_and_player_data(draw):
    """Generate a consistent set of Player and Deck records where some decks are active and some are not.

    Ensures foreign key constraints are satisfied:
    - Each Deck references an existing Player via Player.id
    - Each Deck references an existing ColorIdentity via Color_Identity
    - A fixed ColorIdentity 'Mono-Blue' is always created to satisfy the FK
    """
    # Generate 1-5 players with unique names
    num_players = draw(st.integers(min_value=1, max_value=5))
    player_names = draw(
        st.lists(
            name_strategy,
            min_size=num_players,
            max_size=num_players,
            unique=True,
        )
    )
    players = [{'id': i + 1, 'name': name} for i, name in enumerate(player_names)]

    # Generate 0-10 decks, each assigned to a random player
    num_decks = draw(st.integers(min_value=0, max_value=10))
    decks = []
    for i in range(num_decks):
        player_id = draw(st.sampled_from([p['id'] for p in players]))
        deck_name = draw(name_strategy)
        commander = draw(name_strategy)
        active = draw(st.booleans())
        decks.append({
            'id': i + 1,
            'name': deck_name,
            'commander': commander,
            'player_id': player_id,
            'active': active,
            'color_identity': 'Mono-Blue',
        })

    return {'players': players, 'decks': decks}


def reference_get_decks():
    """Original N+1 implementation of get_decks() used as reference.

    This reproduces the exact behavior of the original code for equivalence testing.
    """
    deck_list = []
    decks = Deck.query.order_by(Deck.commander).all()
    for deck in decks:
        player = Player.query.filter_by(id=deck.player_id).first()
        if deck.active:
            tupel = (deck.name, deck.commander, player.name)
            deck_list.append(tupel)
    return deck_list


@given(data=deck_and_player_data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_get_active_decks_equivalence(app, db_session, data):
    """Property 3: get_active_decks() SHALL return the same list of (name, commander,
    player_name) tuples as the original N+1 implementation that queries each deck's
    player individually, for any set of Deck and Player records where some decks are
    active and some are not.
    """
    with app.app_context():
        # Clear existing data (order matters for FK constraints)
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert fixed ColorIdentity to satisfy FK
        ci = ColorIdentity(name='Mono-Blue', amount=1)
        db_session.add(ci)
        db_session.flush()

        # Insert players
        for player_data in data['players']:
            player = Player(id=player_data['id'], name=player_data['name'])
            db_session.add(player)
        db_session.flush()

        # Insert decks
        for deck_data in data['decks']:
            deck = Deck(
                id=deck_data['id'],
                name=deck_data['name'],
                commander=deck_data['commander'],
                player_id=deck_data['player_id'],
                active=deck_data['active'],
                color_identity=deck_data['color_identity'],
            )
            db_session.add(deck)
        db_session.flush()

        # Run both implementations
        new_result = get_active_decks()
        reference_result = reference_get_decks()

        # Both should return the same list (already ordered by Commander)
        assert new_result == reference_result, (
            f"Results differ:\n  new: {new_result}\n  ref: {reference_result}"
        )
