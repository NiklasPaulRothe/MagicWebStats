"""
One-time backfill: give face images to the single-image two-name layouts
(adventure / split / prepare / flip, and any multi-face card whose faces were
stored without an image).

Why this exists
---------------
Scryfall stores `image_uris` PER FACE for transform / modal_dfc / reversible
cards, but for the single-image layouts (split, flip, adventure, aftermath,
'prepare', ...) it provides ONE top-level `image_uris` and NO per-face image —
the whole physical card is a single picture. The importer only read per-face
images for multi-face cards, so those faces were stored with image_uri = NULL
and the card shows no art in the grid / popup.

fetch_card_data.py is now fixed to fall back to the card-level image for such
faces, so future fetches are correct. This script repairs the EXISTING rows
without a full re-fetch, by setting each imageless face to the deterministic
Scryfall front-image URL derived from the card id:

    https://cards.scryfall.io/large/front/<id[0]>/<id[1]>/<id>.jpg

(The front image is the whole card for these layouts; the ?timestamp query is
only a cache-buster and is not required for the image to load.)

Scope: only faces whose card has NO face-0 image yet (so we never overwrite a
real per-face image). All faces of such a card get the same front image.

DATABASE SAFETY
---------------
Writes. Targets LOCAL_DATABASE_URL only; refuses unless the URL is set and its
host is localhost. Dry run by default; pass --apply to commit.
"""

import argparse
import os
import sys
from urllib.parse import urlsplit

import sqlalchemy as sa
from dotenv import load_dotenv

SCRYFALL_IMG = "https://cards.scryfall.io/large/front/{a}/{b}/{cid}.jpg"


def front_image_url(card_id: str) -> str | None:
    """Deterministic Scryfall 'large' front image URL for a Scryfall card id."""
    if not card_id or len(card_id) < 2:
        return None
    return SCRYFALL_IMG.format(a=card_id[0], b=card_id[1], cid=card_id)


def resolve_url(explicit: str | None, allow_nonlocal: bool) -> str:
    """Resolve the target DB URL.

    Default target is LOCAL_DATABASE_URL and the host MUST be localhost. To run
    against a remote/production database you must pass BOTH --database-url and
    --i-know-this-is-production, which lifts the localhost guard. This is a
    read-mostly backfill (sets image_uri on faces that are currently NULL), but
    it is still a write, so running it against production is a deliberate,
    explicit action.
    """
    load_dotenv()
    if explicit:
        url = explicit.strip().strip("'\"").replace('postgres://', 'postgresql://')
    else:
        url = (os.environ.get('LOCAL_DATABASE_URL') or '').strip().strip("'\"").replace('postgres://', 'postgresql://')
        if not url:
            sys.exit('ABORT: LOCAL_DATABASE_URL is not set (and no --database-url given).')

    host = (urlsplit(url).hostname or '').lower()
    is_local = host in {'localhost', '127.0.0.1', '::1'}
    if not is_local and not allow_nonlocal:
        sys.exit(f'ABORT: target host {host!r} is not local. To run against a '
                 'remote/production database, pass --database-url <url> AND '
                 '--i-know-this-is-production.')
    return url


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--schema', default=os.environ.get('DB_SCHEMA', 'magic_stats_owner'))
    parser.add_argument('--database-url', default=None,
                        help='Target DB URL. Defaults to LOCAL_DATABASE_URL. Required '
                             '(with --i-know-this-is-production) to target a remote DB.')
    parser.add_argument('--i-know-this-is-production', action='store_true',
                        help='Lift the localhost-only guard so --database-url may '
                             'point at a remote/production database.')
    parser.add_argument('--apply', action='store_true',
                        help='Commit changes (otherwise dry run).')
    args = parser.parse_args()

    local = resolve_url(args.database_url, args.i_know_this_is_production)
    schema = args.schema
    engine = sa.create_engine(local, future=True)

    # Cards that have faces but no face-0 image — the ones missing art.
    select_cards = sa.text(f'''
        SELECT DISTINCT c.id, c.layout
        FROM {schema}.cards c
        WHERE EXISTS (SELECT 1 FROM {schema}.card_faces f
                      WHERE f.card_id = c.id AND f.face_index = 1)
          AND NOT EXISTS (SELECT 1 FROM {schema}.card_faces f
                          WHERE f.card_id = c.id AND f.face_index = 0
                            AND f.image_uri IS NOT NULL)
    ''')

    with engine.connect() as conn:
        cards = conn.execute(select_cards).all()

    print('=' * 60)
    print(f'DFC/multi-face face-image backfill  (LOCAL: {urlsplit(local).hostname}'
          f'{urlsplit(local).path})')
    print(f'Mode: {"APPLY" if args.apply else "DRY RUN"}')
    print('=' * 60)
    print(f'Cards needing a face image: {len(cards)}')

    by_layout: dict[str, int] = {}
    for _cid, layout in cards:
        by_layout[layout] = by_layout.get(layout, 0) + 1
    for layout, n in sorted(by_layout.items(), key=lambda kv: -kv[1]):
        print(f'    {layout:<18}: {n}')

    if not cards:
        print('Nothing to do.')
        return

    if not args.apply:
        sample = cards[0]
        print(f'\nExample: card {sample[0]} -> {front_image_url(sample[0])}')
        print('\nDRY RUN: no changes written. Re-run with --apply to commit.')
        return

    updated_faces = 0
    with engine.begin() as conn:
        for cid, _layout in cards:
            url = front_image_url(cid)
            if not url:
                continue
            # Set the front image on every face of this card that lacks one.
            result = conn.execute(sa.text(f'''
                UPDATE {schema}.card_faces
                SET image_uri = :url
                WHERE card_id = :cid AND image_uri IS NULL
            '''), {'url': url, 'cid': cid})
            updated_faces += result.rowcount or 0

    print(f'\nAPPLIED: set image on {updated_faces} face row(s) '
          f'across {len(cards)} card(s).')


if __name__ == '__main__':
    main()
