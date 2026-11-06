"""The Playgroup dashboard is a non-cEDH data hub.

Seeds a mix of normal and cEDH games (with turns, first KO, final blow, seats
and removal data) and checks that every game-based metric of
compute_playgroup_dashboard() ignores the cEDH games, and that the active-deck
count ignores cEDH decks. The color panel reads the v_color_usage view (which
excludes cEDH itself); the view doesn't exist on SQLite, so it's stubbed.
"""

import datetime as dt
import types

import pytest

from app import db as _db
from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import compute_playgroup_dashboard


@pytest.fixture()
def seeded(app, monkeypatch):
    import app.viewmodels as vm
    monkeypatch.setattr(vm, "ColorUsage", types.SimpleNamespace(
        query=types.SimpleNamespace(all=lambda: [])))

    with app.app_context():
        for model in (Participant, Game, Deck, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()

        _db.session.add(ColorIdentity(name="C", amount=0))
        _db.session.add_all([Player(id=i, name=f"P{i}") for i in (1, 2, 3)])
        _db.session.flush()
        _db.session.add_all([
            Deck(id=1, name="Casual A", commander="A", player_id=1, color_identity="C", active=True, cedh=False),
            Deck(id=2, name="Casual B", commander="B", player_id=2, color_identity="C", active=True, cedh=False),
            Deck(id=3, name="Casual C", commander="C", player_id=3, color_identity="C", active=True, cedh=False),
            Deck(id=4, name="Turbo", commander="T", player_id=1, color_identity="C", active=True, cedh=True),
        ])
        _db.session.flush()

        today = dt.date.today()
        # Two normal 3-player games and two cEDH games with very different data,
        # so any leak of cEDH rows shows up in every metric.
        games = [
            # id, cedh, turns, first_ko, final_blow, winner
            (1, False, 10, 7, "Combat", 1),
            (2, False, 12, 9, "Combat", 2),
            (3, True, 3, 2, "Combo", 1),
            (4, True, 4, 2, "Combo", 1),
        ]
        for gid, cedh, turns, ko, fb, winner in games:
            _db.session.add(Game(id=gid, date=today, cedh=cedh, turns=turns,
                                 first_ko_turn=ko, final_blow=fb, winner_id=winner))
        _db.session.flush()
        for gid, cedh, *_ in games:
            seats = [(1, 4 if cedh else 1), (2, 2), (3, 3)]
            for seat, (pid, deck_id) in enumerate(seats, start=1):
                _db.session.add(Participant(
                    game_id=gid, player_id=pid, deck_id=deck_id, seat=seat,
                    removal_played=9 if cedh else 1, targeted_by_removal=9 if cedh else 1,
                ))
        _db.session.commit()
        yield

        for model in (Participant, Game, Deck, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()


def test_kpis_exclude_cedh(app, seeded):
    with app.app_context():
        k = compute_playgroup_dashboard()["kpis"]
    assert k["games"] == 2
    assert k["games_this_month"] == 2
    assert k["games_this_year"] == 2
    assert k["active_decks"] == 3          # the cEDH deck is not counted
    assert k["players"] == 3
    assert k["avg_pod"] == 3.0
    assert "cedh_share" not in k


def test_game_shape_metrics_exclude_cedh(app, seeded):
    with app.app_context():
        d = compute_playgroup_dashboard()
    assert d["game_length"]["avg"] == 11.0 and d["game_length"]["max"] == 12
    assert d["first_kill"]["fastest"] == 7 and d["first_kill"]["avg"] == 8.0
    assert [(f["label"], f["count"]) for f in d["final_blow"]] == [("Combat", 2)]
    assert [(p["size"], p["count"]) for p in d["pod_split"]] == [(3, 2)]


def test_seat_bias_and_removal_exclude_cedh(app, seeded):
    with app.app_context():
        d = compute_playgroup_dashboard()
    assert d["seat_pod_size"] == 3 and d["seat_games"] == 2
    assert sum(s["games"] for s in d["seat_bias"]) == 6       # 2 games x 3 seats
    assert sum(s["wins"] for s in d["seat_bias"]) == 2
    r = d["removal"]
    assert r["games"] == 2
    assert r["played_all"] == 1.0 and r["targeted_all"] == 1.0
    assert r["played_win"] == 1.0 and r["targeted_win"] == 1.0
