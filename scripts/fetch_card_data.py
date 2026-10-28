import gzip
import json
import os
import statistics
import sys
import time
from typing import Iterator

import psycopg2
import requests
from dotenv import load_dotenv
import pyrchidekt
from pyrchidekt.api import getDeckById

def get_bulk_data_uri(bulk_type: str) -> str:
    """Fetch the jsonl_download_uri for the given bulk data type from Scryfall API."""
    headers = {'User-Agent': 'MagicWebStats/1.0', 'Accept': 'application/json'}
    response = requests.get("https://api.scryfall.com/bulk-data", headers=headers)
    response.raise_for_status()
    bulk_data = response.json()
    for entry in bulk_data.get('data', []):
        if entry['type'] == bulk_type:
            return entry['jsonl_download_uri']
    raise ValueError(f"Bulk data type '{bulk_type}' not found")


def stream_jsonl_gz(url: str) -> Iterator[dict]:
    """Stream a gzipped JSONL file, yielding one parsed dict per line."""
    import io

    headers = {'User-Agent': 'MagicWebStats/1.0'}
    response = requests.get(url, stream=True, headers=headers)
    response.raise_for_status()

    # The file itself is gzip-compressed (not Content-Encoding),
    # so we decompress manually. Disable urllib3's decode to get raw bytes.
    response.raw.decode_content = False
    decompressed = gzip.GzipFile(fileobj=response.raw)
    reader = io.TextIOWrapper(io.BufferedReader(decompressed, buffer_size=65536), encoding='utf-8')

    line_num = 0
    for line in reader:
        line_num += 1
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            print(f"Warning: malformed JSON at line {line_num}, skipping")
            continue


def card_type_line(card: dict) -> str:
    """Return a non-null type_line for a card.

    Most cards carry a top-level `type_line`, but reversible_card (and some
    other multi-face layouts) have `type_line: null` at the top level, with the
    real types living on each face. The `cards.type_line` column is NOT NULL, so
    for those cards we synthesize a top-level value by joining the face type
    lines with " // " (e.g. "Land // Land"), falling back to the first non-empty
    face type, then to an empty string as a last resort.
    """
    tl = card.get('type_line')
    if tl:
        return tl
    faces = card.get('card_faces') or []
    face_types = [f.get('type_line') for f in faces if f.get('type_line')]
    if face_types:
        return ' // '.join(face_types)
    return ''


def card_oracle_id(card: dict) -> str | None:
    """Return a card's oracle_id, falling back to a face for reversible cards.

    Most cards carry a top-level `oracle_id`. Reversible cards
    (layout == 'reversible_card', e.g. Secret Lair double-sided reprints and
    some special-frame lands) have NO top-level `oracle_id` — it lives on each
    `card_faces` entry instead (both faces share the same oracle_id). We take
    the first face's oracle_id so these printings are ingested instead of
    skipped. Returns None only when no oracle_id can be found anywhere.
    """
    oid = card.get('oracle_id')
    if oid:
        return oid
    for face in card.get('card_faces') or []:
        face_oid = face.get('oracle_id')
        if face_oid:
            return face_oid
    return None


def card_price_eur(card: dict, foil: bool) -> str | None:
    """Return the Scryfall EUR (Cardmarket) price string for a card, or None.

    Scryfall exposes daily prices under `prices` as strings (e.g. "0.35"); we
    pass the string straight through to psycopg2, which casts it to NUMERIC.
    `foil=True` reads prices.eur_foil, otherwise prices.eur. Missing prices come
    back as None so the column is left NULL.
    """
    prices = card.get('prices') or {}
    value = prices.get('eur_foil' if foil else 'eur')
    return value or None


def should_skip_card(card: dict) -> bool:
    """Return True if the card should be excluded (art_series, non-paper,
    non-English, token-like).

    We stream Scryfall's `all_cards` bulk (every printing in every language) so
    that EVERY paper printing of a card is stored — one `cards` row per Scryfall
    printing id, sharing an `oracle_id`. Two filters narrow that firehose:

      * paper only — a physical collection never references MTGO/Arena-only
        objects, and those have no set/collector number a player could own.
      * English only (`lang == 'en'`) — `all_cards` repeats each printing once
        per language; without this guard every printing would be duplicated
        across ~10+ languages. We key the printings table on the English
        printing of each set/collector number. (Collection CSVs carry their own
        Language column on the owned copy; that's recorded on the collection
        entry, not by storing a separate card row per language.)
    """
    # Skip art series
    if card.get('layout') == 'art_series':
        return True
    # Skip non-paper cards
    if 'paper' not in card.get('games', []):
        return True
    # Skip non-English printings (all_cards includes every language).
    if card.get('lang') != 'en':
        return True
    # Skip token-like entries with "Card" in type_line. Use the derived type
    # line so reversible/multi-face cards (top-level type_line == None) are
    # handled without raising on a None value.
    type_line = card_type_line(card)
    if 'Card' in type_line:
        return True
    return False


def upsert_card(cur, card: dict) -> None:
    """INSERT ... ON CONFLICT UPDATE for the cards table."""
    cur.execute("""
        INSERT INTO magic_stats_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at, price_eur, price_eur_foil)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE SET
            oracle_id = EXCLUDED.oracle_id,
            name = EXCLUDED.name,
            mana_cost = EXCLUDED.mana_cost,
            cmc = EXCLUDED.cmc,
            type_line = EXCLUDED.type_line,
            oracle_text = EXCLUDED.oracle_text,
            layout = EXCLUDED.layout,
            set_code = EXCLUDED.set_code,
            set_name = EXCLUDED.set_name,
            rarity = EXCLUDED.rarity,
            released_at = EXCLUDED.released_at,
            price_eur = EXCLUDED.price_eur,
            price_eur_foil = EXCLUDED.price_eur_foil
    """, (
        card['id'],
        card_oracle_id(card),
        card['name'],
        card.get('mana_cost'),
        card.get('cmc', 0),
        card_type_line(card),
        card.get('oracle_text'),
        card['layout'],
        card['set'],
        card['set_name'],
        card['rarity'],
        card.get('released_at'),
        card_price_eur(card, foil=False),
        card_price_eur(card, foil=True)
    ))


def _face_image(face: dict, card: dict) -> str | None:
    """Pick the 'large' image for a face, falling back to the card's top-level.

    Transform / modal_dfc / reversible_card put `image_uris` on each face. But
    the single-image two-name layouts (split, flip, adventure, aftermath,
    'prepare', etc.) carry ONE top-level `image_uris` and NO per-face image —
    the whole physical card is a single image. For those, fall back to the
    card-level image so both faces still get a picture instead of NULL.
    """
    face_imgs = face.get('image_uris')
    if face_imgs and face_imgs.get('large'):
        return face_imgs['large']
    card_imgs = card.get('image_uris')
    if card_imgs and card_imgs.get('large'):
        return card_imgs['large']
    return None


def insert_card_faces(cur, card_id: str, card: dict) -> None:
    """Insert face rows — handles single-face and multi-face cards."""
    if 'card_faces' in card:
        # Multi-face card: insert one row per face
        for idx, face in enumerate(card['card_faces']):
            image_uri = _face_image(face, card)
            cur.execute("""
                INSERT INTO magic_stats_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                card_id,
                idx,
                face['name'],
                face.get('mana_cost'),
                face.get('type_line'),
                face.get('oracle_text'),
                image_uri
            ))
    else:
        # Single-face card: insert one row with face_index = 0, using top-level data
        image_uri = card.get('image_uris', {}).get('large') if 'image_uris' in card else None
        cur.execute("""
            INSERT INTO magic_stats_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            card_id,
            0,
            card['name'],
            card.get('mana_cost'),
            card.get('type_line'),
            card.get('oracle_text'),
            image_uri
        ))


def insert_card_metadata(cur, card_id: str, card: dict) -> None:
    """Insert colors, color_identity, keywords, legalities for a card."""
    # Insert colors (one row per color, empty array = zero rows)
    for color in card.get('colors', []):
        cur.execute("""
            INSERT INTO magic_stats_owner.card_colors (card_id, color)
            VALUES (%s, %s)
        """, (card_id, color))

    # Insert color identity (one row per color)
    for color in card.get('color_identity', []):
        cur.execute("""
            INSERT INTO magic_stats_owner.card_color_identity (card_id, color)
            VALUES (%s, %s)
        """, (card_id, color))

    # Insert keywords (one row per keyword)
    for keyword in card.get('keywords', []):
        cur.execute("""
            INSERT INTO magic_stats_owner.card_keywords (card_id, keyword)
            VALUES (%s, %s)
        """, (card_id, keyword))

    # Insert legalities (one row per format)
    legalities = card.get('legalities', {})
    for format_name, status in legalities.items():
        cur.execute("""
            INSERT INTO magic_stats_owner.card_legalities (card_id, format, status)
            VALUES (%s, %s, %s)
        """, (card_id, format_name, status))


def process_oracle_tags(cur, tags_url: str) -> None:
    """Download oracle tags JSONL, truncate oracle_tags table, batch insert."""
    cur.execute("TRUNCATE magic_stats_owner.oracle_tags")

    batch = []
    for tag_obj in stream_jsonl_gz(tags_url):
        if tag_obj.get('type') != 'oracle':
            continue
        label = tag_obj['label']
        for tagging in tag_obj.get('taggings', []):
            oracle_id = tagging.get('oracle_id')
            if oracle_id:
                batch.append((oracle_id, label))
                if len(batch) >= 1000:
                    _execute_oracle_tags_batch(cur, batch)
                    batch = []
    if batch:
        _execute_oracle_tags_batch(cur, batch)


def _execute_oracle_tags_batch(cur, batch: list) -> None:
    """Helper to batch insert oracle tag rows."""
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        "INSERT INTO magic_stats_owner.oracle_tags (oracle_id, tag) VALUES %s",
        batch
    )


def process_rulings(cur, rulings_url: str) -> int:
    """Download the Scryfall rulings JSONL, replace card_rulings, batch insert.

    Each entry in the rulings bulk file looks like:
        {"object": "ruling", "oracle_id": "...", "source": "wotc",
         "published_at": "2004-10-04", "comment": "..."}
    Rulings key on oracle_id (shared across printings). We truncate and reload
    so stale rulings are dropped, matching how oracle_tags is handled. Returns
    the number of ruling rows inserted.
    """
    cur.execute("TRUNCATE magic_stats_owner.card_rulings")

    inserted = 0
    batch = []
    for ruling in stream_jsonl_gz(rulings_url):
        oracle_id = ruling.get('oracle_id')
        comment = ruling.get('comment')
        # comment is NOT NULL in the schema; skip malformed/empty entries.
        if not oracle_id or not comment:
            continue
        batch.append((
            oracle_id,
            ruling.get('source'),
            ruling.get('published_at'),
            comment,
        ))
        if len(batch) >= 1000:
            _execute_rulings_batch(cur, batch)
            inserted += len(batch)
            batch = []
    if batch:
        _execute_rulings_batch(cur, batch)
        inserted += len(batch)
    return inserted


def _execute_rulings_batch(cur, batch: list) -> None:
    """Helper to batch insert ruling rows."""
    from psycopg2.extras import execute_values
    execute_values(
        cur,
        "INSERT INTO magic_stats_owner.card_rulings "
        "(oracle_id, source, published_at, comment) VALUES %s",
        batch
    )


def expected_score(rating, opponent_rating):
    """Pairwise expected score (standard Elo formula)."""
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 400))


def expected_multiplayer_score(deck_id, deck_ratings):
    """Average pairwise expected score against all opponents."""
    opponents = {did: r for did, r in deck_ratings.items() if did != deck_id}
    my_rating = deck_ratings[deck_id]
    pairwise_sum = sum(expected_score(my_rating, opp_r) for opp_r in opponents.values())
    return pairwise_sum / len(opponents)


def get_game_k_factor(participants_games_played):
    """Single K-factor for the game based on median experience."""
    median_games = statistics.median(participants_games_played)
    if median_games <= 10:
        return 60
    elif median_games <= 30:
        return 40
    else:
        return 24


def calculate_elo_ratings(conn):
    """Recalculate Elo ratings for all decks from scratch."""
    cur = conn.cursor()

    # Load all decks (id, player_id)
    cur.execute('SELECT id, player_id FROM magic_stats_owner.decks')
    decks = cur.fetchall()
    elo_ratings = {row[0]: {'elo_rating': 1500, 'games_played': 0} for row in decks}
    deck_player_map = {row[0]: row[1] for row in decks}

    # Load all games ordered by date/id for chronological processing
    cur.execute('SELECT id, winner_id FROM magic_stats_owner.games ORDER BY date, id')
    games = cur.fetchall()

    # Load all participants grouped by game
    cur.execute('SELECT game_id, player_id, deck_id FROM magic_stats_owner.participants')
    all_participants = cur.fetchall()
    participants_by_game = {}
    for game_id, player_id, deck_id in all_participants:
        participants_by_game.setdefault(game_id, []).append((player_id, deck_id))

    for game_id, winner_player_id in games:
        participants = participants_by_game.get(game_id, [])
        if len(participants) < 3 or len(participants) > 5:
            continue

        # Build ratings for valid participants (deck belongs to player, or player 24)
        deck_ratings = {}
        valid_participants = []
        for player_id, deck_id in participants:
            deck_owner = deck_player_map.get(deck_id)
            if deck_owner != player_id and deck_owner != 24:
                continue
            if deck_id in elo_ratings:
                deck_ratings[deck_id] = elo_ratings[deck_id]['elo_rating']
                valid_participants.append((player_id, deck_id))

        if len(deck_ratings) < 2:
            continue

        # Normalize expected scores
        raw_expected = {
            did: expected_multiplayer_score(did, deck_ratings)
            for did in deck_ratings
        }
        total_expected = sum(raw_expected.values())
        normalized_expected = {
            did: raw / total_expected
            for did, raw in raw_expected.items()
        }

        # Single K-factor for zero-sum guarantee
        games_played_list = [elo_ratings[did]['games_played'] for _, did in valid_participants]
        k = get_game_k_factor(games_played_list)

        # Apply updates
        for player_id, deck_id in valid_participants:
            actual_score = 1.0 if winner_player_id == player_id else 0.0
            rating = elo_ratings[deck_id]['elo_rating']
            new_rating = rating + k * (actual_score - normalized_expected[deck_id])
            elo_ratings[deck_id]['elo_rating'] = new_rating
            elo_ratings[deck_id]['games_played'] += 1

    # Write results back to the database
    for deck_id, values in elo_ratings.items():
        if values['games_played'] >= 5:
            elo = values['elo_rating']
        else:
            elo = 0
        cur.execute(
            'UPDATE magic_stats_owner.decks SET elo_rating = %s WHERE id = %s',
            (elo, deck_id)
        )

    conn.commit()
    cur.close()
    updated = sum(1 for v in elo_ratings.values() if v['games_played'] >= 5)
    print(f"  Updated {updated} decks with Elo ratings ({len(games)} games processed)")


def reload_all_decks():
    """Re-import every deck's cards from its source site (Archidekt/Moxfield).

    Reuses the application's import functions so the nightly run applies the
    same logic as a manual import: all cards are stored with an in_deck flag
    (derived from the card's primary category / board), and card ids that
    aren't present as that exact printing fall back to another printing by
    name. Must run AFTER the Scryfall card-data phase so the name fallback can
    resolve against fresh card rows.

    Runs inside a Flask app context because the import functions use the ORM.
    """
    # Imported lazily so the card-data phases don't depend on the app package.
    from app import create_app
    from app.models import Deck
    from app.third_party_data.deckbuilder import (
        load_cards_from_archidekt,
        load_cards_from_moxfield,
    )

    app = create_app()
    with app.app_context():
        decks = Deck.query.all()
        reloaded = 0
        for deck in decks:
            if not deck.decksite or not deck.archidekt_id:
                continue
            try:
                if 'archidekt' in deck.decksite:
                    load_cards_from_archidekt(deck.archidekt_id.strip(), deck.id)
                    reloaded += 1
                    time.sleep(1)
                elif 'moxfield' in deck.decksite:
                    load_cards_from_moxfield(deck.archidekt_id.strip(), deck.id)
                    reloaded += 1
                    time.sleep(1)
            except Exception as e:
                print(f"  Error reloading deck {deck.id} ({deck.name}): {e}")
                continue
        print(f"  Reloaded {reloaded} decks")


if __name__ == '__main__':
    print('Fetching Card Data...')
    load_dotenv()

    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://'))

    # =========================================================================
    # Phase 1: Archidekt deck tags
    # =========================================================================
    print('Fetching deck tags from Archidekt...')
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, name, archidekt_id 
            FROM magic_stats_owner.decks 
            WHERE archidekt_id IS NOT NULL AND archidekt_id != ''
        """)
        decks_with_archidekt = cur.fetchall()

        print(f'Found {len(decks_with_archidekt)} decks with Archidekt links')

        for deck_id, deck_name, archidekt_id in decks_with_archidekt:
            try:
                print(f'Fetching tags for deck: {deck_name} (ID: {deck_id})')
                deck = pyrchidekt.api.getDeckById(archidekt_id.strip())
                deck_tags = getattr(deck, 'deck_tags', [])

                cur.execute("DELETE FROM magic_stats_owner.deck_tags WHERE deck_id = %s", (deck_id,))

                if deck_tags:
                    for tag in deck_tags:
                        tag_name = tag['name'].strip()
                        if tag_name:
                            cur.execute("""
                                INSERT INTO magic_stats_owner.deck_tags (deck_id, tag)
                                VALUES (%s, %s)
                                ON CONFLICT (deck_id, tag) DO NOTHING
                            """, (deck_id, tag_name))
                    print(f'  Saved {len(deck_tags)} tags')
                else:
                    print(f'  No tags found')

                conn.commit()
                time.sleep(1)

            except Exception as e:
                print(f'  Error fetching tags for deck {deck_name}: {str(e)}')
                conn.rollback()
                continue

        print('Deck tags fetching completed!')
        cur.close()

    except Exception as e:
        print(f'Archidekt tags phase failed: {str(e)}')
        # Continue to Phase 2 regardless

    # =========================================================================
    # Phase 2: Scryfall card data (new JSONL streaming + batched inserts)
    # =========================================================================
    print('Starting Scryfall card data fetch...')
    try:
        from psycopg2.extras import execute_values

        # `all_cards` contains every printing in every language (unlike
        # `default_cards`, which is a single representative printing per card).
        # should_skip_card() narrows this to English paper printings so we store
        # every paper set/collector-number printing without duplicating each
        # across languages.
        cards_url = get_bulk_data_uri("all_cards")
        print(f'Streaming card data from: {cards_url}')

        cur = conn.cursor()
        total_count = 0
        start_time = time.time()

        # Batch accumulators
        cards_batch = []
        faces_batch = []
        colors_batch = []
        color_identity_batch = []
        keywords_batch = []
        legalities_batch = []
        card_ids_in_batch = []

        BATCH_SIZE = 1000

        for card in stream_jsonl_gz(cards_url):
            if should_skip_card(card):
                continue

            # Skip cards for which we can't build the NOT-NULL columns. Both
            # fields fall back to card_faces, so reversible_card printings
            # (no top-level oracle_id/type_line) are still ingested.
            oracle_id = card_oracle_id(card)
            if not oracle_id or not card_type_line(card):
                continue

            card_id = card['id']
            card_ids_in_batch.append(card_id)

            # Accumulate card row
            cards_batch.append((
                card_id,
                oracle_id,
                card['name'],
                card.get('mana_cost'),
                card.get('cmc', 0),
                card_type_line(card),
                card.get('oracle_text'),
                card['layout'],
                card['set'],
                card['set_name'],
                card['rarity'],
                card.get('released_at'),
                card_price_eur(card, foil=False),
                card_price_eur(card, foil=True)
            ))

            # Accumulate faces
            if 'card_faces' in card:
                for idx, face in enumerate(card['card_faces']):
                    image_uri = _face_image(face, card)
                    faces_batch.append((card_id, idx, face['name'], face.get('mana_cost'), face.get('type_line'), face.get('oracle_text'), image_uri))
            else:
                image_uri = card.get('image_uris', {}).get('large') if 'image_uris' in card else None
                faces_batch.append((card_id, 0, card['name'], card.get('mana_cost'), card.get('type_line'), card.get('oracle_text'), image_uri))

            # Accumulate colors
            for color in card.get('colors', []):
                colors_batch.append((card_id, color))

            # Accumulate color identity
            for color in card.get('color_identity', []):
                color_identity_batch.append((card_id, color))

            # Accumulate keywords
            for keyword in card.get('keywords', []):
                keywords_batch.append((card_id, keyword))

            # Accumulate legalities
            for format_name, status in card.get('legalities', {}).items():
                legalities_batch.append((card_id, format_name, status))

            total_count += 1

            # Flush batch when full
            if len(cards_batch) >= BATCH_SIZE:
                id_tuple = tuple(card_ids_in_batch)
                cur.execute("DELETE FROM magic_stats_owner.card_faces WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM magic_stats_owner.card_colors WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM magic_stats_owner.card_color_identity WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM magic_stats_owner.card_keywords WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM magic_stats_owner.card_legalities WHERE card_id IN %s", (id_tuple,))

                execute_values(cur, """
                    INSERT INTO magic_stats_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at, price_eur, price_eur_foil)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        oracle_id = EXCLUDED.oracle_id, name = EXCLUDED.name, mana_cost = EXCLUDED.mana_cost,
                        cmc = EXCLUDED.cmc, type_line = EXCLUDED.type_line, oracle_text = EXCLUDED.oracle_text,
                        layout = EXCLUDED.layout, set_code = EXCLUDED.set_code, set_name = EXCLUDED.set_name,
                        rarity = EXCLUDED.rarity, released_at = EXCLUDED.released_at,
                        price_eur = EXCLUDED.price_eur, price_eur_foil = EXCLUDED.price_eur_foil
                """, cards_batch)

                if faces_batch:
                    execute_values(cur, "INSERT INTO magic_stats_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri) VALUES %s", faces_batch)
                if colors_batch:
                    execute_values(cur, "INSERT INTO magic_stats_owner.card_colors (card_id, color) VALUES %s", colors_batch)
                if color_identity_batch:
                    execute_values(cur, "INSERT INTO magic_stats_owner.card_color_identity (card_id, color) VALUES %s", color_identity_batch)
                if keywords_batch:
                    execute_values(cur, "INSERT INTO magic_stats_owner.card_keywords (card_id, keyword) VALUES %s", keywords_batch)
                if legalities_batch:
                    execute_values(cur, "INSERT INTO magic_stats_owner.card_legalities (card_id, format, status) VALUES %s", legalities_batch)

                conn.commit()
                cards_batch, faces_batch, colors_batch = [], [], []
                color_identity_batch, keywords_batch, legalities_batch = [], [], []
                card_ids_in_batch = []

            if total_count % 10000 == 0:
                elapsed = time.time() - start_time
                print(f"Processed {total_count} cards in {elapsed:.1f}s")

        # Final flush for remaining cards
        if cards_batch:
            id_tuple = tuple(card_ids_in_batch)
            cur.execute("DELETE FROM magic_stats_owner.card_faces WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM magic_stats_owner.card_colors WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM magic_stats_owner.card_color_identity WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM magic_stats_owner.card_keywords WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM magic_stats_owner.card_legalities WHERE card_id IN %s", (id_tuple,))

            execute_values(cur, """
                INSERT INTO magic_stats_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    oracle_id = EXCLUDED.oracle_id, name = EXCLUDED.name, mana_cost = EXCLUDED.mana_cost,
                    cmc = EXCLUDED.cmc, type_line = EXCLUDED.type_line, oracle_text = EXCLUDED.oracle_text,
                    layout = EXCLUDED.layout, set_code = EXCLUDED.set_code, set_name = EXCLUDED.set_name,
                    rarity = EXCLUDED.rarity, released_at = EXCLUDED.released_at
            """, cards_batch)

            if faces_batch:
                execute_values(cur, "INSERT INTO magic_stats_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri) VALUES %s", faces_batch)
            if colors_batch:
                execute_values(cur, "INSERT INTO magic_stats_owner.card_colors (card_id, color) VALUES %s", colors_batch)
            if color_identity_batch:
                execute_values(cur, "INSERT INTO magic_stats_owner.card_color_identity (card_id, color) VALUES %s", color_identity_batch)
            if keywords_batch:
                execute_values(cur, "INSERT INTO magic_stats_owner.card_keywords (card_id, keyword) VALUES %s", keywords_batch)
            if legalities_batch:
                execute_values(cur, "INSERT INTO magic_stats_owner.card_legalities (card_id, format, status) VALUES %s", legalities_batch)

            conn.commit()

        elapsed = time.time() - start_time
        print(f"Card data import complete: {total_count} cards in {elapsed:.1f}s")
        cur.close()

    except requests.HTTPError as e:
        print(f"Card data download failed: {e.response.status_code} - {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Card data processing failed: {e}")
        sys.exit(1)

    # =========================================================================
    # Phase 3: Oracle tags
    # =========================================================================
    print('Fetching oracle tags...')
    try:
        tags_url = get_bulk_data_uri("oracle_tags")
        cur = conn.cursor()
        process_oracle_tags(cur, tags_url)
        conn.commit()
        cur.close()
        print('Oracle tags import complete.')
    except Exception as e:
        print(f"Oracle tags failed (non-fatal): {e}")
        # Card data already committed, so we continue (Req 6.6)

    # =========================================================================
    # Phase 4: Card rulings (Gatherer/Scryfall)
    # =========================================================================
    print('Fetching card rulings...')
    try:
        rulings_url = get_bulk_data_uri("rulings")
        cur = conn.cursor()
        count = process_rulings(cur, rulings_url)
        conn.commit()
        cur.close()
        print(f'Card rulings import complete: {count} rulings.')
    except Exception as e:
        print(f"Card rulings failed (non-fatal): {e}")
        # Card data already committed, so we continue.

    # =========================================================================
    # Phase 5: Re-import decks from their source sites
    # =========================================================================
    # Runs after card data so the name-based printing fallback resolves against
    # fresh card rows. Refreshes each deck's cards + the in_deck flags.
    print('Reloading decks from source sites...')
    try:
        reload_all_decks()
        print('Deck reload complete.')
    except Exception as e:
        print(f"Deck reload failed (non-fatal): {e}")

    # =========================================================================
    # Phase 6: Elo rating recalculation
    # =========================================================================
    print('Recalculating Elo ratings...')
    try:
        calculate_elo_ratings(conn)
        print('Elo ratings updated.')
    except Exception as e:
        print(f"Elo calculation failed (non-fatal): {e}")

    conn.close()
    print('All done!')