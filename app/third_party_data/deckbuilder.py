import traceback

from flask import current_app
from pyrchidekt.api import getDeckById
from sqlalchemy import delete

from app import db
from app.models import DeckComponent


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
    deck = getDeckById(archidekt_id)
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
    db.session.commit()