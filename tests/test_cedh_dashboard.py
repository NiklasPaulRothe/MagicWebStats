"""cEDH dashboard: data set switch, cEDH-only metrics and commander ranking.

Seeds casual and cEDH games with very different data and checks that
compute_playgroup_dashboard(cedh=True) uses only cEDH games/decks, that the
commander winrate ranking groups by commander (partner pair = one commander,
either order), applies the 4-game minimum and orders by winrate, and that the
page renders the slider plus the right panels per mode.
"""

import datetime as dt
import types

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, Deck, Game, Participant, ColorIdentity, ColorComponent, Color, User
from app.services.stats_service import (
    compute_playgroup_dashboard,
    compute_cedh_commander_ranking,
    commander_label,
)


@pytest.fixture()
def seeded(app, monkeypatch):
    # Casual colors come from the v_color_usage view, which doesn't exist on SQLite.
    import app.viewmodels as vm
    monkeypatch.setattr(vm, "ColorUsage", types.SimpleNamespace(
        query=types.SimpleNamespace(all=lambda: [])))

    with app.app_context():
        for model in (Participant, Game, Deck, User, Player, ColorComponent, ColorIdentity, Color):
            _db.session.query(model).delete()
        _db.session.commit()

        _db.session.add_all([Color(name="Blue", abbreviation="U"), Color(name="Black", abbreviation="B")])
        _db.session.add_all([ColorIdentity(name="Dimir", amount=2), ColorIdentity(name="Mono-Blue", amount=1)])
        _db.session.flush()
        _db.session.add_all([
            ColorComponent(color_identity="Dimir", color="Blue"),
            ColorComponent(color_identity="Dimir", color="Black"),
            ColorComponent(color_identity="Mono-Blue", color="Blue"),
        ])
        # Player 5 never plays a cEDH game (only exists for the player counts).
        _db.session.add_all([Player(id=i, name=f"P{i}") for i in (1, 2, 3, 4, 5)])
        u = User(id=1, username="u1", email="u1@e.com", player_id=1, active=True, role="user")
        u.set_password("pw")
        _db.session.add(u)
        _db.session.flush()

        _db.session.add_all([
            # cEDH decks: two different decks with the same partner pair (in
            # opposite order) must count as ONE commander.
            Deck(id=1, name="Blue Farm A", commander="Tymna", partner="Kraum", player_id=1,
                 color_identity="Dimir", active=True, cedh=True),
            Deck(id=2, name="Blue Farm B", commander="Kraum", partner="Tymna", player_id=2,
                 color_identity="Dimir", active=True, cedh=True),
            Deck(id=3, name="Kinnan", commander="Kinnan", player_id=3,
                 color_identity="Mono-Blue", active=True, cedh=True),
            Deck(id=4, name="Rare", commander="Rarely Played", player_id=4,
                 color_identity="Mono-Blue", active=True, cedh=True),
            # casual deck (must not appear in any cEDH number)
            Deck(id=5, name="Casual", commander="Casual Guy", player_id=4,
                 color_identity="Mono-Blue", active=True, cedh=False),
        ])
        _db.session.flush()

        today = dt.date.today()
        # 5 cEDH games: games 1-3 seat decks 1-4, games 4-5 seat decks 1-3.
        # Winners: Tymna/Kraum pilots win 3 (players 1, 2, 1), Kinnan wins 2.
        cedh_games = [(1, 1), (2, 2), (3, 1), (4, 3), (5, 3)]
        for gid, winner in cedh_games:
            _db.session.add(Game(id=gid, date=today, cedh=True, turns=4, first_ko_turn=3,
                                 final_blow="Combo", winner_id=winner))
        # 1 casual game with very different numbers
        _db.session.add(Game(id=9, date=today, cedh=False, turns=12, first_ko_turn=9,
                             final_blow="Combat", winner_id=4))
        _db.session.flush()
        for gid, _w in cedh_games:
            seats = [(1, 1), (2, 2), (3, 3)] + ([(4, 4)] if gid <= 3 else [])
            for seat, (pid, deck_id) in enumerate(seats, start=1):
                _db.session.add(Participant(game_id=gid, player_id=pid, deck_id=deck_id, seat=seat))
        # The casual game: three seats, all on the casual deck.
        for seat, pid in enumerate((4, 1, 2), start=1):
            _db.session.add(Participant(game_id=9, player_id=pid, deck_id=5, seat=seat))
        _db.session.commit()
        yield

        for model in (Participant, Game, Deck, User, Player, ColorComponent, ColorIdentity, Color):
            _db.session.query(model).delete()
        _db.session.commit()


def test_commander_label_partner_pair_is_one_commander():
    assert commander_label("Tymna", "Kraum") == commander_label("Kraum", "Tymna") == "Kraum + Tymna"
    assert commander_label("Kinnan", None) == "Kinnan"
    assert commander_label("Kinnan", "  ") == "Kinnan"


def test_ranking_groups_by_commander_with_min_games(app, seeded):
    with app.app_context():
        ranking = compute_cedh_commander_ranking()
    rows = {r["commander"]: r for r in ranking}
    # Tymna/Kraum: 2 seats in each of 5 games = 10 games, 3 wins.
    assert rows["Kraum + Tymna"]["games"] == 10 and rows["Kraum + Tymna"]["wins"] == 3
    # Kinnan: 5 games, 2 wins.
    assert rows["Kinnan"]["games"] == 5 and rows["Kinnan"]["wins"] == 2
    # "Rarely Played" has only 3 cEDH games -> below the 4-game minimum.
    assert "Rarely Played" not in rows
    # Casual decks never appear.
    assert "Casual Guy" not in rows
    # Ordered by winrate: Kinnan 40% > Kraum + Tymna 30%.
    assert [r["commander"] for r in ranking] == ["Kinnan", "Kraum + Tymna"]
    assert [r["rank"] for r in ranking] == [1, 2]
    assert rows["Kinnan"]["winrate"] == 40.0


def test_cedh_dashboard_uses_only_cedh_data(app, seeded):
    with app.app_context():
        d = compute_playgroup_dashboard(cedh=True)
    assert d["mode"] == "cedh"
    k = d["kpis"]
    assert k["games"] == 5
    assert k["active_decks"] == 4            # cEDH decks only
    assert k["players"] == 4                 # players 1-4 played cEDH; player 5 didn't
    assert k["avg_pod"] == round(18 / 5, 1)  # 3 x 4 seats + 2 x 3 seats
    assert d["game_length"]["avg"] == 4.0 and d["game_length"]["max"] == 4
    assert d["first_kill"]["fastest"] == 3
    assert [(f["label"], f["count"]) for f in d["final_blow"]] == [("Combo", 5)]
    assert d["seat_pod_size"] == 4 and d["seat_games"] == 3
    colors = {c["key"]: c for c in d["colors"]}
    assert colors["blue"]["likelihood"] == 100.0          # every cEDH game has blue
    assert colors["blue"]["avg_decks"] == round(18 / 5, 1)
    assert colors["black"]["likelihood"] == 100.0
    assert colors["black"]["avg_decks"] == 2.0           # the two Dimir decks
    assert [r["commander"] for r in d["commander_ranking"]] == ["Kinnan", "Kraum + Tymna"]


def test_casual_dashboard_unchanged_and_has_no_ranking(app, seeded):
    with app.app_context():
        d = compute_playgroup_dashboard()
    assert d["mode"] == "casual"
    assert d["commander_ranking"] == []
    assert d["kpis"]["games"] == 1
    assert d["kpis"]["active_decks"] == 1
    assert d["kpis"]["players"] == 5         # casual: plain count of all players
    assert [(f["label"], f["count"]) for f in d["final_blow"]] == [("Combat", 1)]


def _client(app):
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=_db.session.get(User, 1))


def test_page_cedh_mode_swaps_panels(app, seeded):
    body = _client(app).get("/?mode=cedh").data.decode("utf-8")
    assert "cEDH dashboard" in body
    assert 'class="mode-switch is-cedh"' in body
    assert "Commander winrate" in body and "Kraum + Tymna" in body
    assert "Pod size split" not in body
    assert "Removal" not in body


def test_page_casual_mode_default(app, seeded):
    body = _client(app).get("/").data.decode("utf-8")
    assert "Playgroup dashboard" in body
    assert 'class="mode-switch"' in body
    assert "Pod size split" in body and "Removal" in body
    assert "Commander winrate" not in body


def test_page_unknown_mode_falls_back_to_casual(app, seeded):
    body = _client(app).get("/?mode=whatever").data.decode("utf-8")
    assert "Playgroup dashboard" in body
