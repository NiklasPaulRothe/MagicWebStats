from flask import render_template, flash, redirect, url_for, request, session, current_app
from flask_login import login_required, current_user
from sqlalchemy import select, and_

from app import db, models, third_party_data
from app.decks import bp
from app.decks.forms import DeckEditForm
from app.models import Deck, Player, User, Game, Participant
from app.third_party_data.deckbuilder import load_cards_from_archidekt


@bp.route('/edit/<deckname>', methods=['GET', 'POST'])
@login_required
def deck_edit(deckname):
    deck = Deck.query.filter(Deck.Name == deckname).one()
    user = User.query.filter(User.username == current_user.username).one()
    owner = Player.query.filter(user.spieler == Player.id).one()
    if deck.Player != owner.id:
        flash('Du bist nicht berechtigt dieses Deck zu bearbeiten')
        return redirect(url_for('main.index'))

    form = DeckEditForm()

    deckname = deckname + " (" + deck.Commander + ")"

    if not form.validate_on_submit():
        print(form.errors)

    if form.validate_on_submit():
        deck.Name = form.name.data
        deck.Active = not form.archive.data
        if (form.decklist.data != ""):
            deck.decklist = form.decklist.data
            deckbuilder = third_party_data.deckbuilder.get_id_from_url(form.decklist.data)
            deck.decksite = deckbuilder[0].strip()
            deck.archidekt_id = deckbuilder[1].strip()
            load_cards_from_archidekt(deck.archidekt_id, deck.id)
        db.session.commit()
        return redirect(url_for('main.user', username=current_user.username))
    form.name.default = deck.Name
    form.decklist.default = deck.decklist
    form.current_name.default = deck.Name
    form.process()

    return render_template('decks/edit.html', form=form, deckname=deckname)


@bp.route('/show/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def deck_show(deckname):
    current_app.logger.info(deckname)
    deck = models.Deck.query.filter(Deck.Name == deckname).first()
    games = models.Participant.query.filter(and_(Participant.player_id == deck.Player, Participant.deck_id == deck.id)).all()
    row = []
    for game in games:
        game_data = models.Game.query.filter_by(id = game.game_id).first()
        opponents = models.Participant.query.filter(and_(Participant.game_id == game.game_id,
                                                         Participant.player_id != deck.Player)).all()

        row.append({
            "Datum": game_data.Date,
            "Gegner": {(models.Player.query.filter_by(id = opponent.player_id).first().Name,
                        models.Deck.query.filter_by(id=opponent.deck_id).first().Name,
                        models.Deck.query.filter_by(id=opponent.deck_id).first().Commander) for opponent in opponents},
            "Winner": models.Player.query.filter_by(id = game_data.Winner).first().Name,
        })

    card = models.Card.query.filter_by(Name=models.Deck.query.filter_by(Name=deckname).first().Commander).first()
    commander = None
    if card is not None:
        commander = card.image_uri

    return render_template('decks/show.html', deckname=deckname, commander=commander, games=row)
