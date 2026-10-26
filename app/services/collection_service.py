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

    for entry in entries:
        # Match the EXACT printing by Scryfall id. Never fall back to another
        # printing — if this exact printing isn't stored, the entry is left out
        # and reported, not rewritten to a different card.
        card_id = db.session.scalar(
            sa.select(Card.id).where(Card.id == entry.scryfall_id)
        )
        if card_id is None:
            result.unimported.append(entry)
            continue
        result.imported += 1

        existing = None
        if not replace:
            existing = db.session.scalar(
                sa.select(PlayerCollectionCard).where(
                    PlayerCollectionCard.player_id == player_id,
                    PlayerCollectionCard.scryfall_id == entry.scryfall_id,
                    PlayerCollectionCard.finish == entry.finish,
                    PlayerCollectionCard.condition == entry.condition,
                    PlayerCollectionCard.language == entry.language,
                )
            )

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
