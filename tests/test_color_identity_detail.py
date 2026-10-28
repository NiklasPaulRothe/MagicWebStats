"""Tests for the color identity detail feature.

Covers the ``get_color_identity_detail`` service function (deck counts,
non-cEDH performance, games share, active-deck breakdown) and the
``/ColorStats/<name>`` route (200 for an existing identity, 404 for a
missing one), exercised through the authenticated test client.
"""

import pytest
from datetime import date

from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, Deck, Game, Participant, ColorIdentity, User
from app.services.stats_service import get_color_identity_detail


@pytest.fixture()
def seeded_detail(app):
    """Seed a deterministic scenario for the detail page.

    Players: Alice(1), Bob(2).
    Color identities: Azorius, Dimir.
    Decks:
      - d1: Alice, Azorius, active
      - d2: Bob,   Azorius, archived (active=False)
      - d3: Alice, Azorius, active, cEDH (excluded from stats)
      - d4: Bob,   Dimir,   active
    Games (all non-cEDH unless noted):
      - g1: Alice(d1) vs Bob(d4); winner Alice
      - g2: Alice(d1) vs Bob(d4); winner Bob
      - g3: Alice(d3 cEDH) vs Bob(d4); winner Alice  -> counts for Dimir only
    """
    with app.app_context():
        for model in (Participant, Game, Deck, Player, ColorIdentity, User):
            _db.session.query(model).delete()
        _db.session.commit()

        user = User(id=1, username="u", email="u@e.com", player_id=1, active=True, role="admin")
        user.set_password("pw")
        _db.session.add(user)

        _db.session.add_all([Player(id=1, name="Alice"), Player(id=2, name="Bob")])
        _db.session.add_all([
            ColorIdentity(name="Azorius", amount=2),
            ColorIdentity(name="Dimir", amount=2),
        ])
        _db.session.flush()

        _db.session.add_all([
            Deck(id=1, name="AzoActive", commander="Cmd1", player_id=1, active=True, color_identity="Azorius", cedh=False),
            Deck(id=2, name="AzoArchived", commander="Cmd2", player_id=2, active=False, color_identity="Azorius", cedh=False),
            Deck(id=3, name="AzoCedh", commander="Cmd3", player_id=1, active=True, color_identity="Azorius", cedh=True),
            Deck(id=4, name="DimirActive", commander="Cmd4", player_id=2, active=True, color_identity="Dimir", cedh=False),
        ])
        _db.session.add_all([
            Game(id=1, date=date(2024, 6, 1), winner_id=1, cedh=False),
            Game(id=2, date=date(2024, 6, 2), winner_id=2, cedh=False),
            Game(id=3, date=date(2024, 6, 3), winner_id=1, cedh=False),
        ])
        _db.session.flush()

        _db.session.add_all([
            Participant(game_id=1, player_id=1, deck_id=1),
            Participant(game_id=1, player_id=2, deck_id=4),
            Participant(game_id=2, player_id=1, deck_id=1),
            Participant(game_id=2, player_id=2, deck_id=4),
            Participant(game_id=3, player_id=1, deck_id=3),
            Participant(game_id=3, player_id=2, deck_id=4),
        ])
        _db.session.commit()
        yield _db.session

        for model in (Participant, Game, Deck, Player, ColorIdentity, User):
            _db.session.query(model).delete()
        _db.session.commit()


def test_detail_none_for_unknown_identity(app, seeded_detail):
    with app.app_context():
        assert get_color_identity_detail("Nonexistent") is None


def test_detail_deck_counts(app, seeded_detail):
    with app.app_context():
        d = get_color_identity_detail("Azorius")
    # 3 Azorius decks total: 2 active (d1, d3), 1 archived (d2).
    assert d["total_decks"] == 3
    assert d["active_decks"] == 2
    assert d["archived_decks"] == 1


def test_detail_performance_excludes_cedh(app, seeded_detail):
    with app.app_context():
        d = get_color_identity_detail("Azorius")
    # Only d1 (non-cEDH Azorius) participated: g1 (win) + g2 (loss) = 2 games, 1 win.
    assert d["games"] == 2
    assert d["wins"] == 1
    assert d["winrate"] == 50.0


def test_detail_games_share(app, seeded_detail):
    with app.app_context():
        d = get_color_identity_detail("Azorius")
    # Azorius (non-cEDH) appears in g1 and g2 -> 2 of 3 total non-cEDH games.
    assert d["games_share_pct"] == round(2 / 3 * 100, 1)


def test_detail_active_decks_breakdown(app, seeded_detail):
    with app.app_context():
        d = get_color_identity_detail("Azorius")
    # Active decks table lists the 2 active Azorius decks (d1 active, d3 active cEDH).
    names = {row["name"] for row in d["decks"]}
    assert names == {"AzoActive", "AzoCedh"}
    by_name = {row["name"]: row for row in d["decks"]}
    # d1 played 2 games, won 1.
    assert by_name["AzoActive"]["games"] == 2
    assert by_name["AzoActive"]["wins"] == 1
    assert by_name["AzoActive"]["winrate"] == 50.0
    # d3 (cEDH) was never excluded from the per-deck table (it is active); it
    # participated in g3 but did not win (winner was its own player though).
    assert by_name["AzoCedh"]["games"] == 1


def _client(app, user):
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=user)


def test_route_returns_200(app, seeded_detail):
    user = _db.session.get(User, 1)
    client = _client(app, user)
    resp = client.get("/ColorStats/Azorius")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "Azorius" in body
    assert "Active Decks" in body
    assert "AzoActive" in body


def test_route_returns_404_for_unknown(app, seeded_detail):
    user = _db.session.get(User, 1)
    client = _client(app, user)
    resp = client.get("/ColorStats/Nonexistent")
    assert resp.status_code == 404
