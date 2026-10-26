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
            sa.select(Card.id, Card.price_eur, Card.price_eur_foil)
            .where(Card.id.in_(card_ids))
        ).all()
        prices = {
            cid: {"eur": eur, "eur_foil": eur_foil}
            for cid, eur, eur_foil in price_rows
        }

    result: list[dict] = []
    for e in entries:
        foil = _is_foil(e.finish)
        price = None
        if e.card_id and e.card_id in prices:
            price = prices[e.card_id]["eur_foil" if foil else "eur"]
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
            "scryfall_id": e.scryfall_id,
            "card_id": e.card_id,
        })

    result.sort(key=lambda r: (
        (r["name"] or "").lower(),
        (r["set_code"] or ""),
        (r["finish"] or ""),
    ))
    return result
