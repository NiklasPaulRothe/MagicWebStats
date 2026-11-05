"""Unit tests for stats_service.get_aggregate_elo.

Covers averaging the deck rating over active, non-cEDH, rated decks; rounding
to a whole number; the None empty state when no deck qualifies; and exclusion
of inactive, unrated (NULL), and cEDH decks.

A deck counts as "rated" only when it has a non-NULL ``elo_rating`` AND at least
five counted games (``elo_games >= 5``). On the new 0-1000 scale 0 is a legal
rating, so the old ``elo_rating > 0`` sentinel was replaced by this NULL + games
gate — these tests exercise that.

Validates: Requirements 8.1, 8.2, 8.3, 8.4
"""

import pytest

from app.models import Player, Deck, ColorIdentity
from app.services.stats_service import get_aggregate_elo


@pytest.fixture()
def seeded(app, db_session):
    """Seed decks with varying active/cedh/elo/games for aggregate-Elo tests.

    Subject = player 1, with decks exercising every filter:
        Deck1: active, non-cEDH, elo 400, 12 games  -> counted
        Deck2: active, non-cEDH, elo 500, 12 games  -> counted
        Deck3: active, non-cEDH, elo 600, 12 games  -> counted  (avg = 500)
        Deck4: INACTIVE,          elo 900, 12 games -> excluded (not active)
        Deck5: active, non-cEDH, elo None           -> excluded (no rating)
        Deck6: active, cEDH,      elo 800, 12 games -> excluded (cEDH)
        Deck7: active, non-cEDH, elo 300, 2 games   -> excluded (<5 games gate)

    Player 2 owns two rated decks used to verify an exact rounding case.
    Player 3 owns only non-qualifying decks (empty-state check).
    Player 4 owns only a below-gate deck (gate-only empty-state check).
    """
    with app.app_context():
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        db_session.add(ColorIdentity(name="TestColor", amount=1))
        db_session.flush()

        for pid, name in [(1, "Subject"), (2, "Rounder"), (3, "NoRated"), (4, "BelowGate")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        def add_deck(did, pid, elo, games=12, active=True, cedh=False):
            deck = Deck(
                id=did, name=f"Deck{did}", commander=f"Cmd{did}",
                player_id=pid, active=active, cedh=cedh,
                color_identity="TestColor", elo_rating=elo, elo_games=games,
            )
            db_session.add(deck)
            # elo_rating has no default now (unrated = NULL), but flushing after
            # construction keeps the explicit None robust across backends.
            if elo is None:
                db_session.flush()
                deck.elo_rating = None
                db_session.flush()

        # Subject (player 1)
        add_deck(1, 1, 400)
        add_deck(2, 1, 500)
        add_deck(3, 1, 600)
        add_deck(4, 1, 900, active=False)
        add_deck(5, 1, None)
        add_deck(6, 1, 800, cedh=True)
        # Below the 5-game gate: a real rating but too few games to trust it.
        add_deck(7, 1, 300, games=2)

        # Player 2: 500 and 501 -> avg 500.5 -> rounds to 500 (bankers' nearest even)
        add_deck(10, 2, 500)
        add_deck(11, 2, 501)

        # Player 3: only an inactive and an unrated (NULL) deck -> no qualifiers
        add_deck(20, 3, 500, active=False)
        add_deck(21, 3, None)

        # Player 4: only an active, non-cEDH deck below the games gate
        # -> no qualifiers.
        add_deck(30, 4, 300, games=2)

        db_session.flush()
        yield db_session


def test_average_over_active_rated_non_cedh_decks(app, seeded):
    with app.app_context():
        # (400 + 500 + 600) / 3 = 500; inactive/null/cEDH/below-gate decks excluded.
        assert get_aggregate_elo(1) == 500


def test_below_gate_decks_excluded(app, seeded):
    """A deck below the 5-game gate must not enter the average.

    Player 1 owns an active, non-cEDH deck with elo_rating=300 but only 2 games
    (Deck7). Were it counted, (400 + 500 + 600 + 300) / 4 = 450. Because the
    elo_games >= 5 gate excludes it, the average stays 500 over the three
    genuinely rated decks.
    """
    with app.app_context():
        assert get_aggregate_elo(1) == 500


def test_none_when_only_below_gate_decks(app, seeded):
    """A player whose only deck is below the games gate yields None."""
    with app.app_context():
        # Player 4 owns a single active, non-cEDH deck with only 2 games.
        assert get_aggregate_elo(4) is None


def test_result_is_rounded_to_int(app, seeded):
    with app.app_context():
        result = get_aggregate_elo(2)
        assert isinstance(result, int)
        # (500 + 501) / 2 = 500.5 -> round() yields 500 (bankers' rounding).
        assert result == 500


def test_none_when_no_qualifying_decks(app, seeded):
    with app.app_context():
        # Player 3 has only an inactive deck and an unrated (NULL) deck.
        assert get_aggregate_elo(3) is None


def test_none_when_player_has_no_decks(app, seeded):
    with app.app_context():
        assert get_aggregate_elo(999) is None
