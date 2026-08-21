# Feature: raw-sql-to-orm, Property 6: Output Ordering Invariants
"""
Property test verifying that query result sets maintain ordering invariants:
(a) `get_deck_data` results are ordered by commander name ascending,
(b) `get_user_decks` results are ordered by deck name ascending,
(c) color images within any result are ordered alphabetically by color name, and
(d) tags within any result are ordered alphabetically.

**Validates: Requirements 3.6, 3.7, 3.8, 5.5, 5.6**
"""

import pytest
from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import (
    Player,
    Deck,
    Game,
    Participant,
    ColorIdentity,
    Color,
    ColorComponent,
    DeckTag,
)
from app.api.queries import get_deck_data, get_user_decks


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Commander names sampled to ensure variety in ordering tests
commander_names = st.sampled_from([
    "Atraxa", "Breya", "Codie", "Doran", "Emrakul",
    "Feather", "Golos", "Hapatra", "Isshin", "Jodah",
    "Kaalia", "Lathril", "Meren", "Najeela", "Omnath",
])

# Deck names sampled to ensure variety in ordering tests
deck_names = st.sampled_from([
    "Alpha Strike", "Big Mana", "Control Shell", "Dragon Hoard",
    "Enchantress", "Flicker Value", "Graveyard Shenanigans",
    "Human Tribal", "Infect Rush", "Jank Combo",
    "Knights Valor", "Landfall Fury", "Mill Machine",
    "Ninja Tempo", "Overrun Aggro",
])

# Color names that map to the MtG colors with images
available_colors = ["Black", "Blue", "Green", "Red", "White"]

# Tags
available_tags = [
    "aggro", "aristocrats", "combo", "control", "group-hug",
    "midrange", "mill", "spellslinger", "tokens", "voltron",
]


@st.composite
def ordering_scenario(draw):
    """Generate a scenario with multiple decks, color identities, and tags.

    Produces data suitable for testing all four ordering invariants:
    - Multiple active decks with different commanders (for deck-data ordering)
    - Multiple active decks with different names for one player (for user-decks ordering)
    - Color identities with multiple color components (for color image ordering)
    - Decks with multiple tags (for tag ordering)
    """
    # Generate 3-5 unique commander names
    num_decks = draw(st.integers(min_value=3, max_value=5))
    commanders = draw(
        st.lists(commander_names, min_size=num_decks, max_size=num_decks, unique=True)
    )

    # Generate deck names (unique for user-decks ordering test)
    names = draw(
        st.lists(deck_names, min_size=num_decks, max_size=num_decks, unique=True)
    )

    # Generate a color identity with 2-4 color components (for color ordering)
    num_colors = draw(st.integers(min_value=2, max_value=4))
    colors = draw(
        st.lists(
            st.sampled_from(available_colors),
            min_size=num_colors,
            max_size=num_colors,
            unique=True,
        )
    )

    # Generate 2-5 tags per deck (for tag ordering)
    num_tags = draw(st.integers(min_value=2, max_value=5))
    tags = draw(
        st.lists(
            st.sampled_from(available_tags),
            min_size=num_tags,
            max_size=num_tags,
            unique=True,
        )
    )

    return {
        "num_decks": num_decks,
        "commanders": commanders,
        "deck_names": names,
        "colors": colors,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@given(data=ordering_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_deck_data_ordered_by_commander(app, db_session, data):
    """Property 6a: get_deck_data results are ordered by commander name ascending."""
    with app.app_context():
        # Clean existing data
        db_session.query(DeckTag).delete()
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Setup: single color identity, single player, multiple active decks
        ci = ColorIdentity(name="TestCI", amount=1)
        db_session.add(ci)
        player = Player(id=1, name="TestPlayer")
        db_session.add(player)
        db_session.flush()

        for i, commander in enumerate(data["commanders"], start=1):
            deck = Deck(
                id=i,
                name=f"Deck_{i}",
                commander=commander,
                player_id=1,
                active=True,
                color_identity="TestCI",
            )
            db_session.add(deck)
        db_session.flush()

        results = get_deck_data(db_session)

        # Verify results are ordered by commander ascending
        commanders_in_results = [r["commander"] for r in results]
        assert commanders_in_results == sorted(commanders_in_results), (
            f"Deck data not ordered by commander. Got: {commanders_in_results}"
        )


@given(data=ordering_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_user_decks_ordered_by_name(app, db_session, data):
    """Property 6b: get_user_decks results are ordered by deck name ascending."""
    with app.app_context():
        # Clean existing data
        db_session.query(DeckTag).delete()
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Setup: single color identity, single player, multiple active decks
        ci = ColorIdentity(name="TestCI", amount=1)
        db_session.add(ci)
        player = Player(id=1, name="TestPlayer")
        db_session.add(player)
        db_session.flush()

        for i, name in enumerate(data["deck_names"], start=1):
            deck = Deck(
                id=i,
                name=name,
                commander=f"Commander_{i}",
                player_id=1,
                active=True,
                color_identity="TestCI",
            )
            db_session.add(deck)
        db_session.flush()

        results = get_user_decks(db_session, player_id=1)

        # Verify results are ordered by deck name ascending
        names_in_results = [r["name"] for r in results]
        assert names_in_results == sorted(names_in_results), (
            f"User decks not ordered by name. Got: {names_in_results}"
        )


@given(data=ordering_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_color_images_ordered_alphabetically(app, db_session, data):
    """Property 6c: Color images within any result are ordered alphabetically by color name."""
    with app.app_context():
        # Clean existing data
        db_session.query(DeckTag).delete()
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Setup color identity with multiple color components
        ci = ColorIdentity(name="MultiColor", amount=len(data["colors"]))
        db_session.add(ci)
        db_session.flush()

        # Create colors with images
        for color_name in data["colors"]:
            color = Color(
                name=color_name,
                abbreviation=color_name[0],
                img=f"/img/{color_name.lower()}.svg",
            )
            db_session.add(color)
        db_session.flush()

        # Create color components in a non-alphabetical order (reversed)
        for color_name in reversed(data["colors"]):
            cc = ColorComponent(color_identity="MultiColor", color=color_name)
            db_session.add(cc)
        db_session.flush()

        # Create a player and deck
        player = Player(id=1, name="TestPlayer")
        db_session.add(player)
        db_session.flush()

        deck = Deck(
            id=1,
            name="Test Deck",
            commander="TestCommander",
            player_id=1,
            active=True,
            color_identity="MultiColor",
        )
        db_session.add(deck)
        db_session.flush()

        # Test via get_deck_data
        deck_results = get_deck_data(db_session)
        assert len(deck_results) == 1
        color_imgs = deck_results[0]["color_imgs"]

        # Expected order: sorted by color name
        expected_imgs = [
            f"/img/{c.lower()}.svg" for c in sorted(data["colors"])
        ]
        assert color_imgs == expected_imgs, (
            f"Color images not ordered alphabetically. Got: {color_imgs}, expected: {expected_imgs}"
        )

        # Also verify via get_user_decks
        user_results = get_user_decks(db_session, player_id=1)
        assert len(user_results) == 1
        assert user_results[0]["color_imgs"] == expected_imgs, (
            f"User deck color images not ordered alphabetically. "
            f"Got: {user_results[0]['color_imgs']}, expected: {expected_imgs}"
        )


@given(data=ordering_scenario())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_tags_ordered_alphabetically(app, db_session, data):
    """Property 6d: Tags within any result are ordered alphabetically."""
    with app.app_context():
        # Clean existing data
        db_session.query(DeckTag).delete()
        db_session.query(ColorComponent).delete()
        db_session.query(Color).delete()
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Setup
        ci = ColorIdentity(name="TestCI", amount=1)
        db_session.add(ci)
        player = Player(id=1, name="TestPlayer")
        db_session.add(player)
        db_session.flush()

        deck = Deck(
            id=1,
            name="Tagged Deck",
            commander="TestCommander",
            player_id=1,
            active=True,
            color_identity="TestCI",
        )
        db_session.add(deck)
        db_session.flush()

        # Add tags in reversed order to ensure query sorts them
        for tag_name in reversed(data["tags"]):
            tag = DeckTag(deck_id=1, tag=tag_name)
            db_session.add(tag)
        db_session.flush()

        # Test via get_deck_data
        deck_results = get_deck_data(db_session)
        assert len(deck_results) == 1
        tags = deck_results[0]["tags"]

        expected_tags = sorted(data["tags"])
        assert tags == expected_tags, (
            f"Tags not ordered alphabetically in deck data. Got: {tags}, expected: {expected_tags}"
        )

        # Also verify via get_user_decks
        user_results = get_user_decks(db_session, player_id=1)
        assert len(user_results) == 1
        assert user_results[0]["tags"] == expected_tags, (
            f"Tags not ordered alphabetically in user decks. "
            f"Got: {user_results[0]['tags']}, expected: {expected_tags}"
        )
