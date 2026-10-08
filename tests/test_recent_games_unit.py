"""Unit tests for stats_service.get_recent_games.

Covers ordering (newest first), limit, win/loss derivation via Game.winner_id,
null-turn handling, pod size, deck name, and cEDH exclusion.

Validates: Requirements 4.1, 4.2, 4.3, 4.4
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_recent_games


@pytest.fixture()
def seeded(app, db_session):
    """Seed a small, deterministic data set for recent-games tests.

    Players:
        1 = subject, 2/3/4 = opponents.

    Games (all include subject player 1 as a participant):
        g1  2025-01-01  non-cEDH  winner=1  turns=7   pod=3  -> win
        g2  2025-02-01  non-cEDH  winner=2  turns=None pod=4  -> loss, null turns
        g3  2025-03-01  non-cEDH  winner=1  turns=9   pod=2  -> win (newest)
        g4  2025-02-15  cEDH      winner=1  turns=5   pod=4  -> excluded
    """
    with app.app_context():
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        ci = ColorIdentity(name="TestColor", amount=1)
        db_session.add(ci)
        db_session.flush()

        for pid, name in [(1, "Subject"), (2, "Opp2"), (3, "Opp3"), (4, "Opp4")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        # One deck per player; subject's deck has a recognizable name.
        for pid in (1, 2, 3, 4):
            db_session.add(Deck(
                id=pid,
                name=f"Deck_{pid}",
                commander=f"Cmd_{pid}",
                player_id=pid,
                active=True,
                color_identity="TestColor",
            ))
        db_session.flush()

        games = [
            dict(id=1, date=date(2025, 1, 1), cedh=False, winner_id=1, turns=7),
            dict(id=2, date=date(2025, 2, 1), cedh=False, winner_id=2, turns=None),
            dict(id=3, date=date(2025, 3, 1), cedh=False, winner_id=1, turns=9),
            dict(id=4, date=date(2025, 2, 15), cedh=True, winner_id=1, turns=5),
        ]
        for g in games:
            db_session.add(Game(**g))
        db_session.flush()

        # pods: g1 -> {1,2,3}, g2 -> {1,2,3,4}, g3 -> {1,2}, g4 -> {1,2,3,4}
        pods = {1: [1, 2, 3], 2: [1, 2, 3, 4], 3: [1, 2], 4: [1, 2, 3, 4]}
        for gid, pids in pods.items():
            for pid in pids:
                db_session.add(Participant(
                    game_id=gid, player_id=pid, deck_id=pid,
                ))
        db_session.flush()
        yield db_session


def test_ordering_newest_first_and_cedh_excluded(app, seeded):
    with app.app_context():
        rows = get_recent_games(1)
        # cEDH game 4 excluded -> only g3, g2, g1 remain, newest first
        assert len(rows) == 3
        assert [r["date"] for r in rows] == [
            date(2025, 3, 1), date(2025, 2, 1), date(2025, 1, 1)
        ]


def test_win_loss_derivation_and_null_turns(app, seeded):
    with app.app_context():
        rows = get_recent_games(1)
        by_date = {r["date"]: r for r in rows}
        assert by_date[date(2025, 3, 1)]["result"] == "win"
        assert by_date[date(2025, 1, 1)]["result"] == "win"
        # subject did not win g2 -> loss, and turns is null
        assert by_date[date(2025, 2, 1)]["result"] == "loss"
        assert by_date[date(2025, 2, 1)]["turns"] is None
        # non-null turns preserved
        assert by_date[date(2025, 3, 1)]["turns"] == 9


def test_pod_size_and_deck_name(app, seeded):
    with app.app_context():
        rows = get_recent_games(1)
        by_date = {r["date"]: r for r in rows}
        assert by_date[date(2025, 3, 1)]["pod_size"] == 2
        assert by_date[date(2025, 2, 1)]["pod_size"] == 4
        assert by_date[date(2025, 1, 1)]["pod_size"] == 3
        # subject piloted their own deck in every game
        assert by_date[date(2025, 3, 1)]["deck_name"] == "Deck_1"


def test_limit_is_respected(app, seeded):
    with app.app_context():
        rows = get_recent_games(1, limit=2)
        assert len(rows) == 2
        # newest two
        assert [r["date"] for r in rows] == [date(2025, 3, 1), date(2025, 2, 1)]


def test_empty_when_no_games(app, seeded):
    with app.app_context():
        # player 3 only appears in g1, g2, g4 (as participant) -> has games;
        # use a player id with no participations
        assert get_recent_games(999) == []
