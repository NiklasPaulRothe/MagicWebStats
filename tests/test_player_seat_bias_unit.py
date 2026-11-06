"""Unit tests for stats_service.get_player_seat_bias (profile "Winrate by seat").

Counts every casual game in which the player has a seat — any pod size, other
players' seats don't matter. cEDH games and games without the player's seat
are ignored. (No fair line: the chart uses fixed 25/33/50/75 % gridlines.)
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_player_seat_bias


@pytest.fixture()
def seeded(app, db_session):
    with app.app_context():
        for model in (Participant, Game, Deck, Player, ColorIdentity):
            db_session.query(model).delete()
        db_session.flush()
        db_session.add(ColorIdentity(name="TestColor", amount=1))
        for pid in range(1, 7):
            db_session.add(Player(id=pid, name=f"P{pid}"))
        db_session.flush()
        for pid in range(1, 7):
            db_session.add(Deck(id=pid, name=f"D{pid}", commander="C", player_id=pid,
                                active=True, color_identity="TestColor"))
        db_session.flush()

        gid = 0

        def game(seats, winner, cedh=False):
            """seats: {player_id: seat or None}"""
            nonlocal gid
            gid += 1
            db_session.add(Game(id=gid, date=date(2025, 1, 1), cedh=cedh, winner_id=winner))
            db_session.flush()
            for pid, seat in seats.items():
                db_session.add(Participant(game_id=gid, player_id=pid, deck_id=pid, seat=seat))

        # Counted for player 1 (casual, player 1 has a seat):
        game({1: 1, 2: 2, 3: 3, 4: 4}, winner=1)              # 4-pod, seat 1, win
        game({1: 1, 2: None, 3: None, 4: None}, winner=2)     # others unseated, seat 1, loss
        game({1: 2, 2: 1, 3: 3}, winner=1)                    # 3-pod, seat 2, win
        game({1: 5, 2: 1, 3: 2, 4: 3, 5: 4}, winner=2)        # 5-pod, seat 5, loss
        # Not counted:
        game({1: 2, 2: 1, 3: 3, 4: 4}, winner=1, cedh=True)   # cEDH
        game({1: None, 2: 1, 3: 2, 4: 3}, winner=1)           # player 1 has no seat
        db_session.flush()
        yield db_session


def test_counts_all_casual_games_where_player_has_a_seat(app, seeded):
    with app.app_context():
        sb = get_player_seat_bias(1)
    assert sb["games"] == 4
    by_seat = {s["seat"]: s for s in sb["seats"]}
    assert (by_seat[1]["games"], by_seat[1]["wins"], by_seat[1]["winrate"]) == (2, 1, 50.0)
    assert (by_seat[2]["games"], by_seat[2]["wins"], by_seat[2]["winrate"]) == (1, 1, 100.0)
    assert (by_seat[5]["games"], by_seat[5]["wins"], by_seat[5]["winrate"]) == (1, 0, 0.0)
    # Seats 1-4 always listed; 5 appears because it was played.
    assert [s["seat"] for s in sb["seats"]] == [1, 2, 3, 4, 5]
    assert (by_seat[3]["games"], by_seat[3]["winrate"]) == (0, None)


def test_result_has_no_fair_line(app, seeded):
    with app.app_context():
        sb = get_player_seat_bias(1)
    assert set(sb) == {"games", "seats"}


def test_empty_for_player_without_seated_games(app, seeded):
    with app.app_context():
        sb = get_player_seat_bias(6)
    assert sb["games"] == 0
    assert [s["seat"] for s in sb["seats"]] == [1, 2, 3, 4]
    assert all(s["games"] == 0 for s in sb["seats"])
