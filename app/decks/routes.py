from flask import render_template, flash, redirect, url_for, request
from flask_login import login_required, current_user

from app import db, models
from app.decks import bp
from app.decks.forms import DeckEditForm
from app.models import Deck, Player, User


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
        print(deck.Active)
        if (form.decklist.data != ""):
            deck.decklist = form.decklist.data
        db.session.commit()
        return redirect(url_for('main.user', username=current_user.username))
    form.name.default = deck.Name
    form.decklist.default = deck.decklist
    form.current_name.default = deck.Name
    form.process()


    return render_template('decks/edit.html', form=form, deckname=deckname)

@bp.route('/show/<deckname>', methods=['GET'])
@login_required
def deck_show(deckname):
    commander = models.Card.query.filter_by(Name = models.Deck.query.filter_by(Name = deckname).first().Commander).first().image_uri

    return render_template('decks/show.html', deckname=deckname, commander=commander)