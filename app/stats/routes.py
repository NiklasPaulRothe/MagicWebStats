from flask_security import roles_accepted

from app import db, admin_permission
from app.stats import bp
from flask import render_template, flash, redirect, url_for, request, session
from flask_login import login_required
import sqlalchemy as sa

from app.stats.forms import PlayerAddForm, DeckAddForm, GameAddForm
from app.models import Player, Deck, Game, Participant



@bp.route('/PlayerAdd', methods=['GET', 'POST'])
@admin_permission.require(http_exception=403)
def player_add():
    form = PlayerAddForm()
    if form.validate_on_submit():
        player = Player(Name = form.name.data)
        db.session.add(player)
        db.session.commit()
        flash('Player added!')
        return redirect(url_for('main.index'))
    return render_template('stats/PlayerAdd.html', form=form)

@bp.route('/DeckAdd', methods=['GET', 'POST'])
@admin_permission.require(http_exception=403)
@login_required
def deck_add():
    form = DeckAddForm()
    if form.validate_on_submit():
        player = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.player.data)
        )
        deck = Deck(
            Name = form.name.data,
            Commander = form.commander.data,
            Player = player,
            Color_Identity = form.color_identity.data,
            Partner = form.partner.data
        )
        db.session.add(deck)
        db.session.commit()
        flash('Deck added!')
        return redirect(url_for('main.index'))
    return render_template('stats/DeckAdd.html', form=form)

@bp.route('/game-add', methods=['GET', 'POST'])
@admin_permission.require(http_exception=403)
@login_required
def game_add():
    form = GameAddForm()

    # Handle add player action
    if form.add_player.data:
        form.players.append_entry()
        return render_template('stats/GameAdd.html', form=form)

    # Handle remove player action
    if form.remove_player.data and len(form.players) > form.players.min_entries:
        form.players.pop_entry()
        return render_template('stats/GameAdd.html', form=form)

    # Handle form submission
    if form.validate_on_submit():
        winner = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.winner.data)
        )
        first = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.first.data)
        )
        game = Game( Date = form.date.data,
                     First_Player = first,
                     Winner = winner,
                     Planechase = form.planechase.data
        )
        db.session.add(game)
        db.session.commit()
        print(game.id)
        for participant in form.players:
            player = db.session.scalar(
                sa.select(Player.id).where(Player.Name == participant.player.data)
            )
            deck = db.session.scalar(
                sa.select(Deck.id).where(Deck.Name == participant.deck.data)
            )
            if (player == 1):
                participant = Participant (
                    game_id = game.id,
                    player_id = player,
                    deck_id = deck,
                    fun = form.fun.data,
                    performance = form.performance.data,
                    mulligans = form.mulligan.data,
                    comments = form.comment.data
                )
            else:
                participant = Participant(
                    game_id=game.id,
                    player_id=player,
                    deck_id=deck
                )
            db.session.add(participant)
            db.session.commit()
        flash('Game added successfully!')
        return redirect(url_for('main.index'))

    # Render the form normally
    return render_template('stats/GameAdd.html', form=form)

@bp.route('/PlayerStats')
@login_required
def playerstats():
    return render_template('stats/playerstats.html')

@bp.route('/ColorStats')
@login_required
def colorstats():
    return render_template('stats/colorstats.html')

@bp.route('/DeckStats')
@login_required
def deckstats():
    return render_template('stats/deckstats.html')