from flask import render_template
from flask_login import login_required

from app import db
from app.cards import bp
from app.models import DeckComponent, Card

@bp.route('/cardmeta', methods=['GET'])
@login_required
def card_meta():

    names = db.session.query(DeckComponent.name).distinct().all()
    cards =[]
    for name in names:
        count = 0
        entries = DeckComponent.query.all()
        for entry in entries:
            if entry.name == name[0]:
                count += entry.count
        cards.append({
            "Name": name[0],
            "Count": count
        })


    return render_template('cards/show.html', cards=cards)