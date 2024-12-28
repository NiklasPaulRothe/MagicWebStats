from flask import render_template
from flask_login import login_required

from app import db
from app.cards import bp
from app.models import DeckComponent, Card

@bp.route('/cardmeta', methods=['GET'])
@login_required
def card_meta():

    card_ids = db.session.query(DeckComponent.card_id).distinct().all()
    cards =[]
    for card_id in card_ids:
        count = 0
        entries = DeckComponent.query.all()
        for entry in entries:
            if entry.card_id == card_id[0]:
                count += entry.count
        name = db.session.query(Card.Name).filter(Card.id == card_id[0]).first()[0]
        cards.append({
            "Name": name,
            "Count": count
        })


    return render_template('cards/show.html', cards=cards)