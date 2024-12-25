import requests
from flask import jsonify, render_template
from flask_login import login_required
from sqlalchemy.orm import column_mapped_collection

from app import models, db
from app.main import bp
from app.models import Card


@bp.route('/load_card_data')
@login_required
def get_card_data():
    bulk_data = requests.get("https://api.scryfall.com/bulk-data").json()
    data = bulk_data['data']
    download_link = ''
    for entry in data:
        if entry['type'] == 'oracle_cards':
            download_link = entry['download_uri']
    card_data = requests.get(download_link).json()
    count = 2
    for card in card_data:
        print(count)
        print(card['name'])
        count = count + 1
        exists = models.Card.query.filter_by(id = card['oracle_id']).first()
        if card['multiverse_ids'] != [] and not '//' in card['name'] and 'paper' in card['games']:
            card_entry = Card()
            if exists:
                card_entry = models.Card.query.filter_by(id = card['oracle_id']).first()

            card_entry.Name = card['name']
            card_entry.id = card['oracle_id']
            card_entry.image_uri = card['image_uris']['large']
            card_entry.commander_legal = True
            card_entry.cmc = card['cmc']
            card_entry.card_text = card['oracle_text']
            db.session.add(card_entry)
            db.session.commit()
    return render_template('index.html')