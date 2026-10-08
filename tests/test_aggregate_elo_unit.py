"""Unit tests for stats_service.get_aggregate_elo.

Covers averaging Elo over active, non-cEDH, rated decks; rounding to a whole
number; the None empty state when no deck qualifies; and exclusion of
inactive, null-rated, and cEDH decks.

Validates: Requirements 8.1, 8.2, 8.3, 8.4
"""

import pytest

from app.models import Player, Deck, ColorIdentity
from app.services.stats_service import get_aggregate_elo


@pytest.fixture()
def seeded(app, db_session):
    """Seed decks with varying active/cedh/elo for aggregate-Elo tests.

    Subject = player 1, with decks exercising every filter:
        Deck1: active, non-cEDH, elo 1500  -> counted
        Deck2: active, non-cEDH, elo 1600  -> counted
        Deck3: active, non-cEDH, elo 1700  -> counted  (avg of 1/2/3 = 1600)
        Deck4: INACTIVE,          elo 9000 -> excluded (not active)
        Deck5: active, non-cEDH, elo None  -> excluded (no rating)
        Deck6: active, cEDH,      elo 3000 -> excluded (cEDH)

    Player 2 owns one rated deck used to verify an exact rounding case.
    Player 3 owns only non-qualifying decks (empty-state check).
    """
    with app.app_context():
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        db_session.add(ColorIdentity(name="TestColor", amount=1))
        db_session.flush()

        for pid, name in [(1, "Subject"), (2, "Rounder"), (3, "NoRated")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        def add_deck(did, pid, elo, active=True, cedh=False):
            deck = Deck(
                id=did, name=f"Deck{did}", commander=f"Cmd{did}",
                player_id=pid, active=active, cedh=cedh,
                color_identity="TestColor", elo_rating=elo,
            )
            db_session.add(deck)
            # The Deck.elo_rating column has default=1500, so passing None at
            # construction time still persists 1500 on flush. To seed a genuine
            # NULL rating (an "unrated" deck), flush then explicitly null the
            # column and flush again.
            if elo is None:
                db_session.flush()
                deck.elo_rating = None
                db_session.flush()

        # Subject (player 1)
        add_deck(1, 1, 1500)
        add_deck(2, 1, 1600)
        add_deck(3, 1, 1700)
        add_deck(4, 1, 9000, active=False)
        add_deck(5, 1, None)
        add_deck(6, 1, 3000, cedh=True)

        # Player 2: 1500 and 1501 -> avg 1500.5 -> rounds to 1500 (bankers' nearest even)
        add_deck(10, 2, 1500)
        add_deck(11, 2, 1501)

        # Player 3: only an inactive and a null-elo deck -> no qualifiers
        add_deck(20, 3, 1500, active=False)
        add_deck(21, 3, None)

        db_session.flush()
        yield db_session


def test_average_over_active_rated_non_cedh_decks(app, seeded):
    with app.app_context():
        # (1500 + 1600 + 1700) / 3 = 1600; inactive/null/cEDH decks excluded.
        assert get_aggregate_elo(1) == 1600


def test_result_is_rounded_to_int(app, seeded):
    with app.app_context():
        result = get_aggregate_elo(2)
        assert isinstance(result, int)
        # (1500 + 1501) / 2 = 1500.5 -> round() yields 1500.
        assert result == 1500


def test_none_when_no_qualifying_decks(app, seeded):
    with app.app_context():
        # Player 3 has only an inactive deck and a null-elo deck.
        assert get_aggregate_elo(3) is None


def test_none_when_player_has_no_decks(app, seeded):
    with app.app_context():
        assert get_aggregate_elo(999) is None
