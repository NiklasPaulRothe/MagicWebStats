import gzip
import json
import os
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


def should_skip_card(card: dict) -> bool:
    """Return True if the card should be excluded (art_series, non-paper, token-like)."""
    # Skip art series
    if card.get('layout') == 'art_series':
        return True
    # Skip non-paper cards
    if 'paper' not in card.get('games', []):
        return True
    # Skip token-like entries with "Card" in type_line
    type_line = card.get('type_line', '')
    if 'Card' in type_line:
        return True
    return False


def upsert_card(cur, card: dict) -> None:
    """INSERT ... ON CONFLICT UPDATE for the cards table."""
    cur.execute("""
        INSERT INTO data_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            released_at = EXCLUDED.released_at
    """, (
        card['id'],
        card['oracle_id'],
        card['name'],
        card.get('mana_cost'),
        card.get('cmc', 0),
        card['type_line'],
        card.get('oracle_text'),
        card['layout'],
        card['set'],
        card['set_name'],
        card['rarity'],
        card.get('released_at')
    ))


def insert_card_faces(cur, card_id: str, card: dict) -> None:
    """Insert face rows — handles single-face and multi-face cards."""
    if 'card_faces' in card:
        # Multi-face card: insert one row per face
        for idx, face in enumerate(card['card_faces']):
            image_uri = face.get('image_uris', {}).get('large') if 'image_uris' in face else None
            cur.execute("""
                INSERT INTO data_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri)
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
            INSERT INTO data_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri)
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
            INSERT INTO data_owner.card_colors (card_id, color)
            VALUES (%s, %s)
        """, (card_id, color))

    # Insert color identity (one row per color)
    for color in card.get('color_identity', []):
        cur.execute("""
            INSERT INTO data_owner.card_color_identity (card_id, color)
            VALUES (%s, %s)
        """, (card_id, color))

    # Insert keywords (one row per keyword)
    for keyword in card.get('keywords', []):
        cur.execute("""
            INSERT INTO data_owner.card_keywords (card_id, keyword)
            VALUES (%s, %s)
        """, (card_id, keyword))

    # Insert legalities (one row per format)
    legalities = card.get('legalities', {})
    for format_name, status in legalities.items():
        cur.execute("""
            INSERT INTO data_owner.card_legalities (card_id, format, status)
            VALUES (%s, %s, %s)
        """, (card_id, format_name, status))


def process_oracle_tags(cur, tags_url: str) -> None:
    """Download oracle tags JSONL, truncate oracle_tags table, batch insert."""
    cur.execute("TRUNCATE data_owner.oracle_tags")

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
        "INSERT INTO data_owner.oracle_tags (oracle_id, tag) VALUES %s",
        batch
    )


if __name__ == '__main__':
    print('Fetching Card Data...')
    load_dotenv()

    conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
        'postgres://', 'postgresql://'))

    # =========================================================================
    # Phase 1: Archidekt deck tags (COMMENTED OUT FOR TESTING)
    # =========================================================================
    # print('Fetching deck tags from Archidekt...')
    # try:
    #     cur = conn.cursor()
    #     cur.execute("""
    #         SELECT id, "Name", archidekt_id 
    #         FROM data_owner."Decks" 
    #         WHERE archidekt_id IS NOT NULL AND archidekt_id != ''
    #     """)
    #     decks_with_archidekt = cur.fetchall()
    #
    #     print(f'Found {len(decks_with_archidekt)} decks with Archidekt links')
    #
    #     for deck_id, deck_name, archidekt_id in decks_with_archidekt:
    #         try:
    #             print(f'Fetching tags for deck: {deck_name} (ID: {deck_id})')
    #             deck = pyrchidekt.api.getDeckById(archidekt_id.strip())
    #             deck_tags = getattr(deck, 'deck_tags', [])
    #
    #             cur.execute("DELETE FROM data_owner.deck_tags WHERE deck_id = %s", (deck_id,))
    #
    #             if deck_tags:
    #                 for tag in deck_tags:
    #                     tag_name = tag['name'].strip()
    #                     if tag_name:
    #                         cur.execute("""
    #                             INSERT INTO data_owner.deck_tags (deck_id, tag)
    #                             VALUES (%s, %s)
    #                             ON CONFLICT (deck_id, tag) DO NOTHING
    #                         """, (deck_id, tag_name))
    #                 print(f'  Saved {len(deck_tags)} tags')
    #             else:
    #                 print(f'  No tags found')
    #
    #             conn.commit()
    #             time.sleep(1)
    #
    #         except Exception as e:
    #             print(f'  Error fetching tags for deck {deck_name}: {str(e)}')
    #             conn.rollback()
    #             continue
    #
    #     print('Deck tags fetching completed!')
    #     cur.close()
    #
    # except Exception as e:
    #     print(f'Archidekt tags phase failed: {str(e)}')
    #     # Continue to Phase 2 regardless (Req 12.4)

    # =========================================================================
    # Phase 2: Scryfall card data (new JSONL streaming + batched inserts)
    # =========================================================================
    print('Starting Scryfall card data fetch...')
    try:
        from psycopg2.extras import execute_values

        cards_url = get_bulk_data_uri("default_cards")
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

            # Skip cards missing required fields
            if 'oracle_id' not in card or 'type_line' not in card:
                continue

            card_id = card['id']
            card_ids_in_batch.append(card_id)

            # Accumulate card row
            cards_batch.append((
                card_id,
                card['oracle_id'],
                card['name'],
                card.get('mana_cost'),
                card.get('cmc', 0),
                card['type_line'],
                card.get('oracle_text'),
                card['layout'],
                card['set'],
                card['set_name'],
                card['rarity'],
                card.get('released_at')
            ))

            # Accumulate faces
            if 'card_faces' in card:
                for idx, face in enumerate(card['card_faces']):
                    image_uri = face.get('image_uris', {}).get('large') if 'image_uris' in face else None
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
                cur.execute("DELETE FROM data_owner.card_faces WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM data_owner.card_colors WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM data_owner.card_color_identity WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM data_owner.card_keywords WHERE card_id IN %s", (id_tuple,))
                cur.execute("DELETE FROM data_owner.card_legalities WHERE card_id IN %s", (id_tuple,))

                execute_values(cur, """
                    INSERT INTO data_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        oracle_id = EXCLUDED.oracle_id, name = EXCLUDED.name, mana_cost = EXCLUDED.mana_cost,
                        cmc = EXCLUDED.cmc, type_line = EXCLUDED.type_line, oracle_text = EXCLUDED.oracle_text,
                        layout = EXCLUDED.layout, set_code = EXCLUDED.set_code, set_name = EXCLUDED.set_name,
                        rarity = EXCLUDED.rarity, released_at = EXCLUDED.released_at
                """, cards_batch)

                if faces_batch:
                    execute_values(cur, "INSERT INTO data_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri) VALUES %s", faces_batch)
                if colors_batch:
                    execute_values(cur, "INSERT INTO data_owner.card_colors (card_id, color) VALUES %s", colors_batch)
                if color_identity_batch:
                    execute_values(cur, "INSERT INTO data_owner.card_color_identity (card_id, color) VALUES %s", color_identity_batch)
                if keywords_batch:
                    execute_values(cur, "INSERT INTO data_owner.card_keywords (card_id, keyword) VALUES %s", keywords_batch)
                if legalities_batch:
                    execute_values(cur, "INSERT INTO data_owner.card_legalities (card_id, format, status) VALUES %s", legalities_batch)

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
            cur.execute("DELETE FROM data_owner.card_faces WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM data_owner.card_colors WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM data_owner.card_color_identity WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM data_owner.card_keywords WHERE card_id IN %s", (id_tuple,))
            cur.execute("DELETE FROM data_owner.card_legalities WHERE card_id IN %s", (id_tuple,))

            execute_values(cur, """
                INSERT INTO data_owner.cards (id, oracle_id, name, mana_cost, cmc, type_line, oracle_text, layout, set_code, set_name, rarity, released_at)
                VALUES %s
                ON CONFLICT (id) DO UPDATE SET
                    oracle_id = EXCLUDED.oracle_id, name = EXCLUDED.name, mana_cost = EXCLUDED.mana_cost,
                    cmc = EXCLUDED.cmc, type_line = EXCLUDED.type_line, oracle_text = EXCLUDED.oracle_text,
                    layout = EXCLUDED.layout, set_code = EXCLUDED.set_code, set_name = EXCLUDED.set_name,
                    rarity = EXCLUDED.rarity, released_at = EXCLUDED.released_at
            """, cards_batch)

            if faces_batch:
                execute_values(cur, "INSERT INTO data_owner.card_faces (card_id, face_index, name, mana_cost, type_line, oracle_text, image_uri) VALUES %s", faces_batch)
            if colors_batch:
                execute_values(cur, "INSERT INTO data_owner.card_colors (card_id, color) VALUES %s", colors_batch)
            if color_identity_batch:
                execute_values(cur, "INSERT INTO data_owner.card_color_identity (card_id, color) VALUES %s", color_identity_batch)
            if keywords_batch:
                execute_values(cur, "INSERT INTO data_owner.card_keywords (card_id, keyword) VALUES %s", keywords_batch)
            if legalities_batch:
                execute_values(cur, "INSERT INTO data_owner.card_legalities (card_id, format, status) VALUES %s", legalities_batch)

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

    conn.close()
    print('All done!')