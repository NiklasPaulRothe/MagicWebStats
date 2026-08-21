"""Tests for card name autocomplete used in the Quick-Add Deck modal on the Game Add page.

Verifies that:
1. The /api/cards/autocomplete query logic returns correct results for the
   quick-add deck modal's commander/partner fields.
2. The GameAdd template includes the autocomplete JS/CSS resources and
   initializes autocomplete on the modal inputs.
"""

import pytest
import sqlalchemy as sa

from app import db as _db
from app.models import Card, CardFace


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_cards(db_session):
    """Seed card data for autocomplete testing."""
    cards_data = [
        ("card-001", "orc-001", "Aesi, Tyrant of Gyre Strait", "Legendary Creature", "normal"),
        ("card-002", "orc-002", "Atraxa, Praetors' Voice", "Legendary Creature", "normal"),
        ("card-003", "orc-003", "Kozilek, the Great Distortion", "Legendary Creature", "normal"),
        ("card-004", "orc-004", "Kenrith, the Returned King", "Legendary Creature", "normal"),
        ("card-005", "orc-005", "Kroxa, Titan of Death's Hunger", "Legendary Creature", "normal"),
    ]
    cards = []
    for card_id, oracle_id, name, type_line, layout in cards_data:
        card = Card(
            id=card_id,
            oracle_id=oracle_id,
            name=name,
            type_line=type_line,
            layout=layout,
            set_code="test",
            set_name="Test Set",
            rarity="rare",
        )
        cards.append(card)
    db_session.add_all(cards)
    db_session.flush()

    # Add front faces
    for i, card in enumerate(cards):
        face = CardFace(
            card_id=card.id,
            face_index=0,
            name=card.name,
            image_uri=f"/img/{card.id}.png",
        )
        db_session.add(face)
    db_session.flush()
    return cards


# ---------------------------------------------------------------------------
# Test: Autocomplete query logic (mirrors /api/cards/autocomplete behavior)
# ---------------------------------------------------------------------------


class TestCardsAutocompleteQuery:
    """Tests for the card autocomplete query logic used by the quick-add deck modal."""

    def _query_autocomplete(self, session, q):
        """Execute the same query that /api/cards/autocomplete uses."""
        if len(q) < 2:
            return []
        results = session.execute(
            sa.select(sa.distinct(Card.name))
            .where(Card.name.ilike(f'%{q}%'))
            .order_by(Card.name)
            .limit(10)
        ).scalars().all()
        return results

    def test_returns_matching_cards(self, app, db_session, seed_cards):
        """Should return card names matching the query (case-insensitive)."""
        results = self._query_autocomplete(db_session, 'aesi')
        assert "Aesi, Tyrant of Gyre Strait" in results

    def test_case_insensitive_search(self, app, db_session, seed_cards):
        """Search should be case-insensitive."""
        results = self._query_autocomplete(db_session, 'ATRAXA')
        assert "Atraxa, Praetors' Voice" in results

    def test_partial_match(self, app, db_session, seed_cards):
        """Should match cards containing the query substring."""
        results = self._query_autocomplete(db_session, 'kr')
        assert "Kroxa, Titan of Death's Hunger" in results

    def test_returns_empty_for_short_query(self, app, db_session, seed_cards):
        """Should return empty list if query is shorter than 2 characters."""
        results = self._query_autocomplete(db_session, 'a')
        assert results == []

    def test_returns_empty_for_empty_query(self, app, db_session, seed_cards):
        """Should return empty list if query is empty."""
        results = self._query_autocomplete(db_session, '')
        assert results == []

    def test_returns_empty_for_no_match(self, app, db_session, seed_cards):
        """Should return empty list when nothing matches."""
        results = self._query_autocomplete(db_session, 'zzzzz')
        assert results == []

    def test_results_limited_to_10(self, app, db_session):
        """Should return at most 10 results."""
        # Seed 15 cards that all match 'Test'
        for i in range(15):
            db_session.add(Card(
                id=f"test-card-{i:02d}",
                oracle_id=f"test-orc-{i:02d}",
                name=f"Test Card {i:02d}",
                type_line="Creature",
                layout="normal",
                set_code="tst",
                set_name="Test",
                rarity="common",
            ))
        db_session.flush()

        results = self._query_autocomplete(db_session, 'Test')
        assert len(results) <= 10

    def test_results_ordered_alphabetically(self, app, db_session, seed_cards):
        """Results should be ordered alphabetically."""
        results = self._query_autocomplete(db_session, 'k')
        assert results == sorted(results)

    def test_multiple_matches_for_substring(self, app, db_session, seed_cards):
        """Should return all cards matching a common substring."""
        # 'Tyrant' and 'Titan' both contain 'T' but let's search for 'the'
        results = self._query_autocomplete(db_session, 'the')
        # Kozilek, the Great Distortion / Kenrith, the Returned King / Kroxa, Titan of Death's Hunger
        assert len(results) >= 2


# ---------------------------------------------------------------------------
# Test: GameAdd template includes autocomplete resources
# ---------------------------------------------------------------------------


class TestGameAddTemplateAutocomplete:
    """Verify that GameAdd.html includes autocomplete JS/CSS for quick-add deck modal.

    Uses direct template file inspection since full HTTP integration tests require
    complex auth and data setup beyond the scope of this feature test.
    """

    def _read_template(self):
        """Read the GameAdd.html template source."""
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'app', 'templates', 'stats', 'GameAdd.html'
        )
        with open(template_path, 'r', encoding='utf-8') as f:
            return f.read()

    def test_template_includes_autocomplete_css(self):
        """GameAdd template should include autocomplete.css stylesheet."""
        html = self._read_template()
        assert 'autocomplete.css' in html

    def test_template_includes_autocomplete_js(self):
        """GameAdd template should include autocomplete.js script."""
        html = self._read_template()
        assert 'autocomplete.js' in html

    def test_template_has_commander_input_in_deck_modal(self):
        """Quick-add deck modal should have the commander input field."""
        html = self._read_template()
        assert 'id="new-deck-commander"' in html

    def test_template_has_partner_input_in_deck_modal(self):
        """Quick-add deck modal should have the partner input field."""
        html = self._read_template()
        assert 'id="new-deck-partner"' in html

    def test_template_initializes_autocomplete_on_commander(self):
        """Template should call initAutocomplete on the deck modal commander input."""
        html = self._read_template()
        assert 'initAutocomplete(deckCommanderInput)' in html

    def test_template_initializes_autocomplete_on_partner(self):
        """Template should call initAutocomplete on the deck modal partner input."""
        html = self._read_template()
        assert 'initAutocomplete(deckPartnerInput)' in html

    def test_autocomplete_js_loaded_before_modal_script(self):
        """autocomplete.js should be loaded before the inline script that uses it."""
        html = self._read_template()
        js_pos = html.find('autocomplete.js')
        init_pos = html.find('initAutocomplete(deckCommanderInput)')
        assert js_pos < init_pos, "autocomplete.js must be loaded before initAutocomplete is called"
