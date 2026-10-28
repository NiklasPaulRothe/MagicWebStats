"""Collection service: import a player's card collection from a CSV export.

Parses a collection CSV (the Moxfield/ManaBox-style export whose header is
`Quantity,Name,Finish,Condition,Date Added,Language,Purchase Price,Tags,
Edition Name,Edition Code,Multiverse Id,Scryfall ID,Collector Number`), collapses
rows into counts, resolves each to a card in our DB, and writes
PlayerCollectionCard rows.

Collapse rule
-------------
Two source rows combine into one entry — their quantities summed — ONLY when the
printing, finish, condition and language are all identical. The dedup key is
therefore (scryfall_id, finish, condition, language) within a single player.
A foil and a non-foil of the same printing stay as separate entries, as do two
different conditions or languages. Per-acquisition metadata (Date Added,
Purchase Price, Tags) is not part of the identity and is dropped on collapse.

Card resolution
---------------
Each entry is matched to a cards (printing) row by its EXACT Scryfall id only.
There is deliberately no fallback to another printing (e.g. by name or
set/collector number): importing a collection must never silently record a
different printing than the one the player owns. When a row's Scryfall id is not
present in our cards table, that row is NOT imported — it is collected and
returned in ImportResult.unimported so the caller can show the user exactly
which cards were left out (typically because the nightly card fetch hasn't
ingested that printing yet).

None of the functions here commit the session — the caller is responsible for
committing (matching the rest of the services layer).
"""

from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Iterable, TextIO

import sqlalchemy as sa

from app import db
from app.models import Card, PlayerCollectionCard

# CSV header names (exact, as exported).
COL_QUANTITY = "Quantity"
COL_NAME = "Name"
COL_FINISH = "Finish"
COL_CONDITION = "Condition"
COL_LANGUAGE = "Language"
COL_EDITION_NAME = "Edition Name"
COL_EDITION_CODE = "Edition Code"
COL_SCRYFALL_ID = "Scryfall ID"
COL_COLLECTOR_NUMBER = "Collector Number"

REQUIRED_COLUMNS = {
    COL_QUANTITY,
    COL_NAME,
    COL_FINISH,
    COL_CONDITION,
    COL_LANGUAGE,
    COL_SCRYFALL_ID,
}


@dataclass
class CollapsedEntry:
    """One distinct physical card after collapsing, with its summed count."""

    scryfall_id: str
    finish: str
    condition: str
    language: str
    name: str
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    count: int = 0


@dataclass
class ImportResult:
    """Summary of an import run (for logging / CLI output)."""

    rows_read: int = 0
    rows_skipped: int = 0
    distinct_entries: int = 0
    total_quantity: int = 0
    # Distinct entries whose exact Scryfall printing was found and written.
    imported: int = 0
    # Distinct entries NOT written because their exact Scryfall printing is not
    # in our cards table. Reported back so the user can see what was left out.
    unimported: list[CollapsedEntry] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_quantity(raw: str | None) -> int:
    """Parse a Quantity cell to a positive int; 0/blank/invalid → 0 (skip)."""
    raw = _clean(raw)
    if not raw:
        return 0
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def collapse_rows(rows: Iterable[dict]) -> tuple[list[CollapsedEntry], ImportResult]:
    """Collapse raw CSV dict-rows into deduplicated entries with summed counts.

    Rows are combined when (scryfall_id, finish, condition, language) match.
    Insertion order of first appearance is preserved. Rows without a Scryfall ID
    or with a non-positive quantity are skipped (and counted in the result).
    """
    result = ImportResult()
    collapsed: "OrderedDict[tuple, CollapsedEntry]" = OrderedDict()

    for row in rows:
        result.rows_read += 1

        scryfall_id = _clean(row.get(COL_SCRYFALL_ID))
        qty = _parse_quantity(row.get(COL_QUANTITY))
        name = _clean(row.get(COL_NAME))

        if not scryfall_id:
            result.rows_skipped += 1
            result.skipped_reasons.append(
                f"row {result.rows_read}: missing Scryfall ID ({name or 'unknown card'})"
            )
            continue
        if qty <= 0:
            result.rows_skipped += 1
            result.skipped_reasons.append(
                f"row {result.rows_read}: non-positive quantity ({name or scryfall_id})"
            )
            continue

        finish = _clean(row.get(COL_FINISH))
        condition = _clean(row.get(COL_CONDITION))
        language = _clean(row.get(COL_LANGUAGE))

        key = (scryfall_id, finish, condition, language)
        entry = collapsed.get(key)
        if entry is None:
            entry = CollapsedEntry(
                scryfall_id=scryfall_id,
                finish=finish,
                condition=condition,
                language=language,
                name=name,
                set_code=_clean(row.get(COL_EDITION_CODE)) or None,
                set_name=_clean(row.get(COL_EDITION_NAME)) or None,
                collector_number=_clean(row.get(COL_COLLECTOR_NUMBER)) or None,
            )
            collapsed[key] = entry
        entry.count += qty
        result.total_quantity += qty

    result.distinct_entries = len(collapsed)
    return list(collapsed.values()), result


def parse_collection_csv(stream: TextIO) -> tuple[list[CollapsedEntry], ImportResult]:
    """Read and collapse a collection CSV from an open text stream.

    Raises ValueError if required columns are missing from the header.
    """
    reader = csv.DictReader(stream)
    header = set(reader.fieldnames or [])
    missing = REQUIRED_COLUMNS - header
    if missing:
        raise ValueError(
            "CSV is missing required column(s): " + ", ".join(sorted(missing))
        )
    return collapse_rows(reader)


def import_player_collection(
    player_id: int,
    stream: TextIO,
    *,
    replace: bool = True,
) -> ImportResult:
    """Import a player's collection from a CSV stream into player_collection.

    Collapses the CSV to deduplicated entries, resolves each to a card_id, and
    writes PlayerCollectionCard rows for the given player. Does NOT commit — the
    caller is responsible for committing (and for rolling back on error).

    Args:
        player_id: The players.id the collection belongs to.
        stream: An open text stream positioned at the start of the CSV.
        replace: When True (default), the player's existing collection rows are
            deleted first so the import reflects the file exactly. When False,
            entries are merged: a matching existing entry has the new count
            added to it, otherwise a new row is inserted.

    Returns:
        An ImportResult summarizing the run.
    """
    entries, result = parse_collection_csv(stream)

    if replace:
        PlayerCollectionCard.query.filter(
            PlayerCollectionCard.player_id == player_id
        ).delete(synchronize_session=False)
        # Flush so DELETEs hit the DB before INSERTs, avoiding unique-constraint
        # collisions when the same entry is re-inserted (same pattern as the
        # deck-tag re-import in deckbuilder.py).
        db.session.flush()

    # Resolve EXACT printings in bulk: one query (chunked) for all distinct
    # Scryfall ids in the file, instead of a per-entry round-trip. This keeps
    # the import fast even against a remote database, where per-row latency
    # would otherwise dominate (30k entries -> 30k round-trips). The matching
    # semantics are unchanged: an id is kept only if that exact printing exists
    # in our cards table; anything else goes to result.unimported.
    scryfall_ids = {e.scryfall_id for e in entries}
    known_ids = _existing_card_ids(scryfall_ids)

    # For merge mode, load the player's current entries once, keyed by the dedup
    # tuple, so matching is an in-memory lookup rather than a query per entry.
    existing_by_key: dict[tuple, PlayerCollectionCard] = {}
    if not replace:
        for row in PlayerCollectionCard.query.filter(
            PlayerCollectionCard.player_id == player_id
        ).all():
            existing_by_key[(
                row.scryfall_id, row.finish, row.condition, row.language
            )] = row

    for entry in entries:
        # Never fall back to another printing — if this exact printing isn't
        # stored, the entry is left out and reported, not rewritten.
        if entry.scryfall_id not in known_ids:
            result.unimported.append(entry)
            continue
        result.imported += 1
        card_id = entry.scryfall_id

        existing = None
        if not replace:
            existing = existing_by_key.get((
                entry.scryfall_id, entry.finish, entry.condition, entry.language
            ))

        if existing is not None:
            existing.count += entry.count
            existing.card_id = card_id
        else:
            db.session.add(
                PlayerCollectionCard(
                    player_id=player_id,
                    card_id=card_id,
                    scryfall_id=entry.scryfall_id,
                    finish=entry.finish,
                    condition=entry.condition,
                    language=entry.language,
                    name=entry.name,
                    set_code=entry.set_code,
                    set_name=entry.set_name,
                    collector_number=entry.collector_number,
                    count=entry.count,
                )
            )

    return result


# Postgres caps bind parameters per statement (~65535). Chunk IN (...) lookups
# well under that so even a huge collection resolves in a handful of queries.
_ID_LOOKUP_CHUNK = 10000


def _existing_card_ids(scryfall_ids: Iterable[str]) -> set[str]:
    """Return the subset of the given Scryfall ids that exist in cards.

    Runs one `WHERE id IN (...)` query per chunk instead of one query per id.
    """
    ids = [i for i in set(scryfall_ids) if i]
    found: set[str] = set()
    for start in range(0, len(ids), _ID_LOOKUP_CHUNK):
        chunk = ids[start:start + _ID_LOOKUP_CHUNK]
        rows = db.session.scalars(
            sa.select(Card.id).where(Card.id.in_(chunk))
        ).all()
        found.update(rows)
    return found


# Finish values (from the CSV `Finish` column) that denote a foil printing.
# Everything else (Normal, etc.) uses the non-foil EUR price.
_FOIL_FINISHES = {"foil", "etched"}


def _is_foil(finish: str | None) -> bool:
    return (finish or "").strip().lower() in _FOIL_FINISHES


def get_player_collection(player_id: int) -> list[dict]:
    """Return a player's collection as view-ready dicts for the collection page.

    Joins each PlayerCollectionCard to its Card (for the image and EUR price).
    The EUR price is chosen by finish: foil/etched entries use the card's
    price_eur_foil, everything else uses price_eur. The card image is the front
    face (face_index == 0) image_uri. Entries are sorted by card name, then set
    code, then finish for a stable gallery order.

    Each dict has: name, set_code, set_name, collector_number, finish,
    condition, language, count, image (str|None), price (Decimal|None),
    scryfall_id, card_id.
    """
    from app.models import CardFace

    # Pull the front-face image for each collected card in one query, keyed by
    # card_id, to avoid a per-row lookup.
    entries = (
        PlayerCollectionCard.query
        .filter(PlayerCollectionCard.player_id == player_id)
        .all()
    )
    card_ids = {e.card_id for e in entries if e.card_id}

    images: dict[str, str] = {}
    prices: dict[str, dict] = {}
    if card_ids:
        face_rows = db.session.execute(
            sa.select(CardFace.card_id, CardFace.image_uri)
            .where(CardFace.card_id.in_(card_ids), CardFace.face_index == 0)
        ).all()
        images = {cid: uri for cid, uri in face_rows}

        price_rows = db.session.execute(
            sa.select(
                Card.id, Card.price_eur, Card.price_eur_foil, Card.type_line
            )
            .where(Card.id.in_(card_ids))
        ).all()
        prices = {
            cid: {"eur": eur, "eur_foil": eur_foil, "type_line": type_line}
            for cid, eur, eur_foil, type_line in price_rows
        }

    result: list[dict] = []
    for e in entries:
        foil = _is_foil(e.finish)
        price = None
        type_line = None
        if e.card_id and e.card_id in prices:
            price = prices[e.card_id]["eur_foil" if foil else "eur"]
            type_line = prices[e.card_id]["type_line"]
        result.append({
            "name": e.name,
            "set_code": e.set_code,
            "set_name": e.set_name,
            "collector_number": e.collector_number,
            "finish": e.finish,
            "condition": e.condition,
            "language": e.language,
            "count": e.count,
            "image": images.get(e.card_id) if e.card_id else None,
            "price": price,
            "type_line": type_line,
            "scryfall_id": e.scryfall_id,
            "card_id": e.card_id,
        })

    result.sort(key=lambda r: (
        (r["name"] or "").lower(),
        (r["set_code"] or ""),
        (r["finish"] or ""),
    ))
    return result


# Ownership classification labels for the deck "collection" view.
OWNERSHIP_EXACT = "exact"       # player owns this exact printing (same card_id)
OWNERSHIP_OTHER = "other"       # player owns a different printing (same oracle)
OWNERSHIP_NONE = "none"         # player owns no printing of this card


def classify_deck_ownership(player_id: int, card_ids: Iterable[str]) -> dict[str, str]:
    """Classify each deck card_id by how the player owns it.

    Returns a mapping card_id -> one of OWNERSHIP_EXACT / OWNERSHIP_OTHER /
    OWNERSHIP_NONE:

      * EXACT  — the player's collection contains this exact printing (the same
                 card_id / Scryfall printing).
      * OTHER  — the player owns a *different* printing of the same card (matched
                 by the card's oracle_id, shared across printings), but not this
                 exact one.
      * NONE   — the player owns no printing of this card.

    Done in two bulk queries (not per card): the player's owned printing ids,
    and the oracle_ids spanning both the owned printings and the deck's cards.
    card_ids that don't resolve to a Card row are classified NONE.
    """
    card_ids = [c for c in dict.fromkeys(card_ids) if c]  # de-dup, keep order
    if not card_ids:
        return {}

    # Owned exact printing ids for this player (card_id is the printing id).
    owned_ids: set[str] = set(db.session.scalars(
        sa.select(PlayerCollectionCard.card_id).where(
            PlayerCollectionCard.player_id == player_id,
            PlayerCollectionCard.card_id.is_not(None),
        )
    ).all())

    # oracle_id for every deck card and every owned printing, so we can detect
    # "owns a different printing of the same card".
    relevant_ids = set(card_ids) | owned_ids
    oracle_by_card: dict[str, str] = {}
    if relevant_ids:
        rows = db.session.execute(
            sa.select(Card.id, Card.oracle_id).where(Card.id.in_(relevant_ids))
        ).all()
        oracle_by_card = {cid: oid for cid, oid in rows}

    owned_oracles = {
        oracle_by_card[cid] for cid in owned_ids if cid in oracle_by_card
    }

    result: dict[str, str] = {}
    for cid in card_ids:
        if cid in owned_ids:
            result[cid] = OWNERSHIP_EXACT
        elif oracle_by_card.get(cid) in owned_oracles:
            result[cid] = OWNERSHIP_OTHER
        else:
            result[cid] = OWNERSHIP_NONE
    return result


# =============================================================================
# Collection tracking: physical/proxy marking and availability status.
# =============================================================================
#
# These mirror the SQL views v_player_printing_availability and
# v_deck_card_collection_status (see scripts/add_deck_component_collection_
# tracking.sql) but are computed in Python so the deck overview and collection
# pages can render the status with a couple of bulk queries, and so the logic
# is testable without Postgres. The matching rule is EXACT: a deck card claims
# one collection copy of the same printing (card_id) + finish + language
# (case-insensitive); condition is ignored.

# Per-deck-card status values (deck overview).
DECK_STATUS_IN_DECK_OK = "in_deck_ok"
DECK_STATUS_IN_DECK_FAULTY = "in_deck_faulty"
DECK_STATUS_PROXY = "proxy"
DECK_STATUS_AVAILABLE = "available"
DECK_STATUS_OWNED_NO_COPY = "owned_no_copy"
DECK_STATUS_OWNED_OTHER = "owned_other"
DECK_STATUS_NOT_OWNED = "not_owned"

# Per-collection-entry status values (collection page).
COLL_STATUS_IN_DECK = "owned_in_deck"
COLL_STATUS_SPARE = "owned_spare_available"
COLL_STATUS_OTHER_PRINTING = "owned_different_printing_available"
COLL_STATUS_NO_COPY = "owned_no_copy_available"
COLL_STATUS_NOT_OWNED = "not_owned"

VALID_PHYSICAL_STATUSES = ("unset", "in_deck", "proxy")


def _norm(value: str | None) -> str:
    """Normalize a finish/language token for pool matching (lower, stripped)."""
    return (value or "").strip().lower()


def _pool_key(card_id: str | None, finish: str | None, language: str | None) -> tuple:
    return (card_id, _norm(finish), _norm(language))


def _player_owned_pools(player_id: int) -> dict[tuple, int]:
    """Owned copies per (card_id, finish_key, language_key) for a player.

    Only resolved rows (card_id not NULL) participate — an unresolved printing
    can't be matched to a deck card's printing.
    """
    rows = db.session.execute(
        sa.select(
            PlayerCollectionCard.card_id,
            PlayerCollectionCard.finish,
            PlayerCollectionCard.language,
            PlayerCollectionCard.count,
        ).where(
            PlayerCollectionCard.player_id == player_id,
            PlayerCollectionCard.card_id.is_not(None),
        )
    ).all()
    owned: dict[tuple, int] = {}
    for card_id, finish, language, count in rows:
        key = _pool_key(card_id, finish, language)
        owned[key] = owned.get(key, 0) + (count or 0)
    return owned


def _player_claimed_pools(player_id: int) -> dict[tuple, int]:
    """Copies claimed 'in_deck' per pool across all of a player's decks."""
    from app.models import Deck, DeckComponent

    rows = db.session.execute(
        sa.select(
            DeckComponent.card_id,
            DeckComponent.physical_finish,
            DeckComponent.physical_language,
            DeckComponent.count,
        )
        .join(Deck, Deck.id == DeckComponent.deck_id)
        .where(
            Deck.player_id == player_id,
            DeckComponent.physical_status == "in_deck",
            DeckComponent.card_id.is_not(None),
        )
    ).all()
    claimed: dict[tuple, int] = {}
    for card_id, finish, language, count in rows:
        key = _pool_key(card_id, finish, language)
        claimed[key] = claimed.get(key, 0) + (count or 1)
    return claimed


def get_collection_finish_language_options(player_id: int) -> dict[str, list[str]]:
    """Distinct finish and language tokens in a player's collection.

    Used to populate the deck-overview collection editor's dropdowns with the
    exact tokens the collection stores (so an edit always targets a real pool).
    The common defaults ('Normal' / 'EN') are always included and placed first,
    even if the collection is empty, so a fresh account still has sane choices.
    """
    finish_rows = db.session.scalars(
        sa.select(PlayerCollectionCard.finish)
        .where(PlayerCollectionCard.player_id == player_id)
        .distinct()
    ).all()
    language_rows = db.session.scalars(
        sa.select(PlayerCollectionCard.language)
        .where(PlayerCollectionCard.player_id == player_id)
        .distinct()
    ).all()

    def _ordered(values: Iterable[str], default: str) -> list[str]:
        seen: list[str] = [default]
        for v in sorted(x for x in values if x and x != default):
            if v not in seen:
                seen.append(v)
        return seen

    return {
        "finishes": _ordered(finish_rows, "Normal"),
        "languages": _ordered(language_rows, "EN"),
    }


def compute_deck_collection_status(player_id: int, deck_id: int) -> dict[int, dict]:
    """Resolve each in-deck component's collection status for a deck.

    Returns a mapping deck_component_id -> {
        'status': one of DECK_STATUS_*,
        'physical_status': 'unset'|'in_deck'|'proxy',
        'finish': str|None, 'language': str|None,
        'owned': int, 'claimed': int,
    }. Mirrors v_deck_card_collection_status.
    """
    from app.models import Deck, DeckComponent

    components = db.session.scalars(
        sa.select(DeckComponent).where(
            DeckComponent.deck_id == deck_id,
            DeckComponent.in_deck.is_(True),
        )
    ).all()
    if not components:
        return {}

    owned = _player_owned_pools(player_id)
    claimed = _player_claimed_pools(player_id)

    # Oracle-level totals (summed across ALL printings/finishes/languages of a
    # card). Used for the fallback when the exact printing isn't owned: whether
    # a *free physical copy of the card* exists at all — printing doesn't matter
    # for that question. We map every owned/claimed/deck printing to its oracle.
    all_card_ids = (
        {k[0] for k in owned} | {k[0] for k in claimed}
        | {c.card_id for c in components if c.card_id}
    )
    oracle_by_card: dict[str, str] = {}
    if all_card_ids:
        rows = db.session.execute(
            sa.select(Card.id, Card.oracle_id).where(Card.id.in_(all_card_ids))
        ).all()
        oracle_by_card = {cid: oid for cid, oid in rows}

    owned_by_oracle: dict[str, int] = {}
    for (card_id, _f, _l), n in owned.items():
        oid = oracle_by_card.get(card_id)
        if oid:
            owned_by_oracle[oid] = owned_by_oracle.get(oid, 0) + n
    claimed_by_oracle: dict[str, int] = {}
    for (card_id, _f, _l), n in claimed.items():
        oid = oracle_by_card.get(card_id)
        if oid:
            claimed_by_oracle[oid] = claimed_by_oracle.get(oid, 0) + n

    result: dict[int, dict] = {}
    for comp in components:
        # Match on the exact pool (printing + finish + language). Finish and
        # language always have a concrete value (default 'Normal' / 'EN', set
        # from the deck source on import), so there's no NULL-vs-real mismatch.
        key = _pool_key(comp.card_id, comp.physical_finish, comp.physical_language)
        owned_n = owned.get(key, 0)
        claimed_n = claimed.get(key, 0)

        oid = oracle_by_card.get(comp.card_id)
        oracle_owned = owned_by_oracle.get(oid, 0) if oid else 0
        oracle_claimed = claimed_by_oracle.get(oid, 0) if oid else 0

        if comp.physical_status == "in_deck":
            status = (
                DECK_STATUS_IN_DECK_OK if claimed_n <= owned_n and owned_n > 0
                else DECK_STATUS_IN_DECK_FAULTY
            )
        elif comp.physical_status == "proxy":
            status = DECK_STATUS_PROXY
        else:  # unset
            if owned_n > claimed_n:
                # A free copy of this exact printing+finish+language exists.
                status = DECK_STATUS_AVAILABLE
            elif owned_n > 0:
                # Own this exact printing, but all its copies are allocated.
                status = DECK_STATUS_OWNED_NO_COPY
            elif oracle_owned > oracle_claimed:
                # Don't own this exact printing, but own the card in another
                # printing with a free copy -> owned (other printing).
                status = DECK_STATUS_OWNED_OTHER
            elif oracle_owned > 0:
                # Own the card (in some printing) but every copy across all
                # printings is allocated to a deck -> no free copy. Printing
                # doesn't matter here.
                status = DECK_STATUS_OWNED_NO_COPY
            else:
                status = DECK_STATUS_NOT_OWNED

        result[comp.id] = {
            "status": status,
            "physical_status": comp.physical_status,
            "finish": comp.physical_finish,
            "language": comp.physical_language,
            "owned": owned_n,
            "claimed": claimed_n,
        }
    return result


def update_deck_component_collection(
    player_id: int,
    deck_id: int,
    component_id: int,
    *,
    physical_status: str | None = None,
    card_id: str | None = None,
    finish: str | None = None,
    language: str | None = None,
    set_card_id: bool = False,
) -> "DeckComponent":
    """Owner-gated mutation of a deck component's collection fields.

    Only updates fields that are provided. ``physical_status`` must be one of
    VALID_PHYSICAL_STATUSES. ``card_id`` (the printing) is only changed when
    ``set_card_id`` is True (so callers can distinguish "leave printing alone"
    from "set printing to None"). Marking never auto-edits finish/language —
    the caller passes them explicitly. Does not commit.

    Raises ValueError on an invalid status or if the component doesn't belong
    to the deck; raises PermissionError if the deck isn't owned by player_id;
    raises LookupError if the deck or component is missing.
    """
    from app.models import Deck, DeckComponent

    deck = db.session.get(Deck, deck_id)
    if deck is None:
        raise LookupError("deck")
    if deck.player_id != player_id:
        raise PermissionError("not owner")

    comp = db.session.get(DeckComponent, component_id)
    if comp is None or comp.deck_id != deck_id:
        raise LookupError("component")

    if physical_status is not None:
        if physical_status not in VALID_PHYSICAL_STATUSES:
            raise ValueError("invalid physical_status")
        comp.physical_status = physical_status
    if set_card_id:
        comp.card_id = card_id
    if finish is not None:
        comp.physical_finish = finish or None
    if language is not None:
        comp.physical_language = language or None

    return comp


def get_collection_statuses(player_id: int) -> dict[tuple, str]:
    """Five-state status per collection pool for the collection page.

    Returns a mapping (card_id, finish_key, language_key) -> COLL_STATUS_*:
      * owned_in_deck            — some copy of this pool is claimed in a deck
      * owned_spare_available    — owned copies exceed those claimed in decks
      * owned_no_copy_available  — owned but every copy is claimed in decks
      * owned_different_printing_available — (pool has 0 owned here but the
        player owns another printing of the same card with a spare) — included
        for completeness; a collection *entry* always has owned>0 for its own
        pool, so this is computed at lookup time by the caller when needed.
      * not_owned                — no owned copies (not used for existing
        entries; included for symmetry).

    Because every real collection entry owns >=1 copy of its own pool, each
    entry resolves to one of: owned_in_deck, owned_spare_available,
    owned_no_copy_available. The "different printing" case is relevant only
    when asking about a card the player doesn't own in that exact pool, so the
    caller (deck view) uses compute_deck_collection_status for that; here we
    classify the player's own entries.
    """
    owned = _player_owned_pools(player_id)
    claimed = _player_claimed_pools(player_id)

    result: dict[tuple, str] = {}
    for key, owned_n in owned.items():
        claimed_n = claimed.get(key, 0)
        if claimed_n <= 0:
            result[key] = COLL_STATUS_SPARE
        elif owned_n > claimed_n:
            # Some claimed, some spare — still has a free copy.
            result[key] = COLL_STATUS_SPARE
        elif owned_n == claimed_n:
            result[key] = COLL_STATUS_IN_DECK
        else:  # claimed > owned: over-claimed, no free copy
            result[key] = COLL_STATUS_NO_COPY
    return result
