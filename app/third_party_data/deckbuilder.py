from pyrchidekt.api import getDeckById

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

    for card in deck.cards:
        component = DeckComponent(
            deck_id = deck_id,
            card_id = card.card.uid
        )
        db.session.add(component)
    db.session.commit()