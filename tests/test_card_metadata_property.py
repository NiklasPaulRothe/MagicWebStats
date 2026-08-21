# Feature: service-layer-security-refactor, Property 11: Card metadata grouped query equivalence
"""
Property test verifying that `get_card_usage_counts()` produces the same
(name, count) pairs as the original O(n×m) nested-loop implementation
in `app/cards/routes.py`'s `card_meta()`.

**Validates: Requirements 8.1, 8.3**
"""
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Deck, DeckComponent, ColorIdentity, Card
from app.services.stats_service import get_card_usage_counts
from app import db


# --- Strategies ---

# Short non-empty strings for names
name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=15,
)

# Card IDs: either None (no card reference) or a short string
card_id_strategy = st.one_of(st.none(), st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=10,
))

# Decksite values: some containing 'archidekt', some not, some None
decksite_strategy = st.one_of(
    st.none(),
    st.just('archidekt'),
    st.just('https://archidekt.com/decks/12345'),
    st.just('moxfield'),
    st.just(''),
)


@st.composite
def card_metadata_scenario(draw):
    """Generate a consistent set of Player, Deck, Card, and DeckComponent records.

    Ensures FK constraints are satisfied:
    - Each Deck references an existing Player
    - Each Deck references the fixed ColorIdentity 'TestCI'
    - DeckComponent.card_id references an existing Card or is None
    - DeckComponent.deck_id references an existing Deck
    """
    # Generate 1-3 players
    num_players = draw(st.integers(min_value=1, max_value=3))
    player_names = draw(
        st.lists(name_strategy, min_size=num_players, max_size=num_players, unique=True)
    )
    players = [{'id': i + 1, 'name': name} for i, name in enumerate(player_names)]

    # Generate 1-5 decks with varying Active and decksite combinations
    num_decks = draw(st.integers(min_value=1, max_value=5))
    decks = []
    for i in range(num_decks):
        player_id = draw(st.sampled_from([p['id'] for p in players]))
        active = draw(st.booleans())
        decksite = draw(decksite_strategy)
        decks.append({
            'id': i + 1,
            'name': draw(name_strategy),
            'commander': draw(name_strategy),
            'player_id': player_id,
            'active': active,
            'color_identity': 'TestCI',
            'decksite': decksite,
        })

    # Generate 0-3 cards to use as FK targets
    num_cards = draw(st.integers(min_value=1, max_value=3))
    card_ids = [f"card_{i}" for i in range(num_cards)]

    # Generate 0-15 deck components
    num_components = draw(st.integers(min_value=0, max_value=15))
    components = []
    # Use a small pool of card names to increase aggregation
    card_name_pool = draw(
        st.lists(name_strategy, min_size=1, max_size=5, unique=True)
    )
    for i in range(num_components):
        deck_id = draw(st.sampled_from([d['id'] for d in decks]))
        # card_id: either None or one of our card IDs
        has_card = draw(st.booleans())
        card_id = draw(st.sampled_from(card_ids)) if has_card else None
        comp_name = draw(st.sampled_from(card_name_pool))
        count = draw(st.integers(min_value=0, max_value=4))
        components.append({
            'id': i + 1,
            'deck_id': deck_id,
            'card_id': card_id,
            'name': comp_name,
            'count': count,
        })

    return {
        'players': players,
        'decks': decks,
        'card_ids': card_ids,
        'components': components,
    }


def reference_card_usage_counts(session):
    """Original O(n×m) nested-loop implementation from card_meta() as reference.

    Reproduces the exact behavior of the original code:
    1. Get distinct names from DeckComponent where card_id is not None
    2. Get all DeckComponent entries where card_id is not None
    3. Get active deck IDs where decksite contains 'archidekt'
    4. For each name, loop all entries summing count for those in active decks
    5. Only include entries where count > 0
    """
    from sqlalchemy import and_

    names = session.query(DeckComponent.name).filter(
        DeckComponent.card_id.isnot(None)
    ).distinct().all()

    entries = DeckComponent.query.filter(DeckComponent.card_id.isnot(None)).all()

    decks = Deck.query.filter(
        and_(Deck.decksite.contains('archidekt'), Deck.active == True)  # noqa: E712
    ).all()
    active_decks = [deck.id for deck in decks]

    cards = []
    for name in names:
        count = 0
        for entry in entries:
            if entry.name == name[0] and entry.deck_id in active_decks:
                count += entry.count
        if count > 0:
            cards.append({
                "name": name[0],
                "count": count,
            })

    return cards


@given(data=card_metadata_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_card_metadata_grouped_query_equivalence(app, db_session, data):
    """Property 11: get_card_usage_counts() SHALL produce the same (name, count)
    pairs as the original O(n×m) nested-loop implementation, for any set of
    DeckComponent, Deck, and Player records where some decks are active and have
    decksite containing 'archidekt'.
    """
    with app.app_context():
        # Clear existing data (order matters for FK constraints)
        db_session.query(DeckComponent).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.query(Card).delete()
        db_session.flush()

        # Insert fixed ColorIdentity to satisfy FK
        ci = ColorIdentity(name='TestCI', amount=1)
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
                decksite=deck_data['decksite'],
            )
            db_session.add(deck)
        db_session.flush()

        # Insert cards (to satisfy FK on DeckComponent.card_id)
        for card_id in data['card_ids']:
            card = Card(
                id=card_id,
                oracle_id=f"oracle_{card_id}",
                name=f"Card {card_id}",
                cmc=0,
                type_line="Creature",
                layout="normal",
                set_code="TST",
                set_name="Test Set",
                rarity="common",
            )
            db_session.add(card)
        db_session.flush()

        # Insert deck components
        for comp_data in data['components']:
            comp = DeckComponent(
                id=comp_data['id'],
                deck_id=comp_data['deck_id'],
                card_id=comp_data['card_id'],
                name=comp_data['name'],
                count=comp_data['count'],
            )
            db_session.add(comp)
        db_session.flush()

        # Run both implementations
        new_result = get_card_usage_counts()
        reference_result = reference_card_usage_counts(db_session)

        # Compare as sets of (Name, Count) tuples since order may differ
        new_set = {(item['name'], item['count']) for item in new_result}
        ref_set = {(item['name'], item['count']) for item in reference_result}

        assert new_set == ref_set, (
            f"Results differ:\n"
            f"  new (grouped query): {sorted(new_set)}\n"
            f"  ref (nested loop):   {sorted(ref_set)}\n"
            f"  only in new: {sorted(new_set - ref_set)}\n"
            f"  only in ref: {sorted(ref_set - new_set)}"
        )
