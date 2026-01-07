import time
import traceback

import pyrchidekt
from flask import current_app, render_template, redirect, url_for
from flask_login import login_required
from pyrchidekt.api import getDeckById

from app import db, third_party_data
from app.auth import role_required
from app.models import DeckComponent, Deck
from app.third_party_data import bp



def load_cards_for_decks():
    current_app.task_queue.enqueue(load_all_decks, job_timeout=600)

    return render_template('index.html')


def get_id_from_url(url):
    if 'archidekt' not in url:
        return None
    splitted = url.split('/')
    next = False
    for i in splitted:
        if next == True:
            return ('archidekt', i)
        if i == 'decks':
            next = True

    return None

def load_cards_from_archidekt(archidekt_id, deck_id):
    print('load cards...')
    print(archidekt_id)
    try:
        deck = pyrchidekt.api.getDeckById(archidekt_id.strip())
    except Exception as e:
        print(e)
    deck_categories = deck.categories

    Cards = DeckComponent.query.filter(DeckComponent.deck_id == deck_id).all()
    for card in Cards:
        db.session.delete(card)

    for card in deck.cards:
        try:
            in_deck = False
            for category in card.categories:
                for deck_category in deck_categories:
                    if category == deck_category.name and deck_category.included_in_deck:
                        in_deck = True
            if in_deck:
                component = DeckComponent(
                    deck_id = deck_id,
                    card_id = card.card.uid,
                    name = card.card.oracle_card.name,
                    count = card.quantity
                )
                db.session.add(component)
        except:
            name = card.card.oracle_card.name
            current_app.logger.info(f'{name} couldn''t be found' + traceback.format_exc())
            continue
    try:
        db.session.commit()
    except:
        print("Something went wrong while committing to the database for " + deck.name)
        db.session.rollback()
    print('end load cards....')
    return redirect(url_for('main.index'), code=302)

@bp.route('/LoadAllDecks', methods=['GET'])
@role_required('admin')
@login_required
def load_all_decks():
    decks = Deck.query.all()
    for deck in decks:
        if not deck.decklist == None and deck.decksite == None:
            deckbuilder = third_party_data.deckbuilder.get_id_from_url(deck.decklist)
            deck.decksite = deckbuilder[0].strip()
            deck.archidekt_id = deckbuilder[1].strip()
            db.session.commit;
        if not deck.decksite == None:
            if 'archidekt' in deck.decksite:
                try:
                    load_cards_from_archidekt(deck.archidekt_id.strip(), deck.id)
                    time.sleep(1)
                except:
                    deck.decksite = None
                    deck.archidekt_id = None
                    db.session.commit()

    return redirect(url_for('main.index'), code=302)