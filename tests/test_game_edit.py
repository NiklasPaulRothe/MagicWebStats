"""Edit Game: changing a participant's deck must actually be saved.

Regression for: changing two players' decks in Edit Game and clicking save
reported success but changed nothing. Cause: the route resolved the deck owner
from ``player_name``, which the template only displays (never submits), so deck
resolution always failed and the old deck was silently kept.
"""

import datetime as dt

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, Deck, Game, Participant, User, ColorIdentity
from app.services.game_service import resolve_deck_id


@pytest.fixture()
def game_setup(app):
    with app.app_context():
        for model in (Participant, Game, Deck, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()

        _db.session.add(ColorIdentity(name="C", amount=0))
        _db.session.add_all([Player(id=1, name="Marx"), Player(id=2, name="Chakka"), Player(id=3, name="Host")])
        _db.session.flush()
        # The host (game owner, maintainer) has user id 1.
        u = User(id=1, username="host", email="h@e.com", player_id=3, active=True, role="maintainer")
        u.set_password("pw")
        _db.session.add(u)
        _db.session.add_all([
            Deck(id=10, name="Old Marx", commander="Someone", player_id=1, color_identity="C", active=True),
            Deck(id=11, name="Odric", commander="Odric, Lunarch Marshal", player_id=1, color_identity="C", active=True),
            # Name containing another deck's name: must not be picked by accident.
            Deck(id=12, name="Odric Voltron", commander="Odric, Master Tactician", player_id=1,
                 color_identity="C", active=True),
            Deck(id=20, name="Old Chakka", commander="Someone Else", player_id=2, color_identity="C", active=True),
            Deck(id=21, name="Scriv", commander="Scriv, the Obligator", player_id=2, color_identity="C", active=True),
            Deck(id=30, name="Host Deck", commander="Host Cmdr", player_id=3, color_identity="C", active=True),
        ])
        _db.session.flush()
        _db.session.add(Game(id=1885, date=dt.date(2026, 10, 1), winner_id=1, turns=9,
                             cedh=False, added_by_user_id=1))
        _db.session.flush()
        _db.session.add_all([
            Participant(game_id=1885, player_id=1, deck_id=10, seat=1),
            Participant(game_id=1885, player_id=2, deck_id=20, seat=2),
            Participant(game_id=1885, player_id=3, deck_id=30, seat=3),
        ])
        _db.session.commit()
        yield

        for model in (Participant, Game, Deck, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()


def _client(app):
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=_db.session.get(User, 1))


def _form(decks):
    """Edit-form POST body as the browser sends it (no player_name fields)."""
    data = {
        "date": "2026-10-01", "winner": "Marx", "turns": "9",
        "final_blow": "", "first_ko_turn": "", "first_ko_by": "",
    }
    for i, (player_id, deck_value) in enumerate(decks):
        data[f"participants-{i}-player_id"] = str(player_id)
        data[f"participants-{i}-seat"] = str(i + 1)
        data[f"participants-{i}-deck"] = deck_value
    return data


def _deck_of(app, player_id):
    with app.app_context():
        return _db.session.scalar(
            _db.select(Participant.deck_id).where(
                Participant.game_id == 1885, Participant.player_id == player_id))


def test_edit_game_saves_changed_decks(app, game_setup):
    resp = _client(app).post("/manage/games/1885/edit", data=_form([
        (1, "Odric (Odric, Lunarch Marshal)"),
        (2, "Scriv (Scriv, the Obligator)"),
        (3, "Host Deck (Host Cmdr)"),
    ]))
    assert resp.status_code == 302
    assert _deck_of(app, 1) == 11      # Marx -> Odric (not "Odric Voltron")
    assert _deck_of(app, 2) == 21      # Chakka -> Scriv
    assert _deck_of(app, 3) == 30      # unchanged


def test_edit_game_unknown_deck_saves_nothing(app, game_setup):
    resp = _client(app).post("/manage/games/1885/edit", data=_form([
        (1, "Does Not Exist (Nobody)"),
        (2, "Scriv (Scriv, the Obligator)"),
        (3, "Host Deck (Host Cmdr)"),
    ]), follow_redirects=True)
    body = resp.data.decode("utf-8")
    assert "Nichts wurde gespeichert" in body
    assert "Game updated successfully" not in body
    assert _deck_of(app, 1) == 10      # rolled back, nothing half-saved
    assert _deck_of(app, 2) == 20


def test_resolve_deck_id_prefers_exact_display_match(app, game_setup):
    with app.app_context():
        assert resolve_deck_id("Odric (Odric, Lunarch Marshal)", "Marx") == 11
        assert resolve_deck_id("Odric Voltron (Odric, Master Tactician)", "Marx") == 12
        with pytest.raises(ValueError):
            resolve_deck_id("Odric (Odric, Lunarch Marshal)", "Chakka")
