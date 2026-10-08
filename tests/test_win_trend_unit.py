"""Unit tests for stats_service.get_win_trend.

Covers monthly bucketing, chronological ordering, per-bucket games/wins/winrate
aggregation, cEDH exclusion, win/loss derivation via Game.winner_id, and the
empty state.

Validates: Requirements 7.1, 7.2, 7.4
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_win_trend


@pytest.fixture()
def seeded(app, db_session):
    """Seed a deterministic data set for win-trend tests.

    Subject = player 1, opponent = player 2 (sits in every game so wins are
    attributable via Game.winner_id).

    Non-cEDH games for the subject:
        2025-01: 2 games, 1 win   -> winrate 50.0
        2025-02: 1 game,  1 win   -> winrate 100.0
        2025-04: 2 games, 0 wins  -> winrate 0.0 (gap at 2025-03 is skipped)
    Plus one cEDH game in 2025-02 (must be excluded) and one game with a
    missing date (must be skipped without error).
    """
    with app.app_context():
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        db_session.add(ColorIdentity(name="TestColor", amount=1))
        db_session.flush()

        for pid, name in [(1, "Subject"), (2, "Opp2")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        for did, pid in [(1, 1), (99, 2)]:
            db_session.add(Deck(
                id=did, name=f"Deck{did}", commander=f"Cmd{did}",
                player_id=pid, active=True, color_identity="TestColor",
            ))
        db_session.flush()

        gid = 1

        def add_game(game_date, won, cedh=False):
            nonlocal gid
            winner = 1 if won else 2
            db_session.add(Game(id=gid, date=game_date, cedh=cedh, winner_id=winner))
            db_session.add(Participant(game_id=gid, player_id=1, deck_id=1))
            db_session.add(Participant(game_id=gid, player_id=2, deck_id=99))
            gid += 1

        # 2025-01: 2 games, 1 win
        add_game(date(2025, 1, 10), won=True)
        add_game(date(2025, 1, 20), won=False)
        # 2025-02: 1 non-cEDH win + 1 cEDH win (excluded)
        add_game(date(2025, 2, 5), won=True)
        add_game(date(2025, 2, 15), won=True, cedh=True)
        # 2025-04: 2 games, 0 wins
        add_game(date(2025, 4, 1), won=False)
        add_game(date(2025, 4, 2), won=False)

        db_session.flush()
        yield db_session


def test_buckets_are_monthly_and_chronological(app, seeded):
    with app.app_context():
        trend = get_win_trend(1)
        # 2025-03 has no games -> not emitted; order is chronological.
        assert [b["period"] for b in trend] == ["2025-01", "2025-02", "2025-04"]


def test_per_bucket_games_wins_winrate(app, seeded):
    with app.app_context():
        trend = get_win_trend(1)
        by_period = {b["period"]: b for b in trend}

        assert by_period["2025-01"]["games"] == 2
        assert by_period["2025-01"]["wins"] == 1
        assert by_period["2025-01"]["winrate"] == 50.0

        assert by_period["2025-02"]["games"] == 1
        assert by_period["2025-02"]["wins"] == 1
        assert by_period["2025-02"]["winrate"] == 100.0

        assert by_period["2025-04"]["games"] == 2
        assert by_period["2025-04"]["wins"] == 0
        assert by_period["2025-04"]["winrate"] == 0.0


def test_cedh_games_excluded(app, seeded):
    with app.app_context():
        trend = get_win_trend(1)
        by_period = {b["period"]: b for b in trend}
        # The cEDH win in 2025-02 must not inflate games or wins.
        assert by_period["2025-02"]["games"] == 1
        assert by_period["2025-02"]["wins"] == 1


def test_empty_when_no_games(app, seeded):
    with app.app_context():
        assert get_win_trend(999) == []
