from flask import render_template
from flask_login import login_required
from sqlalchemy import and_

from app import db
from app.cards import bp
from app.models import Deck, Player
from app.services.stats_service import get_card_usage_counts

# --- CSRF Audit (Requirement 16.1) ---
# This module has no POST endpoints. No CSRF concerns.
# ---


@bp.route('/cardmeta', methods=['GET'])
@login_required
def card_meta():
    cards = get_card_usage_counts()

    # Deck list for the sidebar: active decks with Archidekt-sourced decklists
    rows = (
        db.session.query(Deck.name, Deck.commander, Player.name)
        .join(Player, Player.id == Deck.player_id)
        .filter(and_(Deck.decksite.contains('archidekt'), Deck.active == True))  # noqa: E712
        .all()
    )
    deck_list = [
        {'name': name, 'commander': commander, 'player': player_name}
        for name, commander, player_name in rows
    ]
    deck_count = len(deck_list)

    return render_template('cards/show.html', cards=cards, decks=deck_list, count=deck_count)
