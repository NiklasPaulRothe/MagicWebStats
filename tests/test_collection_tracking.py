"""Tests for per-deck-card collection tracking.

Covers the availability/status computation in collection_service
(compute_deck_collection_status, get_collection_statuses) with exact
printing+finish+language matching and over-claim ("faulty") detection, plus
the owner-gated set_component_collection endpoint.

These exercise the Python status logic (which mirrors the SQL views) so they
run on the in-memory SQLite test DB.
"""

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import (
    Player, Deck, User, ColorIdentity, Card, DeckComponent, PlayerCollectionCard,
)
from app.services.collection_service import (
    compute_deck_collection_status,
    get_collection_statuses,
    get_collection_finish_language_options,
    DECK_STATUS_IN_DECK_OK, DECK_STATUS_IN_DECK_FAULTY, DECK_STATUS_PROXY,
    DECK_STATUS_AVAILABLE, DECK_STATUS_OWNED_NO_COPY, DECK_STATUS_OWNED_OTHER,
    DECK_STATUS_NOT_OWNED,
    COLL_STATUS_SPARE, COLL_STATUS_IN_DECK, COLL_STATUS_NO_COPY,
)


def _card(cid, oracle, name, set_code="SET"):
    return Card(
        id=cid, oracle_id=oracle, name=name, cmc=0, type_line="Creature",
        layout="normal", set_code=set_code, set_name="Set", rarity="common",
    )


@pytest.fixture()
def setup(app):
    """Alice (player 1) with a deck and a small collection; Bob (player 2).

    Cards:
      sol-a / sol-b are two printings of Sol Ring (oracle 'SOL').
      ring       is a different card (oracle 'RING').
    """
    with app.app_context():
        for model in (DeckComponent, PlayerCollectionCard, Deck, Card, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()

        alice = User(id=1, username="alice", email="a@e.com", player_id=1, active=True, role="admin")
        alice.set_password("pw")
        bob = User(id=2, username="bob", email="b@e.com", player_id=2, active=True, role="admin")
        bob.set_password("pw")
        _db.session.add_all([alice, bob])
        _db.session.add_all([Player(id=1, name="Alice"), Player(id=2, name="Bob")])
        _db.session.add(ColorIdentity(name="C", amount=0))
        _db.session.add_all([
            _card("sol-a", "SOL", "Sol Ring", "LEA"),
            _card("sol-b", "SOL", "Sol Ring", "C21"),
            _card("ring", "RING", "The One Ring", "LTR"),
        ])
        _db.session.add(Deck(id=1, name="AliceDeck", commander="Cmd", player_id=1,
                             active=True, color_identity="C"))
        _db.session.add(Deck(id=2, name="AliceDeck2", commander="Cmd", player_id=1,
                             active=True, color_identity="C"))
        _db.session.commit()
        yield _db.session

        for model in (DeckComponent, PlayerCollectionCard, Deck, Card, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()


def _coll(player_id, card_id, finish="Normal", language="EN", count=1, name="Sol Ring"):
    return PlayerCollectionCard(
        player_id=player_id, card_id=card_id, scryfall_id=card_id,
        finish=finish, condition="NM", language=language, name=name, count=count,
    )


def _comp(deck_id, card_id, status="unset", finish="Normal", language="EN", name="Sol Ring"):
    return DeckComponent(
        deck_id=deck_id, card_id=card_id, name=name, count=1, in_deck=True,
        physical_status=status, physical_finish=finish, physical_language=language,
    )


# --- compute_deck_collection_status -------------------------------------

def test_in_deck_ok_when_matching_copy_owned(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        comp = _comp(1, "sol-a", status="in_deck", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_IN_DECK_OK


def test_in_deck_faulty_when_no_matching_copy(app, setup):
    with app.app_context():
        # Owns the OTHER printing only; the in_deck claim is for sol-a.
        _db.session.add(_coll(1, "sol-b", count=1))
        comp = _comp(1, "sol-a", status="in_deck", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_IN_DECK_FAULTY


def test_in_deck_faulty_when_finish_mismatch(app, setup):
    with app.app_context():
        # Owns Normal; claim is for Foil -> different pool -> faulty.
        _db.session.add(_coll(1, "sol-a", finish="Normal", count=1))
        comp = _comp(1, "sol-a", status="in_deck", finish="Foil", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_IN_DECK_FAULTY


def test_in_deck_faulty_when_over_claimed_across_decks(app, setup):
    with app.app_context():
        # Own 1 copy; mark in_deck in BOTH decks -> 2 claimed > 1 owned.
        _db.session.add(_coll(1, "sol-a", count=1))
        c1 = _comp(1, "sol-a", status="in_deck", finish="Normal", language="EN")
        c2 = _comp(2, "sol-a", status="in_deck", finish="Normal", language="EN")
        _db.session.add_all([c1, c2])
        _db.session.commit()
        statuses1 = compute_deck_collection_status(1, 1)
        statuses2 = compute_deck_collection_status(1, 2)
        # Both pull from the same over-claimed pool, so both are faulty.
        assert statuses1[c1.id]["status"] == DECK_STATUS_IN_DECK_FAULTY
        assert statuses2[c2.id]["status"] == DECK_STATUS_IN_DECK_FAULTY


def test_two_owned_two_claimed_is_ok(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=2))
        c1 = _comp(1, "sol-a", status="in_deck", finish="Normal", language="EN")
        c2 = _comp(2, "sol-a", status="in_deck", finish="Normal", language="EN")
        _db.session.add_all([c1, c2])
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[c1.id]["status"] == DECK_STATUS_IN_DECK_OK


def test_unset_available_when_owned_and_free(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        comp = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_AVAILABLE


def test_unset_owned_no_copy_when_all_claimed(app, setup):
    with app.app_context():
        # One copy, claimed in deck 2; the unset card in deck 1 (same pool)
        # finds owned>0 but none free.
        _db.session.add(_coll(1, "sol-a", count=1))
        claimed = _comp(2, "sol-a", status="in_deck", finish="Normal", language="EN")
        unset = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add_all([claimed, unset])
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[unset.id]["status"] == DECK_STATUS_OWNED_NO_COPY


def test_unset_default_finish_matches_default_collection(app, setup):
    # An unmarked card carries the default finish/language ('Normal'/'EN'),
    # matching a collection entry stored with the same defaults -> available.
    # (This is the real-world case the deck overview bug was about: unmarked
    # cards must resolve to 'available', not 'owned_other'.)
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", finish="Normal", language="EN", count=1))
        comp = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_AVAILABLE


def test_unset_finish_mismatch_is_owned_other(app, setup):
    # Exact matching for unset too: own a Foil, but the (default) card finish is
    # Normal -> no exact pool match -> owned_other (same card, different finish).
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", finish="Foil", language="EN", count=1))
        comp = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_OWNED_OTHER


def test_unset_owned_other_printing(app, setup):
    with app.app_context():
        # Owns sol-b; the unset deck card is sol-a (same oracle, no sol-a pool).
        _db.session.add(_coll(1, "sol-b", count=1))
        comp = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_OWNED_OTHER


def test_unset_other_printing_but_all_claimed_is_owned_no_copy(app, setup):
    # Own the card ONLY in a different printing (sol-b), and that copy is marked
    # in_deck in another deck. The unset sol-a card must be owned_no_copy (no
    # free physical copy exists), NOT owned_other — printing doesn't matter for
    # availability. This is the reported bug.
    with app.app_context():
        _db.session.add(_coll(1, "sol-b", finish="Normal", language="EN", count=1))
        # sol-b claimed in deck 2 (over-claims its own pool-of-one).
        _db.session.add(_comp(2, "sol-b", status="in_deck", finish="Normal", language="EN"))
        comp = _comp(1, "sol-a", status="unset", finish="Normal", language="EN")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_OWNED_NO_COPY


def test_unset_not_owned(app, setup):
    with app.app_context():
        comp = _comp(1, "ring", status="unset", name="The One Ring")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_NOT_OWNED


def test_proxy_status(app, setup):
    with app.app_context():
        comp = _comp(1, "sol-a", status="proxy")
        _db.session.add(comp)
        _db.session.commit()
        statuses = compute_deck_collection_status(1, 1)
        assert statuses[comp.id]["status"] == DECK_STATUS_PROXY


# --- get_collection_statuses --------------------------------------------

def test_collection_spare_when_nothing_claimed(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=2))
        _db.session.commit()
        statuses = get_collection_statuses(1)
        assert statuses[("sol-a", "normal", "en")] == COLL_STATUS_SPARE


def test_collection_in_deck_when_all_claimed(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        _db.session.add(_comp(1, "sol-a", status="in_deck", finish="Normal", language="EN"))
        _db.session.commit()
        statuses = get_collection_statuses(1)
        assert statuses[("sol-a", "normal", "en")] == COLL_STATUS_IN_DECK


def test_collection_no_copy_when_over_claimed(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        _db.session.add(_comp(1, "sol-a", status="in_deck", finish="Normal", language="EN"))
        _db.session.add(_comp(2, "sol-a", status="in_deck", finish="Normal", language="EN"))
        _db.session.commit()
        statuses = get_collection_statuses(1)
        assert statuses[("sol-a", "normal", "en")] == COLL_STATUS_NO_COPY


# --- editor dropdown options --------------------------------------------

def test_finish_language_options_defaults_first(app, setup):
    # With a Foil copy and a German copy present, the options include the
    # collection's tokens with 'Normal'/'EN' always first.
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", finish="Foil", language="DE"))
        _db.session.add(_coll(1, "sol-b", finish="Normal", language="EN"))
        _db.session.commit()
        opts = get_collection_finish_language_options(1)
    assert opts["finishes"][0] == "Normal"
    assert "Foil" in opts["finishes"]
    assert opts["languages"][0] == "EN"
    assert "DE" in opts["languages"]


def test_finish_language_options_empty_collection(app, setup):
    # Even with no collection, the defaults are offered.
    with app.app_context():
        opts = get_collection_finish_language_options(1)
    assert opts["finishes"] == ["Normal"]
    assert opts["languages"] == ["EN"]


# --- endpoint owner-gating ----------------------------------------------

def _client(app, user_id):
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=_db.session.get(User, user_id))


def test_endpoint_sets_status_and_returns_recomputed(app, setup):
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        comp = _comp(1, "sol-a", status="unset")
        _db.session.add(comp)
        _db.session.commit()
        comp_id = comp.id

    client = _client(app, 1)
    resp = client.post(
        f"/decks/1/component/{comp_id}/collection",
        json={"physical_status": "in_deck", "finish": "Normal", "language": "EN"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["status"] == "in_deck_ok"
    assert data["physical_status"] == "in_deck"
    assert data["deck_faulty_count"] == 0


def test_endpoint_rejects_non_owner(app, setup):
    with app.app_context():
        comp = _comp(1, "sol-a", status="unset")
        _db.session.add(comp)
        _db.session.commit()
        comp_id = comp.id

    # Bob (player 2) tries to edit Alice's deck component.
    client = _client(app, 2)
    resp = client.post(
        f"/decks/1/component/{comp_id}/collection",
        json={"physical_status": "proxy"},
    )
    assert resp.status_code == 403


def test_endpoint_rejects_invalid_status(app, setup):
    with app.app_context():
        comp = _comp(1, "sol-a", status="unset")
        _db.session.add(comp)
        _db.session.commit()
        comp_id = comp.id

    client = _client(app, 1)
    resp = client.post(
        f"/decks/1/component/{comp_id}/collection",
        json={"physical_status": "bogus"},
    )
    assert resp.status_code == 400


def test_collection_board_fragment_reflects_status(app, setup):
    # The fragment endpoint returns the server-rendered "By collection" board,
    # grouped by the current status. After marking a card in_deck it appears
    # under the "In deck" group with its marker, so a swapped-in board matches a
    # fresh page load.
    with app.app_context():
        _db.session.add(_coll(1, "sol-a", count=1))
        comp = _comp(1, "sol-a", status="in_deck", finish="Normal", language="EN", name="Sol Ring")
        _db.session.add(comp)
        _db.session.commit()
        comp_id = comp.id

    client = _client(app, 1)
    resp = client.get("/decks/1/collection-board")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "stack-board" in body
    assert "In deck" in body
    assert 'data-collection-status="in_deck_ok"' in body
    assert f'data-component-id="{comp_id}"' in body
    assert "cc-in_deck_ok" in body
