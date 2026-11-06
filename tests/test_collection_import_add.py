"""Tests for collection import formats/modes and the single-card add flow.

Covers:
  * ManaBox CSV detection + value mapping onto the stored tokens
    (Normal/Foil/Etched, NM/LP/MP/HP/D, EN/DE/JP/...).
  * The import route's replace vs add (merge) modes.
  * GET /collection/printings (step 2) and POST /collection/add (step 3),
    including merge into an existing entry and input validation.
"""

import io

import pytest
from flask_login import FlaskLoginClient

from app import db as _db
from app.models import Player, User, Card, CardFace, PlayerCollectionCard
from app.services.collection_service import (
    parse_collection_csv,
    detect_csv_format,
    FORMAT_MANABOX,
    FORMAT_STANDARD,
)

MANABOX_HEADER = (
    "Name,Set code,Set name,Collector number,Foil,Rarity,Quantity,ManaBox ID,"
    "Scryfall ID,Purchase price,Misprint,Altered,Signed,Condition,Language,Proxy,"
    "Purchase price currency,Added\n"
)

STANDARD_HEADER = (
    "Quantity,Name,Finish,Condition,Date Added,Language,Purchase Price,Tags,"
    "Edition Name,Edition Code,Multiverse Id,Scryfall ID,Collector Number\n"
)


def _mb_row(name, scryfall_id, qty=1, foil="normal", condition="near_mint", lang="en",
            set_code="fra", set_name="Reality Fracture", number="1"):
    return (f'"{name}",{set_code},{set_name},{number},{foil},rare,{qty},1,{scryfall_id},'
            f'1.00,false,false,false,{condition},{lang},false,EUR,2026-10-08T20:09:29.912Z\n')


def _card(cid, oracle, name, set_code="fra", set_name="Reality Fracture", released=None):
    return Card(
        id=cid, oracle_id=oracle, name=name, cmc=0, type_line="Creature",
        layout="normal", set_code=set_code, set_name=set_name, rarity="rare",
        released_at=released,
    )


@pytest.fixture()
def setup(app):
    """Alice (player 1) and two printings of Jace plus one Chandra printing."""
    import datetime as dt

    with app.app_context():
        for model in (PlayerCollectionCard, CardFace, Card, User, Player):
            _db.session.query(model).delete()
        _db.session.commit()

        alice = User(id=1, username="alice", email="a@e.com", player_id=1, active=True, role="user")
        alice.set_password("pw")
        _db.session.add(alice)
        _db.session.add(Player(id=1, name="Alice"))
        _db.session.add_all([
            _card("jace-old", "JACE", "Jace, Reality Sculptor", "old", "Old Set", dt.date(2020, 1, 1)),
            _card("jace-new", "JACE", "Jace, Reality Sculptor", "fra", "Reality Fracture", dt.date(2026, 9, 1)),
            _card("chandra", "CHANDRA", "Chandra, Torch of Defiance"),
        ])
        _db.session.flush()
        _db.session.add(CardFace(card_id="jace-new", face_index=0, name="Jace, Reality Sculptor",
                                 image_uri="https://cards.scryfall.io/large/front/j/n/jace-new.jpg"))
        _db.session.commit()
        yield _db.session

        for model in (PlayerCollectionCard, CardFace, Card, User, Player):
            _db.session.query(model).delete()
        _db.session.commit()


def _client(app, user_id=1):
    app.test_client_class = FlaskLoginClient
    return app.test_client(user=_db.session.get(User, user_id))


def _upload(client, text, mode=None):
    data = {"csv_file": (io.BytesIO(text.encode("utf-8")), "export.csv")}
    if mode is not None:
        data["mode"] = mode
    return client.post("/collection/import", data=data, content_type="multipart/form-data")


def _entries(app):
    with app.app_context():
        return sorted(
            (e.scryfall_id, e.finish, e.condition, e.language, e.count)
            for e in PlayerCollectionCard.query.filter_by(player_id=1).all()
        )


# --- ManaBox parsing -----------------------------------------------------------

def test_detects_formats():
    assert detect_csv_format(MANABOX_HEADER.strip().split(",")) == FORMAT_MANABOX
    assert detect_csv_format(STANDARD_HEADER.strip().split(",")) == FORMAT_STANDARD


def test_manabox_rows_mapped_to_stored_tokens():
    text = (MANABOX_HEADER
            + _mb_row("Jace, Reality Sculptor", "jace-new", qty=2, foil="foil",
                      condition="near_mint", lang="de", number="300")
            + _mb_row("Chandra, Torch of Defiance", "chandra", foil="etched",
                      condition="light_played", lang="ja"))
    entries, result = parse_collection_csv(io.StringIO(text))
    assert result.rows_read == 2 and result.rows_skipped == 0
    jace, chandra = entries
    assert (jace.scryfall_id, jace.finish, jace.condition, jace.language, jace.count) == \
        ("jace-new", "Foil", "NM", "DE", 2)
    assert (jace.name, jace.set_code, jace.set_name, jace.collector_number) == \
        ("Jace, Reality Sculptor", "fra", "Reality Fracture", "300")
    assert (chandra.finish, chandra.condition, chandra.language) == ("Etched", "LP", "JP")


def test_manabox_duplicate_rows_collapse():
    text = MANABOX_HEADER + _mb_row("Chandra, Torch of Defiance", "chandra") * 3
    entries, _ = parse_collection_csv(io.StringIO(text))
    assert len(entries) == 1 and entries[0].count == 3


def test_manabox_missing_required_column():
    bad_header = MANABOX_HEADER.replace("Scryfall ID,", "")
    with pytest.raises(ValueError, match="ManaBox CSV is missing"):
        parse_collection_csv(io.StringIO(bad_header))


def test_manabox_sample_from_user(app, setup):
    """The exact header/row shape the user provided imports end to end."""
    text = (MANABOX_HEADER
            + '"Chandra, Torch of Defiance",FRA,Reality Fracture,244,normal,mythic,1,112896,'
              'chandra,1.73,false,false,false,near_mint,en,false,EUR,2026-10-08T20:09:29.916Z\n')
    resp = _upload(_client(app), text, mode="add")
    assert resp.status_code == 302
    assert _entries(app) == [("chandra", "Normal", "NM", "EN", 1)]


# --- Import modes --------------------------------------------------------------

def test_import_replace_mode_replaces_collection(app, setup):
    client = _client(app)
    _upload(client, MANABOX_HEADER + _mb_row("Chandra, Torch of Defiance", "chandra"), mode="replace")
    _upload(client, MANABOX_HEADER + _mb_row("Jace, Reality Sculptor", "jace-new"), mode="replace")
    assert _entries(app) == [("jace-new", "Normal", "NM", "EN", 1)]


def test_import_default_mode_is_replace(app, setup):
    client = _client(app)
    _upload(client, MANABOX_HEADER + _mb_row("Chandra, Torch of Defiance", "chandra"))
    _upload(client, MANABOX_HEADER + _mb_row("Jace, Reality Sculptor", "jace-new"))
    assert _entries(app) == [("jace-new", "Normal", "NM", "EN", 1)]


def test_import_add_mode_merges(app, setup):
    client = _client(app)
    _upload(client, MANABOX_HEADER + _mb_row("Chandra, Torch of Defiance", "chandra", qty=2), mode="add")
    _upload(client, MANABOX_HEADER
            + _mb_row("Chandra, Torch of Defiance", "chandra", qty=1)
            + _mb_row("Jace, Reality Sculptor", "jace-new"), mode="add")
    assert _entries(app) == [
        ("chandra", "Normal", "NM", "EN", 3),
        ("jace-new", "Normal", "NM", "EN", 1),
    ]


def test_import_rejects_unknown_mode(app, setup):
    _upload(_client(app), MANABOX_HEADER + _mb_row("Chandra, Torch of Defiance", "chandra"), mode="wipe")
    assert _entries(app) == []


def test_import_unknown_printing_is_skipped(app, setup):
    _upload(_client(app), MANABOX_HEADER + _mb_row("Ghost", "not-in-db"), mode="add")
    assert _entries(app) == []


# --- Step 2: printings -----------------------------------------------------------

def test_printings_lists_all_printings_newest_first(app, setup):
    resp = _client(app).get("/collection/printings?name=Jace, Reality Sculptor")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert [p["id"] for p in data["printings"]] == ["jace-new", "jace-old"]
    # Image is the front face, downsized from 'large' to 'normal'.
    assert data["printings"][0]["image"] == "https://cards.scryfall.io/normal/front/j/n/jace-new.jpg"
    assert data["printings"][1]["image"] is None
    assert data["printings"][0]["set_name"] == "Reality Fracture"


def test_printings_unknown_name_404(app, setup):
    assert _client(app).get("/collection/printings?name=Nope").status_code == 404


def test_printings_requires_name(app, setup):
    assert _client(app).get("/collection/printings").status_code == 400


# --- Step 3: add -----------------------------------------------------------------

def _add(client, **body):
    payload = {"card_id": "jace-new", "count": 1, "finish": "Normal", "language": "EN"}
    payload.update(body)
    return client.post("/collection/add", json=payload)


def test_add_creates_entry_from_card(app, setup):
    resp = _add(_client(app), count=2, finish="Foil", language="DE")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "created": True, "count": 2}
    with app.app_context():
        e = PlayerCollectionCard.query.filter_by(player_id=1).one()
        assert (e.card_id, e.scryfall_id, e.name, e.set_code, e.set_name) == \
            ("jace-new", "jace-new", "Jace, Reality Sculptor", "fra", "Reality Fracture")
        assert (e.finish, e.condition, e.language, e.count) == ("Foil", "NM", "DE", 2)


def test_add_merges_into_matching_entry(app, setup):
    client = _client(app)
    _add(client, count=1)
    resp = _add(client, count=3)
    assert resp.get_json() == {"ok": True, "created": False, "count": 4}
    assert _entries(app) == [("jace-new", "Normal", "NM", "EN", 4)]


def test_add_different_finish_is_separate_entry(app, setup):
    client = _client(app)
    _add(client, finish="Normal")
    _add(client, finish="Foil")
    assert _entries(app) == [
        ("jace-new", "Foil", "NM", "EN", 1),
        ("jace-new", "Normal", "NM", "EN", 1),
    ]


@pytest.mark.parametrize("body", [
    {"count": 0}, {"count": 1000}, {"count": "2"}, {"count": True}, {"count": 1.5},
    {"finish": "Shiny"}, {"language": "XX"},
])
def test_add_validates_input(app, setup, body):
    resp = _add(_client(app), **body)
    assert resp.status_code == 400
    assert _entries(app) == []


def test_add_unknown_card_404(app, setup):
    assert _add(_client(app), card_id="nope").status_code == 404


def test_collection_page_has_add_dialog(app, setup):
    body = _client(app).get("/collection").data.decode("utf-8")
    assert 'id="ca-modal"' in body
    assert 'name="mode" value="add"' in body
    assert 'value="Etched"' in body and 'value="JP"' in body


# --- Remove from collection (popup) ---------------------------------------------

def _seed_entry(app, count=3, player_id=1, finish="Normal"):
    with app.app_context():
        e = PlayerCollectionCard(
            player_id=player_id, card_id="jace-new", scryfall_id="jace-new",
            finish=finish, condition="NM", language="EN",
            name="Jace, Reality Sculptor", set_code="fra", set_name="Reality Fracture",
            count=count,
        )
        _db.session.add(e)
        _db.session.commit()
        return e.id


def _remove(client, entry_id, amount):
    return client.post(f"/collection/entry/{entry_id}/remove", json={"amount": amount})


def test_remove_one_decrements(app, setup):
    eid = _seed_entry(app, count=3)
    resp = _remove(_client(app), eid, "one")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "remaining": 2}
    assert _entries(app) == [("jace-new", "Normal", "NM", "EN", 2)]


def test_remove_one_last_copy_deletes_entry(app, setup):
    eid = _seed_entry(app, count=1)
    assert _remove(_client(app), eid, "one").get_json() == {"ok": True, "remaining": 0}
    assert _entries(app) == []


def test_remove_all_deletes_whole_stack(app, setup):
    eid = _seed_entry(app, count=4)
    assert _remove(_client(app), eid, "all").get_json() == {"ok": True, "remaining": 0}
    assert _entries(app) == []


def test_remove_only_touches_that_stack(app, setup):
    keep = _seed_entry(app, count=2, finish="Foil")
    eid = _seed_entry(app, count=2, finish="Normal")
    _remove(_client(app), eid, "all")
    assert _entries(app) == [("jace-new", "Foil", "NM", "EN", 2)]
    assert keep


def test_remove_rejects_other_players_entry(app, setup):
    with app.app_context():
        _db.session.add(Player(id=2, name="Bob"))
        _db.session.commit()
    eid = _seed_entry(app, count=2, player_id=2)
    resp = _remove(_client(app), eid, "all")
    assert resp.status_code == 403
    with app.app_context():
        assert _db.session.get(PlayerCollectionCard, eid).count == 2


def test_remove_rejects_bad_amount(app, setup):
    eid = _seed_entry(app, count=2)
    assert _remove(_client(app), eid, "half").status_code == 400
    assert _entries(app) == [("jace-new", "Normal", "NM", "EN", 2)]


def test_remove_unknown_entry_404(app, setup):
    assert _remove(_client(app), 99999, "one").status_code == 404


def test_collection_tiles_carry_stack_data(app, setup):
    eid = _seed_entry(app, count=2, finish="Foil")
    body = _client(app).get("/collection").data.decode("utf-8")
    assert f'data-entry-id="{eid}"' in body
    assert 'data-count="2"' in body and 'data-finish="Foil"' in body
    assert 'id="cc-modal-remove"' in body
