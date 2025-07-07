import sys

import ijson
import os.path
import requests
from app import models, db, create_app
from app.models import Card

from flask import current_app, render_template
from flask_login import login_required

from app.auth import role_required
from app.third_party_data import bp



def load_card_data():
    current_app.task_queue.enqueue(get_card_data, job_timeout=600)

    return render_template('index.html')

@bp.route('/LoadCardData', methods=['GET'])
@role_required('admin')
@login_required
def get_card_data():

    try:
        bulk_data = requests.get("https://api.scryfall.com/bulk-data").json()
        data = bulk_data['data']
        download_link = ''
        for entry in data:
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
                for data in card_data.iter_content(chunk_size=total_length / 1000):
                    f.write(data)

        with open('files/card_data.json', 'rb') as f:
            for card in ijson.items(f, "item"):
                print(card['name'])
                exists = models.Card.query.filter_by(id=card['id']).first()
                typeline_filter = True

                if 'type_line' in card:
                    if 'Card' in card['type_line']:
                        typeline_filter = False

                if 'paper' in card['games'] and typeline_filter:
                    card_entry = Card()
                    if exists:
                        card_entry = models.Card.query.filter_by(id=card['id']).first()

                    if not '//' in card['name']:
                        card_entry.Name = card['name']
                        card_entry.id = card['id']
                        card_entry.image_uri = card['image_uris']['large']
                        card_entry.commander_legal = True
                        card_entry.cmc = card['cmc']
                        card_entry.card_text = card['oracle_text']

                    elif ('image_uris' in card):
                        card_entry.Name = card['name'].split(' // ')[0]
                        card_entry.id = card['id']
                        card_entry.image_uri = card['image_uris']['large']
                        card_entry.commander_legal = True
                        card_entry.cmc = card['cmc']
                        card_entry.card_text = card['card_faces'][0]['oracle_text']
                        card_entry.back_card_text = card['card_faces'][1]['oracle_text']

                    elif ('cmc' in card):
                        card_entry.Name = card['name'].split(' // ')[0]
                        card_entry.id = card['id']
                        card_entry.image_uri = card['card_faces'][0]['image_uris']['large']
                        card_entry.back_image_uri = card['card_faces'][1]['image_uris']['large']
                        card_entry.commander_legal = True
                        card_entry.cmc = card['cmc']
                        card_entry.card_text = card['card_faces'][0]['oracle_text']
                        card_entry.back_card_text = card['card_faces'][1]['oracle_text']

                    else:
                        card_entry.Name = card['name'].split(' // ')[0]
                        card_entry.id = card['id']
                        card_entry.image_uri = card['card_faces'][0]['image_uris']['large']
                        card_entry.back_image_uri = card['card_faces'][1]['image_uris']['large']
                        card_entry.commander_legal = True
                        card_entry.cmc = card['card_faces'][0]['cmc']
                        card_entry.card_text = card['card_faces'][0]['oracle_text']
                        card_entry.back_card_text = card['card_faces'][1]['oracle_text']

                    db.session.add(card_entry)
            db.session.commit()
        return render_template('index.html')
    except Exception:
        pass

    finally:
        pass




