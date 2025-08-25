from sqlalchemy import literal, and_

from app import db
from app.stats import bp
from flask import render_template, flash, redirect, url_for
from flask_login import login_required
from app.auth import role_required
import sqlalchemy as sa
from sqlalchemy import desc

from app.stats.forms import PlayerAddForm, DeckAddForm, GameAddForm
from app.models import Player, Deck, Game, Participant, ColorIdentity, Card
from app.viewmodels import ColorUsage, ColorUsagePlayer


def get_player():
    player_list = []
    player = Player.query.order_by(Player.Name).all()
    for player in player:
        player_list.append(player.Name)
    return player_list

def get_decks():
    deck_list = []
    decks = Deck.query.order_by(desc(Deck.Name)).all()
    for deck in decks:
        player = Player.query.filter_by(id = deck.Player).first()
        if deck.Active:
            tupel = (deck.Name, deck.Commander, player.Name)
            deck_list.append(tupel)
    return deck_list

def get_ci():
    ci_list = []
    Identities= ColorIdentity.query.all()
    for identity in Identities:
        ci_list.append(identity.Name)
    return ci_list



@bp.route('/PlayerAdd', methods=['GET', 'POST'])
@role_required('admin')
@login_required
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
@role_required('admin')
@login_required
def deck_add():
    form = DeckAddForm()
    player_choices = get_player()
    form.player.choices = player_choices
    ci_choices = get_ci()
    form.color_identity.choices = ci_choices
    if form.validate_on_submit():
        player = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.player.data)
        )
        partner = None
        if form.partner.data != '':
            partner = form.partner.data

        # Commander image for main deck
        img = Card.query.filter_by(Name=form.commander.data).first().image_uri

        deck = Deck(
            Name = form.name.data,
            Commander = form.commander.data,
            Player = player,
            Color_Identity = form.color_identity.data,
            Partner = partner,
            image_uri = img
        )
        db.session.add(deck)
        db.session.commit()
        flash('Deck added!')
        return redirect(url_for('main.index'))
    else:
        print(form.errors)
    return render_template('stats/DeckAdd.html', form=form)

@bp.route('/game-add', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def game_add():
    form = GameAddForm()
    player = get_player()
    decks = get_decks()
    form.winner.choices = player
    form.first.choices = player

    # Handle add player action
    if form.add_player.data:
        form.players.append_entry()
        return render_template('stats/GameAdd.html', form=form)

    # Handle remove player action
    if form.remove_player.data and len(form.players) > form.players.min_entries:
        form.players.pop_entry()
        return render_template('stats/GameAdd.html', form=form)

    if not form.validate_on_submit():
        print(form.errors)

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
                     Planechase = form.planechase.data,
                     turns = form.turns.data,
                     final_blow = form.final_blow.data if form.final_blow.data else None,
                     first_ko_turn = form.first_ko_turn.data,
                     first_ko_by = form.first_ko_by.data if form.first_ko_by.data else None
        )
        db.session.add(game)
        db.session.commit()
        for participant in form.players:
            player = db.session.scalar(
                sa.select(Player.id).where(Player.Name == participant.player.data)
            )
            # Set owner to participant and then overwrite with lender if Deck was borrowed
            owner = participant.player.data
            if participant.borrowed.data == True:
                owner = participant.lender.data

            # Contains Deck Name is necessary, because the form also contains the commander, so equal wouldn't work
            # To prevent similar named Decks to be confused we add the query for Deck owner
            deck = Deck.query.filter(and_(literal(participant.deck.data).contains(Deck.Name),
                                          Deck.Player == (Player.query.filter_by(Name = owner).first().id))).first().id

            if (player == 1):
                participant = Participant (
                    game_id = game.id,
                    player_id = player,
                    deck_id = deck,
                    early_sol_ring = participant.early_fast_mana.data,
                    fun = form.fun.data,
                    performance = form.performance.data,
                    mulligans = form.mulligan.data,
                    comments = form.comment.data,
                    landdrops = form.landdrops.data,
                    lands = form.lands.data,
                    enough_mana = form.enough_mana.data,
                    enough_gas = form.enough_gas.data,
                    deckplan = form.deckplan.data,
                    unanswered_threats = form.unanswered_threats.data,
                    loss_without_answer = form.loss_without_answer.data,
                    selfmade_win = form.selfmade_win.data,
                    fun_moments = form.fun_moments.data
                )
            else:
                participant = Participant(
                    game_id=game.id,
                    player_id=player,
                    deck_id=deck,
                    early_sol_ring = participant.early_fast_mana.data
                )
            db.session.add(participant)
            db.session.commit()
        flash('Game added successfully!')
        return redirect(url_for('main.index'))

    # Render the form normally
    return render_template('stats/GameAdd.html', form=form, player=player, decks=decks)

@bp.route('/PlayerStats')
@login_required
def playerstats():
    color_usage_player = ColorUsagePlayer.query.all()
    return render_template('stats/playerstats.html', color_usage_player=color_usage_player)

@bp.route('/ColorStats')
@login_required
def colorstats():
    return render_template('stats/colorstats.html')

@bp.route('/DeckStats')
@login_required
def deckstats():
    return render_template('stats/deckstats.html')