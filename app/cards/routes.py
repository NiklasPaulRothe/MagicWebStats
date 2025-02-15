from flask import render_template
from flask_login import login_required
from sqlalchemy import and_

from app import db
from app.cards import bp
from app.models import DeckComponent, Card, Deck, Player


@bp.route('/cardmeta', methods=['GET'])
@login_required
def card_meta():

    names = db.session.query(DeckComponent.name).distinct().all()
    entries = DeckComponent.query.all()
    deck_list = []
    decks = Deck.query.filter(and_(Deck.decksite.contains('archidekt'),Deck.Active == True)).all()
    deck_count = 0
    active_decks = []
    for deck in decks:
        deck_count +=1
        player = Player.query.filter_by(id=deck.Player).first()
        active_decks.append(deck.id)
        deck_list.append({
            'Name': deck.Name,
            'Commander': deck.Commander,
            'Player': player.Name
        })
    cards =[]
    for name in names:
        count = 0
        for entry in entries:
            if entry.name == name[0] and entry.deck_id in active_decks:
                count += entry.count
        cards.append({
            "Name": name[0],
            "Count": count
        })


    return render_template('cards/show.html', cards=cards, decks=deck_list, count=deck_count)