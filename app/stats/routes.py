from dataclasses import dataclass
from datetime import date
from sqlalchemy import literal, and_, func

from app import db
from app.stats import bp
from flask import render_template, flash, redirect, url_for, abort, request
from flask_login import login_required, current_user
from app.auth import role_required
import sqlalchemy as sa
from sqlalchemy import desc

from app.stats.forms import PlayerAddForm, DeckAddForm, GameAddForm, GameEditForm, ParticipantEditSubForm
from app.models import Player, Deck, Game, Participant, ColorIdentity, Card, ColorComponent, Color, User
from app.viewmodels import ColorUsage, ColorUsagePlayer


@dataclass
class ParticipantDisplay:
    player_name: str
    deck_name: str
    commander_image: str


@dataclass
class GameRowViewModel:
    game_id: int
    date: date
    winner_name: str
    first_player_name: str
    participants: list  # list of ParticipantDisplay


def _assert_game_owner(game: Game) -> None:
    if game.added_by != current_user.id:
        abort(403)


def get_player():
    player_list = []
    player = Player.query.order_by(Player.Name).all()
    for player in player:
        player_list.append(player.Name)
    return player_list

def get_decks():
    deck_list = []
    decks = Deck.query.order_by(Deck.Commander).all()
    for deck in decks:
        player = Player.query.filter_by(id = deck.Player).first()
        if deck.Active:
            tupel = (deck.Name, deck.Commander, player.Name)
            deck_list.append(tupel)
    return deck_list

def get_ci():
    ci_list = []
    colorless = Color.query.filter_by(Name='Colorless').first()
    colorless_img = colorless.img if colorless and colorless.img else None
    identities = ColorIdentity.query.all()
    for identity in identities:
        components = ColorComponent.query.filter_by(color_identity=identity.Name).all()
        imgs = []
        for comp in components:
            color = Color.query.filter_by(Name=comp.color).first()
            if color and color.img:
                imgs.append(color.img)
        if not imgs and colorless_img:
            imgs = [colorless_img]
        ci_list.append({'name': identity.Name, 'imgs': imgs})
    return ci_list



@bp.route('/manage/games')
@role_required('admin')
@login_required
def game_hub():
    page = request.args.get('page', 1, type=int)
    
    # Query games for current user, ordered by date descending, paginated
    query = (
        sa.select(Game)
        .where(Game.added_by == current_user.id)
        .order_by(Game.Date.desc())
    )
    pagination = db.paginate(query, page=page, per_page=12, error_out=False)
    
    # Build GameRowViewModel for each game
    game_rows = []
    for game in pagination.items:
        # Resolve winner and first player names
        winner = db.session.get(Player, game.Winner)
        first_player = db.session.get(Player, game.First_Player)
        winner_name = winner.Name if winner else ''
        first_player_name = first_player.Name if first_player else ''
        
        # Query participants with their player and deck info
        participants_query = (
            db.session.query(Participant, Player, Deck)
            .join(Player, Player.id == Participant.player_id)
            .join(Deck, Deck.id == Participant.deck_id)
            .filter(Participant.game_id == game.id)
            .all()
        )
        
        # Build ParticipantDisplay list
        participants = []
        for participant, player, deck in participants_query:
            participants.append(ParticipantDisplay(
                player_name=player.Name,
                deck_name=deck.Name,
                commander_image=deck.image_uri
            ))
        
        # Build GameRowViewModel
        game_rows.append(GameRowViewModel(
            game_id=game.id,
            date=game.Date,
            winner_name=winner_name,
            first_player_name=first_player_name,
            participants=participants
        ))
    
    return render_template('stats/game_hub.html', pagination=pagination, game_rows=game_rows)


@bp.route('/manage/games/<int:game_id>/delete', methods=['POST'])
@role_required('admin')
@login_required
def game_delete(game_id):
    # Load game or 404
    game = db.get_or_404(Game, game_id)
    
    # Assert ownership
    _assert_game_owner(game)
    
    # Delete all participants for this game
    db.session.execute(sa.delete(Participant).where(Participant.game_id == game_id))
    
    # Delete the game itself
    db.session.delete(game)
    db.session.commit()
    
    # Flash success and redirect to hub
    flash('Game deleted successfully!')
    return redirect(url_for('stats.game_hub'))


@bp.route('/manage/games/<int:game_id>/edit', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def game_edit(game_id):
    # Load game or 404
    game = db.get_or_404(Game, game_id)
    
    # Assert ownership
    _assert_game_owner(game)
    
    # Load all participants with their player and deck info
    participants_query = (
        db.session.query(Participant, Player, Deck)
        .join(Player, Player.id == Participant.player_id)
        .join(Deck, Deck.id == Participant.deck_id)
        .filter(Participant.game_id == game_id)
        .all()
    )
    
    # Instantiate GameEditForm
    form = GameEditForm()
    
    # Build choices for winner and first from existing participants only
    participant_names = [(p.Name, p.Name) for _, p, _ in participants_query]
    form.winner.choices = participant_names
    form.first.choices = participant_names
    
    # Build decks list for JS widget (same format as game_add)
    decks = get_decks()
    
    # Detect if Niklas is a participant
    niklas_is_participant = False
    niklas_participant = None
    niklas_player_id = None
    
    if current_user.username == 'Niklas':
        # Find Niklas's player record
        niklas_user = db.session.get(User, current_user.id)
        if niklas_user and niklas_user.spieler:
            niklas_player_id = niklas_user.spieler
            # Check if Niklas is a participant in this game
            for participant, player, deck in participants_query:
                if player.id == niklas_player_id:
                    niklas_is_participant = True
                    niklas_participant = participant
                    break
    
    # Handle POST submission
    if form.validate_on_submit():
        # Update Game fields
        game.Date = form.date.data
        game.turns = form.turns.data
        game.final_blow = form.final_blow.data if form.final_blow.data else None
        game.first_ko_turn = form.first_ko_turn.data
        game.first_ko_by = form.first_ko_by.data if form.first_ko_by.data else None
        game.cedh = form.cedh.data
        
        # Resolve Winner and First_Player from names
        winner = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.winner.data)
        )
        first_player = db.session.scalar(
            sa.select(Player.id).where(Player.Name == form.first.data)
        )
        game.Winner = winner
        game.First_Player = first_player
        
        # Update each participant
        for pf in form.participants:
            player_id = pf.player_id.data
            
            # Load the matching Participant record
            participant = db.session.query(Participant).filter_by(
                game_id=game_id,
                player_id=player_id
            ).first()
            
            if participant:
                # Determine deck owner (use lender if borrowed, otherwise use player)
                deck_owner_id = player_id
                if pf.borrowed.data and pf.lender.data:
                    # Resolve lender name to player_id
                    lender = db.session.scalar(
                        sa.select(Player.id).where(Player.Name == pf.lender.data)
                    )
                    if lender:
                        deck_owner_id = lender
                
                # Find the deck using the deck name and owner
                deck = Deck.query.filter(
                    and_(
                        literal(pf.deck.data).contains(Deck.Name),
                        Deck.Player == deck_owner_id
                    )
                ).first()
                
                if deck:
                    participant.deck_id = deck.id
                
                # Update other participant fields
                participant.early_sol_ring = pf.early_fast_mana.data
        
        # Update Niklas's "My Game" fields if applicable
        if niklas_is_participant and niklas_player_id:
            niklas_participant_record = db.session.query(Participant).filter_by(
                game_id=game_id,
                player_id=niklas_player_id
            ).first()
            
            if niklas_participant_record:
                niklas_participant_record.mulligans = form.my_game.mulligans.data
                niklas_participant_record.landdrops = form.my_game.landdrops.data
                niklas_participant_record.enough_mana = form.my_game.enough_mana.data
                niklas_participant_record.enough_gas = form.my_game.enough_gas.data
                niklas_participant_record.deckplan = form.my_game.deckplan.data
                niklas_participant_record.unanswered_threats = form.my_game.unanswered_threats.data
                niklas_participant_record.loss_without_answer = form.my_game.loss_without_answer.data
                niklas_participant_record.selfmade_win = form.my_game.selfmade_win.data
                niklas_participant_record.fun_moments = form.my_game.fun_moments.data
                niklas_participant_record.comments = form.my_game.comment.data
        
        # Commit all changes
        db.session.commit()
        
        # Flash success and redirect to hub
        flash('Game updated successfully!')
        return redirect(url_for('stats.game_hub'))
    
    # GET request or validation failed - pre-populate form
    # Pre-populate game-level fields
    form.date.data = game.Date
    form.turns.data = game.turns
    form.final_blow.data = game.final_blow
    form.first_ko_turn.data = game.first_ko_turn
    form.first_ko_by.data = game.first_ko_by
    form.cedh.data = game.cedh
    
    # Pre-populate winner and first player
    winner = db.session.get(Player, game.Winner)
    first_player = db.session.get(Player, game.First_Player)
    form.winner.data = winner.Name if winner else None
    form.first.data = first_player.Name if first_player else None
    
    # Populate form.participants with each participant's data
    for participant, player, deck in participants_query:
        # Get active decks for this player
        player_decks = Deck.query.filter_by(Player=player.id, Active=True).all()
        deck_choices = [(d.Name, f"{d.Name} ({d.Commander})") for d in player_decks]
        
        # Determine if deck was borrowed (deck owner != player)
        is_borrowed = deck.Player != player.id
        lender_name = None
        if is_borrowed:
            lender = db.session.get(Player, deck.Player)
            lender_name = lender.Name if lender else None
        
        # Create entry data dict
        entry_data = {
            'player_id': participant.player_id,
            'player_name': player.Name,
            'deck': deck.Name,
            'borrowed': is_borrowed,
            'lender': lender_name,
            'early_fast_mana': participant.early_sol_ring
        }
        
        # Append entry to form.participants
        form.participants.append_entry(entry_data)
        
        # Set deck choices for the newly added entry
        form.participants[-1].deck.choices = deck_choices
        
        # Set lender choices (all players)
        form.participants[-1].lender.choices = participant_names
    
    # Pre-populate "My Game" section if Niklas is a participant
    if niklas_is_participant and niklas_participant:
        form.my_game.mulligans.data = niklas_participant.mulligans
        form.my_game.landdrops.data = niklas_participant.landdrops
        form.my_game.enough_mana.data = niklas_participant.enough_mana
        form.my_game.enough_gas.data = niklas_participant.enough_gas
        form.my_game.deckplan.data = niklas_participant.deckplan
        form.my_game.unanswered_threats.data = niklas_participant.unanswered_threats
        form.my_game.loss_without_answer.data = niklas_participant.loss_without_answer
        form.my_game.selfmade_win.data = niklas_participant.selfmade_win
        form.my_game.fun_moments.data = niklas_participant.fun_moments
        form.my_game.comment.data = niklas_participant.comments
    
    # Build autocomplete suggestions from union of distinct final_blow + first_ko_by values
    final_blow_vals = db.session.query(Game.final_blow).filter(Game.final_blow.isnot(None))
    first_ko_by_vals = db.session.query(Game.first_ko_by).filter(Game.first_ko_by.isnot(None))
    combined = final_blow_vals.union(first_ko_by_vals).all()
    game_condition_suggestions = sorted(set(r[0] for r in combined))
    
    # Extract player names for JavaScript
    player_names_list = [p[0] for p in participant_names]
    
    return render_template('stats/game_edit.html', 
                         form=form, 
                         decks=decks, 
                         niklas_is_participant=niklas_is_participant,
                         game_condition_suggestions=game_condition_suggestions,
                         player_names=player_names_list)


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
    ci_data = get_ci()
    form.color_identity.choices = [ci['name'] for ci in ci_data]
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
            image_uri = img,
            cedh = form.cedh.data,
            Version = 1,
            patch = 0,
            change = 0,
            Last_Rework = func.current_date(),
            last_patch = func.current_date(),
            Last_Change = func.current_date()
        )
        db.session.add(deck)
        db.session.commit()
        flash('Deck added!')
        return redirect(url_for('main.index'))
    else:
        print(form.errors)
    return render_template('stats/DeckAdd.html', form=form, ci_data=ci_data)

@bp.route('/game-add', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def game_add():
    form = GameAddForm()
    player = get_player()
    decks = get_decks()
    form.winner.choices = player
    form.first.choices = player

    # Build autocomplete suggestions from union of distinct final_blow + first_ko_by values
    final_blow_vals = db.session.query(Game.final_blow).filter(Game.final_blow.isnot(None))
    first_ko_by_vals = db.session.query(Game.first_ko_by).filter(Game.first_ko_by.isnot(None))
    combined = final_blow_vals.union(first_ko_by_vals).all()
    game_condition_suggestions = sorted(set(r[0] for r in combined))

    # Handle add player action
    if form.add_player.data:
        form.players.append_entry()
        return render_template('stats/GameAdd.html', form=form, player=player, decks=decks,
                               game_condition_suggestions=game_condition_suggestions)

    # Handle remove player action
    if form.remove_player.data and len(form.players) > form.players.min_entries:
        form.players.pop_entry()
        return render_template('stats/GameAdd.html', form=form, player=player, decks=decks,
                               game_condition_suggestions=game_condition_suggestions)

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
                     Planechase = False,
                     turns = form.turns.data,
                     final_blow = form.final_blow.data if form.final_blow.data else None,
                     first_ko_turn = form.first_ko_turn.data,
                     first_ko_by = form.first_ko_by.data if form.first_ko_by.data else None,
                     cedh = form.cedh.data,
                     added_by = current_user.id
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
    return render_template('stats/GameAdd.html', form=form, player=player, decks=decks,
                           game_condition_suggestions=game_condition_suggestions)

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