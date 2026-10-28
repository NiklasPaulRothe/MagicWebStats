"""
One-time migration: translate Archidekt per-card LABELS ("color tags") into the
owner-managed collection ``physical_status`` field, for a single player's decks.

Archidekt stores a free-text label per card (shown as a colored tag in the deck
editor). pyrchidekt exposes it as ``ArchidektCard.label``. Our importer never
persisted it, so this script fetches each deck fresh from Archidekt and maps the
label onto the matching stored deck component.

Mapping (label matched case-insensitively, trimmed):

    "Have"         -> in_deck
    "Proxy"        -> proxy
    "Paper Proxy"  -> proxy
    everything else / no label -> unset

Scope: only decks in our database belonging to ``--player-id`` (default 1) that
have an Archidekt source. Decks whose Archidekt deck can no longer be fetched
(deleted / made private on Archidekt — the API returns 404) are skipped and
reported; nothing we can do without the source data.

Matching fetched cards to stored components
-------------------------------------------
Each fetched card is resolved to a card_id the same way the importer does
(exact printing uid, else any printing of the same name). For every deck we pair
fetched cards and stored components that share a resolved card_id, in order, and
set the component's physical_status from the label. When ``--set-finish`` is
passed we also set physical_finish from Archidekt's per-card ``modifier``
(Normal/Foil/Etched) for cards that become in_deck.

DATABASE SAFETY
---------------
This script WRITES. Per the project's hard database-safety rule it must never
touch the production database (DATABASE_URL). It connects ONLY to
LOCAL_DATABASE_URL and refuses to run unless that URL is present, points at
localhost, and is not equal to DATABASE_URL. It never builds the Flask app
(which would bind the ORM to DATABASE_URL).

Dry run by default: reports what it would change and writes nothing. Pass
--apply to commit the UPDATEs inside a single transaction.

Usage:
    python scripts/migrate_color_tags_to_collection_status.py             # dry run, player 1
    python scripts/migrate_color_tags_to_collection_status.py --apply
    python scripts/migrate_color_tags_to_collection_status.py --apply --set-finish
    python scripts/migrate_color_tags_to_collection_status.py --player-id 3 --apply
"""

import argparse
import os
import sys
import time
from collections import Counter, defaultdict, deque
from urllib.parse import urlsplit

import sqlalchemy as sa
from dotenv import load_dotenv


# --- Label -> status mapping ----------------------------------------------
# Keys are normalized (lower-cased, stripped). Anything else -> 'unset'.
LABEL_TO_STATUS = {
    'have': 'in_deck',
    'proxy': 'proxy',
    'paper proxy': 'proxy',
}

# Delay between Archidekt fetches, matching the nightly importer's politeness.
FETCH_DELAY_SECONDS = 1.0


def map_status(label):
    """Map an Archidekt card label to a physical_status token."""
    if not label:
        return 'unset'
    return LABEL_TO_STATUS.get(str(label).strip().lower(), 'unset')


def normalize_finish(value):
    """Map Archidekt modifier to a 'Normal'/'Foil'/'Etched' token.

    Mirrors app.third_party_data.deckbuilder.normalize_finish so the migration
    stays consistent with the importer without importing the Flask app.
    """
    token = (value or '').strip().lower()
    if token in ('foil', 'f'):
        return 'Foil'
    if token in ('etched', 'foil-etched', 'foiletched'):
        return 'Etched'
    return 'Normal'


def resolve_local_url():
    """Return LOCAL_DATABASE_URL, refusing anything that looks like production."""
    load_dotenv()
    local_url = (os.environ.get('LOCAL_DATABASE_URL') or '').strip().strip("'\"")
    prod_url = (os.environ.get('DATABASE_URL') or '').strip().strip("'\"")

    if not local_url:
        sys.exit('ABORT: LOCAL_DATABASE_URL is not set. This script only runs '
                 'against the local database.')

    local_url = local_url.replace('postgres://', 'postgresql://')
    normalized_prod = prod_url.replace('postgres://', 'postgresql://')

    if normalized_prod and local_url == normalized_prod:
        sys.exit('ABORT: LOCAL_DATABASE_URL equals DATABASE_URL. Refusing to '
                 'run against production.')

    host = (urlsplit(local_url).hostname or '').lower()
    if host not in {'localhost', '127.0.0.1', '::1'}:
        sys.exit(f'ABORT: LOCAL_DATABASE_URL host is {host!r}, not a local '
                 'address. Refusing to run — this script targets local only.')

    return local_url


def build_tables(schema):
    dc = sa.table(
        'deck_component',
        sa.column('id', sa.Integer),
        sa.column('deck_id', sa.Integer),
        sa.column('card_id', sa.String),
        sa.column('name', sa.String),
        sa.column('physical_status', sa.String),
        sa.column('physical_finish', sa.String),
        schema=schema,
    )
    decks = sa.table(
        'decks',
        sa.column('id', sa.Integer),
        sa.column('name', sa.String),
        sa.column('player_id', sa.Integer),
        sa.column('decksite', sa.String),
        sa.column('archidekt_id', sa.String),
        schema=schema,
    )
    cards = sa.table(
        'cards',
        sa.column('id', sa.String),
        sa.column('name', sa.String),
        schema=schema,
    )
    return dc, decks, cards


def resolve_card_id(conn, cards, uid, name, name_cache):
    """Resolve a source uid/name to a card_id present in our cards table.

    Prefers the exact printing uid; falls back to any printing of the same
    name (cached). Returns None when neither matches. Mirrors
    deckbuilder.resolve_card_id but against this script's own connection.
    """
    if uid:
        hit = conn.execute(
            sa.select(cards.c.id).where(cards.c.id == uid).limit(1)
        ).scalar()
        if hit is not None:
            return hit
    if name:
        if name in name_cache:
            return name_cache[name]
        hit = conn.execute(
            sa.select(cards.c.id).where(cards.c.name == name).limit(1)
        ).scalar()
        name_cache[name] = hit
        return hit
    return None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--player-id', type=int, default=1,
                        help='Player whose decks to migrate (default: 1).')
    parser.add_argument('--schema', default=os.environ.get('DB_SCHEMA', 'magic_stats_owner'),
                        help='Database schema (default: $DB_SCHEMA or magic_stats_owner).')
    parser.add_argument('--set-finish', action='store_true',
                        help="Also set physical_finish from Archidekt's modifier "
                             'for cards that become in_deck.')
    parser.add_argument('--apply', action='store_true',
                        help='Commit the changes. Without this flag the script '
                             'is a dry run and writes nothing.')
    args = parser.parse_args()

    # Import here so a missing dependency surfaces only when actually running.
    import pyrchidekt.api

    local_url = resolve_local_url()
    schema = args.schema
    engine = sa.create_engine(local_url, future=True)
    dc, decks, cards = build_tables(schema)

    # The decks we can act on: this player's Archidekt-sourced decks.
    with engine.connect() as conn:
        deck_rows = conn.execute(
            sa.select(decks.c.id, decks.c.name, decks.c.archidekt_id)
            .where(decks.c.player_id == args.player_id)
            .where(decks.c.decksite.ilike('%archidekt%'))
            .where(decks.c.archidekt_id.isnot(None))
            .order_by(decks.c.id)
        ).all()

    if not deck_rows:
        print(f'No Archidekt decks for player_id={args.player_id}. Nothing to do.')
        return

    print('=' * 70)
    print(f'Archidekt label -> collection-status migration  (player_id={args.player_id})')
    db_bits = urlsplit(local_url)
    print(f'Database : {db_bits.hostname}:{db_bits.port}{db_bits.path}  schema={schema}')
    print(f'Mode     : {"APPLY (will commit)" if args.apply else "DRY RUN (no writes)"}'
          f'{"  +set-finish" if args.set_finish else ""}')
    print(f'Decks    : {len(deck_rows)} Archidekt deck(s) to scan')
    print('=' * 70)

    # Planned updates: component_id -> (new_status, new_finish_or_None)
    planned = {}
    target_counts = Counter()
    change_counts = Counter()
    label_counts = Counter()
    fetch_failed = []
    unmatched_cards = 0  # fetched cards with no stored component to attach to

    name_cache = {}

    with engine.connect() as conn:
        for row in deck_rows:
            try:
                deck = pyrchidekt.api.getDeckById(str(row.archidekt_id).strip())
            except Exception as e:
                fetch_failed.append((row.id, row.archidekt_id, row.name, str(e)[:70]))
                time.sleep(FETCH_DELAY_SECONDS)
                continue

            # Stored components for this deck, grouped by card_id and ordered by
            # id so pairing with fetched cards is deterministic.
            comp_rows = conn.execute(
                sa.select(dc.c.id, dc.c.card_id, dc.c.physical_status)
                .where(dc.c.deck_id == row.id)
                .order_by(dc.c.id)
            ).all()
            comps_by_card = defaultdict(deque)
            for c in comp_rows:
                comps_by_card[c.card_id].append(c)

            # Pair each fetched card (which carries the label) with a stored
            # component sharing its resolved card_id.
            for card in deck.cards:
                label = getattr(card, 'label', None)
                label_counts[(label or '').strip() or '<empty>'] += 1
                status = map_status(label)

                uid = getattr(getattr(card, 'card', None), 'uid', None)
                name = getattr(getattr(getattr(card, 'card', None), 'oracle_card', None), 'name', None)
                card_id = resolve_card_id(conn, cards, uid, name, name_cache)

                bucket = comps_by_card.get(card_id)
                if not bucket:
                    unmatched_cards += 1
                    continue
                comp = bucket.popleft()

                finish = None
                if args.set_finish and status == 'in_deck':
                    finish = normalize_finish(getattr(card, 'modifier', None))

                target_counts[status] += 1
                if status != comp.physical_status:
                    change_counts[f'{comp.physical_status} -> {status}'] += 1
                planned[comp.id] = (status, finish)

            time.sleep(FETCH_DELAY_SECONDS)

    # --- Report ---------------------------------------------------------
    fetched_ok = len(deck_rows) - len(fetch_failed)
    print(f'Decks fetched OK          : {fetched_ok}')
    print(f'Decks not fetchable       : {len(fetch_failed)} (deleted/private on Archidekt)')
    print(f'Fetched labels            : ', dict(label_counts.most_common()))
    print(f'Components matched         : {len(planned)}')
    print(f'Fetched cards unmatched    : {unmatched_cards} (no stored component for that card)')
    print('Target status (matched)   :')
    for status in ('in_deck', 'proxy', 'unset'):
        print(f'    {status:<9}: {target_counts.get(status, 0)}')
    changes = {cid: v for cid, v in planned.items()}
    n_changes = sum(change_counts.values())
    print(f'Status changes             : {n_changes}')
    if change_counts:
        for transition, n in sorted(change_counts.items()):
            print(f'    {transition:<20}: {n}')
    if fetch_failed:
        print('\nUnfetchable decks (skipped):')
        for deck_id, aid, name, err in fetch_failed:
            print(f'    deck_id={deck_id} archidekt_id={aid} {name!r}: {err}')

    if not planned:
        print('\nNothing to apply.')
        return

    if not args.apply:
        print('\nDRY RUN: no changes written. Re-run with --apply to commit.')
        return

    # --- Apply ----------------------------------------------------------
    updated = 0
    with engine.begin() as conn:
        for comp_id, (status, finish) in planned.items():
            values = {'physical_status': status}
            if finish is not None:
                values['physical_finish'] = finish
            result = conn.execute(
                sa.update(dc).where(dc.c.id == comp_id).values(**values)
            )
            updated += result.rowcount or 0

    print(f'\nAPPLIED: updated {updated} component(s).')


if __name__ == '__main__':
    main()
