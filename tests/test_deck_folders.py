"""Tests for the deck folders feature.

Covers the DeckFolder model, the My Decks folder-scoped view, and the
create-folder / move-deck JSON endpoints (success paths plus owner gating),
exercised through the authenticated test client.
"""

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, Deck, User, DeckFolder, ColorIdentity


@pytest.fixture()
def folders_setup(app):
    """Two users/players (owner=1 Alice, other=2 Bob), a color identity, and a
    couple of active decks for Alice. Committed so they survive request session
    teardown; cleaned up after.
    """
    with app.app_context():
        for model in (Deck, DeckFolder, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()

        owner = User(id=1, username="alice", email="a@e.com", player_id=1, active=True, role="admin")
        owner.set_password("pw")
        other = User(id=2, username="bob", email="b@e.com", player_id=2, active=True, role="admin")
        other.set_password("pw")
        _db.session.add_all([owner, other])
        _db.session.add_all([Player(id=1, name="Alice"), Player(id=2, name="Bob")])
        _db.session.add(ColorIdentity(name="Azorius", amount=2))
        _db.session.flush()

        _db.session.add_all([
            Deck(id=1, name="Alpha", commander="Cmd A", player_id=1, active=True, color_identity="Azorius"),
            Deck(id=2, name="Beta", commander="Cmd B", player_id=1, active=True, color_identity="Azorius"),
            Deck(id=3, name="BobDeck", commander="Cmd C", player_id=2, active=True, color_identity="Azorius"),
        ])
        _db.session.commit()
        yield _db.session

        for model in (Deck, DeckFolder, User, Player, ColorIdentity):
            _db.session.query(model).delete()
        _db.session.commit()


def _client(app, user_id):
    app.test_client_class = FlaskLoginClient
    user = _db.session.get(User, user_id)
    return app.test_client(user=user)


# --- Model ----------------------------------------------------------------

def test_folder_nesting_relationship(app, folders_setup):
    with app.app_context():
        root = DeckFolder(player_id=1, name="Root")
        _db.session.add(root)
        _db.session.flush()
        child = DeckFolder(player_id=1, name="Child", parent_id=root.id)
        _db.session.add(child)
        _db.session.flush()
        assert child.parent.id == root.id
        assert [c.id for c in root.children] == [child.id]


# --- create_folder --------------------------------------------------------

def test_create_folder_success(app, folders_setup):
    client = _client(app, 1)
    resp = client.post("/decks/folders", json={"name": "Commander"})
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert data["folder"]["name"] == "Commander"
    assert data["folder"]["parent_id"] is None


def test_create_subfolder_success(app, folders_setup):
    client = _client(app, 1)
    parent = client.post("/decks/folders", json={"name": "Parent"}).get_json()["folder"]
    resp = client.post("/decks/folders", json={"name": "Sub", "parent_id": parent["id"]})
    assert resp.status_code == 201
    assert resp.get_json()["folder"]["parent_id"] == parent["id"]


def test_create_folder_rejects_blank_name(app, folders_setup):
    client = _client(app, 1)
    resp = client.post("/decks/folders", json={"name": "   "})
    assert resp.status_code == 400


def _seed_bob_folder(app):
    """Create a folder owned by Bob (player_id=2) directly in the DB and return
    its id. Seeding directly (rather than via a second HTTP client) keeps each
    test to a single authenticated client, avoiding cross-client login bleed."""
    with app.app_context():
        folder = DeckFolder(player_id=2, name="BobFolder")
        _db.session.add(folder)
        _db.session.commit()
        return folder.id


def test_create_subfolder_rejects_foreign_parent(app, folders_setup):
    # Alice cannot nest a folder under Bob's folder.
    bob_folder_id = _seed_bob_folder(app)
    alice = _client(app, 1)
    resp = alice.post("/decks/folders", json={"name": "X", "parent_id": bob_folder_id})
    assert resp.status_code == 404


# --- move_deck_to_folder --------------------------------------------------

def test_move_deck_into_folder(app, folders_setup):
    client = _client(app, 1)
    folder = client.post("/decks/folders", json={"name": "F"}).get_json()["folder"]
    resp = client.post(f"/decks/1/folder", json={"folder_id": folder["id"]})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    with app.app_context():
        assert _db.session.get(Deck, 1).folder_id == folder["id"]


def test_move_deck_to_root(app, folders_setup):
    client = _client(app, 1)
    folder = client.post("/decks/folders", json={"name": "F"}).get_json()["folder"]
    client.post(f"/decks/1/folder", json={"folder_id": folder["id"]})
    resp = client.post(f"/decks/1/folder", json={"folder_id": None})
    assert resp.status_code == 200
    with app.app_context():
        assert _db.session.get(Deck, 1).folder_id is None


def test_move_deck_rejects_non_owner(app, folders_setup):
    # Bob tries to move Alice's deck (id=1).
    bob = _client(app, 2)
    resp = bob.post("/decks/1/folder", json={"folder_id": None})
    assert resp.status_code == 403


def test_move_deck_rejects_foreign_target_folder(app, folders_setup):
    bob_folder_id = _seed_bob_folder(app)
    alice = _client(app, 1)
    resp = alice.post("/decks/1/folder", json={"folder_id": bob_folder_id})
    assert resp.status_code == 404


# --- my_decks folder-scoped view -----------------------------------------

def test_my_decks_root_lists_unfiled_decks_and_folders(app, folders_setup):
    client = _client(app, 1)
    folder = client.post("/decks/folders", json={"name": "MyFolder"}).get_json()["folder"]
    # Move Alpha into the folder; root should then show only Beta.
    client.post("/decks/1/folder", json={"folder_id": folder["id"]})
    resp = client.get("/decks/mine")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert "MyFolder" in body
    assert "Beta" in body
    assert 'data-deck-id="1"' not in body  # Alpha moved out of root


def test_my_decks_folder_view_lists_contained_deck(app, folders_setup):
    client = _client(app, 1)
    folder = client.post("/decks/folders", json={"name": "MyFolder"}).get_json()["folder"]
    client.post("/decks/1/folder", json={"folder_id": folder["id"]})
    resp = client.get(f"/decks/mine/folder/{folder['id']}")
    assert resp.status_code == 200
    body = resp.data.decode("utf-8")
    assert 'data-deck-id="1"' in body  # Alpha is inside this folder
    assert "Up one level" in body


def test_my_decks_foreign_folder_404(app, folders_setup):
    bob_folder_id = _seed_bob_folder(app)
    alice = _client(app, 1)
    resp = alice.get(f"/decks/mine/folder/{bob_folder_id}")
    assert resp.status_code == 404
