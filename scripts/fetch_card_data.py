import os
import time

import ijson
import psycopg2
import requests
from dotenv import load_dotenv
import pyrchidekt

if __name__ == '__main__':
    print('Fetching Card Data...')
    load_dotenv()
    
    # Fetch deck tags from Archidekt for all decks with archidekt links
    print('Fetching deck tags from Archidekt...')
    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
            'postgres://', 'postgresql://'))
        print('Connected to PostgreSQL for deck tags...')
        
        # Get all decks with archidekt_id
        cur = conn.cursor()
        cur.execute("""
            SELECT id, "Name", archidekt_id 
            FROM data_owner."Decks" 
            WHERE archidekt_id IS NOT NULL AND archidekt_id != ''
        """)
        decks_with_archidekt = cur.fetchall()
        
        print(f'Found {len(decks_with_archidekt)} decks with Archidekt links')
        
        for deck_id, deck_name, archidekt_id in decks_with_archidekt:
            try:
                print(f'Fetching tags for deck: {deck_name} (ID: {deck_id})')
                
                # Fetch deck data from Archidekt
                deck = pyrchidekt.api.getDeckById(archidekt_id.strip())
                deck_tags = getattr(deck, 'deck_tags', [])
                
                # Delete existing tags for this deck
                cur.execute("DELETE FROM data_owner.deck_tags WHERE deck_id = %s", (deck_id,))
                
                # Insert new tags
                if deck_tags:
                    for tag in deck_tags:
                        tag_name = tag['name'].strip()
                        if tag_name:  # Only insert non-empty tags
                            cur.execute("""
                                INSERT INTO data_owner.deck_tags (deck_id, tag)
                                VALUES (%s, %s)
                                ON CONFLICT (deck_id, tag) DO NOTHING
                            """, (deck_id, tag_name))
                    print(f'  Saved {len(deck_tags)} tags')
                else:
                    print(f'  No tags found')
                
                conn.commit()
                
                # Wait 1 second to avoid rate limiting
                time.sleep(1)
                
            except Exception as e:
                print(f'  Error fetching tags for deck {deck_name}: {str(e)}')
                conn.rollback()
                # Continue with next deck even if one fails
                continue
        
        print('Deck tags fetching completed!')
        cur.close()
        
    except Exception as e:
        print(f'Exception while fetching deck tags: {str(e)}')
    
    print('Starting Scryfall card data fetch...')

    # This Block fetches the complete data dump from scryfall in a json
    try:
        bulk_data = requests.get("https://api.scryfall.com/bulk-data").json()
        data = bulk_data['data']
        download_link = ''
        for entry in data:
            #get the download uri from bulk data export
            if entry['type'] == 'default_cards':
                download_link = entry['download_uri']

        if not os.path.exists('files'):
            os.makedirs('files')

        card_data = requests.get(download_link, stream=True)
        card_data.raise_for_status()
        with open('files/card_data.json', 'wb') as f:
            total_length = card_data.headers.get('content-length')
            if total_length is None:
                f.write(card_data.content)
            else:
                total_length = int(total_length)
                for data in card_data.iter_content(chunk_size=total_length/1000):
                    f.write(data)
        print('Bulk Data loaded...')
    except Exception:
        print('Exception while fetching scryfall data!')


    try:
        conn = psycopg2.connect(os.environ.get('DATABASE_URL', '').replace(
            'postgres://', 'postgresql://'))
        print('Connected to PostgreSQL...')
        with open('files/card_data.json', 'rb') as f:
            for card in ijson.items(f, "item"):
                typeline_filter = True

                # If type_line in cards it's a valid magic card and not some kind of token or art
                if 'type_line' in card:
                    if 'Card' in card['type_line']:
                        typeline_filter = False

                # Only if we have a valid magic card and it's a paper version we continue (no need for alchemy)
                if 'paper' in card['games'] and typeline_filter:

                    # Cards that have only one face (no MDFC, Adventure etc...)
                    if not '//' in card['name'] or 'SP//dr' in  card['name']:
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM data_owner.card_data WHERE id = %s", (card['id'],))
                        if cur.fetchone() != None:
                            cur.execute("UPDATE data_owner.card_data SET card_text = %s WHERE id = %s", (card['oracle_text'], card['id']))
                            print('Update ' + card['name'])
                        else:
                            cur.execute("""INSERT INTO data_owner.card_data (\"Name\", id, image_uri, commander_legal, cmc, card_text)
                                        VALUES(%s, %s, %s, %s, %s, %s);""", (card['name'], card['id'], card['image_uris']['large'], True, card['cmc'], card['oracle_text']))
                            print('Add ' + card['name'])

                    # Cards with two modes on the front of the card
                    elif ('image_uris' in card):
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM data_owner.card_data WHERE id = %s", (card['id'],))
                        if cur.fetchone() != None:
                            cur.execute("UPDATE data_owner.card_data SET card_text = %s, back_card_text = %s WHERE id = %s",
                                        (card['card_faces'][0]['oracle_text'], card['card_faces'][1]['oracle_text'],  card['id']))
                            print('Update ' + card['name'])
                        else:
                            cur.execute("""INSERT INTO data_owner.card_data (\"Name\", id, image_uri, commander_legal, cmc, card_text, back_card_text)
                                        VALUES(%s, %s, %s, %s, %s, %s, %s);""", (card['name'].split(' // ')[0], card['id'],
                                                                             card['image_uris']['large'], True, card['cmc'],
                                                                             card['card_faces'][0]['oracle_text'], card['card_faces'][1]['oracle_text']))
                            print('Add ' + card['name'])

                    # Cards with different images on front and back
                    elif ('cmc' in card):
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM data_owner.card_data WHERE id = %s", (card['id'],))
                        if cur.fetchone() != None:
                            cur.execute("UPDATE data_owner.card_data SET card_text = %s, back_card_text = %s WHERE id = %s",
                                        (card['card_faces'][0]['oracle_text'], card['card_faces'][1]['oracle_text'],  card['id']))
                            print('Update ' + card['name'])
                        else:
                            cur.execute("""INSERT INTO data_owner.card_data (\"Name\", id, image_uri, back_image_uri, commander_legal, cmc, card_text, back_card_text)
                                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s);""", (card['name'].split(' // ')[0], card['id'],
                                                                                    card['card_faces'][0]['image_uris']['large'], card['card_faces'][1]['image_uris']['large'],
                                                                                    True, card['cmc'],card['card_faces'][0]['oracle_text'],
                                                                                    card['card_faces'][1]['oracle_text']))
                            print('Add ' + card['name'])

                    # MDFC with two castable sides
                    else:
                        cur = conn.cursor()
                        cur.execute("SELECT id FROM data_owner.card_data WHERE id = %s", (card['id'],))
                        if cur.fetchone() != None:
                            cur.execute("UPDATE data_owner.card_data SET card_text = %s, back_card_text = %s WHERE id = %s",
                                        (card['card_faces'][0]['oracle_text'], card['card_faces'][1]['oracle_text'],  card['id']))
                            print('Update ' + card['name'])
                        else:
                            cur.execute("""INSERT INTO data_owner.card_data (\"Name\", id, image_uri, back_image_uri, commander_legal, cmc, card_text, back_card_text)
                                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s);""", (card['name'].split(' // ')[0], card['id'],
                                                                                    card['card_faces'][0]['image_uris']['large'], card['card_faces'][1]['image_uris']['large'],
                                                                                    True, card['card_faces'][0]['cmc'],card['card_faces'][0]['oracle_text'],
                                                                                    card['card_faces'][1]['oracle_text']))
                            print('Add ' + card['name'])

            conn.commit()
            print("Kartendaten erfolgreich aktualisiert...")
    except Exception as e:
        print('Exception: ' + str(e))

    finally:
        pass