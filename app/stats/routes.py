import logging
from dataclasses import dataclass
from datetime import date
from sqlalchemy import literal, and_, func

from app import db
from app.stats import bp
from flask import render_template, flash, redirect, url_for, abort, request
from flask_login import login_required, current_user
from app.auth import role_required, has_personal_stats_access
import sqlalchemy as sa
from sqlalchemy import desc

from app.stats.forms import PlayerAddForm, DeckAddForm, GameAddForm, GameEditForm, ParticipantEditSubForm
from app.models import Player, Deck, Game, Participant, Card, User, AuditLog
from app.viewmodels import ColorUsage, ColorUsagePlayer
from app.services.audit import write_audit_log
from app.services.stats_service import get_players, get_active_decks, get_color_identities

logger = logging.getLogger(__name__)

# --- CSRF Audit (Requirement 16.1) ---
# All POST endpoints in this module are protected by Flask-WTF CSRFProtect (init'd in app/__init__.py).
# Form-based endpoints (game_add, game_edit, game_delete, player_add, deck_add) use WTForms which
# includes the CSRF token automatically. No exemptions are needed.
# ---



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
    if game.added_by_user_id != current_user.id:
        abort(403)


@bp.route('/manage/games')
@role_required('admin')
@login_required
def game_hub():
    page = request.args.get('page', 1, type=int)
    
    # Query games for current user, ordered by date descending, paginated
    query = (
        sa.select(Game)
        .where(Game.added_by_user_id == current_user.id)
        .order_by(Game.date.desc())
    )
    pagination = db.paginate(query, page=page, per_page=12, error_out=False)
    
    # Build GameRowViewModel for each game
    game_rows = []
    for game in pagination.items:
        # Resolve winner and first player names
        winner = db.session.get(Player, game.winner_id)
        first_player = db.session.get(Player, game.first_player_id)
        winner_name = winner.name if winner else ''
        first_player_name = first_player.name if first_player else ''
        
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
                player_name=player.name,
                deck_name=deck.name,
                commander_image=deck.image_uri
            ))
        
        # Build GameRowViewModel
        game_rows.append(GameRowViewModel(
            game_id=game.id,
            date=game.date,
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
    
    # Store info before deletion
    game_date = game.date
    
    # Delete all participants for this game
    db.session.execute(sa.delete(Participant).where(Participant.game_id == game_id))
    
    # Delete the game itself
    db.session.delete(game)
    write_audit_log('game_delete', 'Game', game_id, f'Deleted game on {game_date}')
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
    participant_names = [(p.name, p.name) for _, p, _ in participants_query]
    form.winner.choices = participant_names
    form.first.choices = participant_names
    
    # Build decks list for JS widget (same format as game_add)
    decks = get_active_decks()
    
    # Detect if the personal-stats user is a participant
    niklas_is_participant = False
    niklas_participant = None
    niklas_player_id = None
    
    if has_personal_stats_access(current_user):
        # Find the user's player record
        stats_user = db.session.get(User, current_user.id)
        if stats_user and stats_user.player_id:
            niklas_player_id = stats_user.player_id
            # Check if the user is a participant in this game
            for participant, player, deck in participants_query:
                if player.id == niklas_player_id:
                    niklas_is_participant = True
                    niklas_participant = participant
                    break
    
    # Handle POST submission
    if form.validate_on_submit():
        # Update Game fields
        game.date = form.date.data
        game.turns = form.turns.data
        game.final_blow = form.final_blow.data if form.final_blow.data else None
        game.first_ko_turn = form.first_ko_turn.data
        game.first_ko_by = form.first_ko_by.data if form.first_ko_by.data else None
        game.cedh = form.cedh.data
        
        # Resolve Winner and First_Player from names
        winner = db.session.scalar(
            sa.select(Player.id).where(Player.name == form.winner.data)
        )
        first_player = db.session.scalar(
            sa.select(Player.id).where(Player.name == form.first.data)
        )
        game.winner_id = winner
        game.first_player_id = first_player
        
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
                        sa.select(Player.id).where(Player.name == pf.lender.data)
                    )
                    if lender:
                        deck_owner_id = lender
                
                # Find the deck using the deck name and owner
                deck = Deck.query.filter(
                    and_(
                        literal(pf.deck.data).contains(Deck.name),
                        Deck.player_id == deck_owner_id
                    )
                ).first()
                
                if deck:
                    participant.deck_id = deck.id
                
                # Update other participant fields
                participant.early_sol_ring = pf.early_fast_mana.data
                participant.removal_played = pf.removal_played.data
                participant.targeted_by_removal = pf.targeted_by_removal.data
                participant.protection_played = pf.protection_played.data
        
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
        write_audit_log('game_edit', 'Game', game.id, f'Edited game on {game.date}')
        db.session.commit()
        
        # Flash success and redirect to hub
        flash('Game updated successfully!')
        return redirect(url_for('stats.game_hub'))
    
    # GET request or validation failed - pre-populate form
    # Pre-populate game-level fields
    form.date.data = game.date
    form.turns.data = game.turns
    form.final_blow.data = game.final_blow
    form.first_ko_turn.data = game.first_ko_turn
    form.first_ko_by.data = game.first_ko_by
    form.cedh.data = game.cedh
    
    # Pre-populate winner and first player
    winner = db.session.get(Player, game.winner_id)
    first_player = db.session.get(Player, game.first_player_id)
    form.winner.data = winner.name if winner else None
    form.first.data = first_player.name if first_player else None
    
    # Populate form.participants with each participant's data
    for participant, player, deck in participants_query:
        # Get active decks for the deck owner (lender if borrowed, player otherwise)
        deck_owner_id = deck.player_id
        player_decks = Deck.query.filter_by(player_id=deck_owner_id, active=True).all()
        # Use "Name (Commander)" format as value to match JS-built options
        deck_choices = [(f"{d.name} ({d.commander})", f"{d.name} ({d.commander})") for d in player_decks]
        
        # Ensure the current deck is in choices even if it's been deactivated
        current_deck_value = f"{deck.name} ({deck.commander})"
        if not any(c[0] == current_deck_value for c in deck_choices):
            deck_choices.insert(0, (current_deck_value, current_deck_value))
        
        # Determine if deck was borrowed (deck owner != player)
        is_borrowed = deck.player_id != player.id
        lender_name = None
        if is_borrowed:
            lender = db.session.get(Player, deck.player_id)
            lender_name = lender.name if lender else None
        
        # Create entry data dict
        # Use "DeckName (Commander)" format to match the JS-built select options
        entry_data = {
            'player_id': participant.player_id,
            'player_name': player.name,
            'deck': f"{deck.name} ({deck.commander})",
            'borrowed': is_borrowed,
            'lender': lender_name,
            'early_fast_mana': participant.early_sol_ring,
            'removal_played': participant.removal_played,
            'targeted_by_removal': participant.targeted_by_removal,
            'protection_played': participant.protection_played
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
                         show_my_game=has_personal_stats_access(current_user),
                         game_condition_suggestions=game_condition_suggestions,
                         player_names=player_names_list)


@bp.route('/PlayerAdd', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def player_add():
    form = PlayerAddForm()
    if form.validate_on_submit():
        player = Player(name=form.name.data)
        db.session.add(player)
        write_audit_log('player_add', 'Player', player.id, f'Added player: {player.name}')
        db.session.commit()
        flash('Player added!')
        return redirect(url_for('stats.game_hub'))
    return render_template('stats/PlayerAdd.html', form=form)

@bp.route('/DeckAdd', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def deck_add():
    form = DeckAddForm()
    player_choices = get_players()
    form.player.choices = player_choices
    ci_data = get_color_identities()
    form.color_identity.choices = [ci['name'] for ci in ci_data]
    if form.validate_on_submit():
        player = db.session.scalar(
            sa.select(Player.id).where(Player.name == form.player.data)
        )
        partner = None
        if form.partner.data != '':
            partner = form.partner.data

        # Commander image for main deck
        card = Card.query.filter_by(name=form.commander.data).first()
        img = None
        if card:
            front_face = next((f for f in card.faces if f.face_index == 0), None)
            if front_face:
                img = front_face.image_uri

        deck = Deck(
            name = form.name.data,
            commander = form.commander.data,
            player_id = player,
            color_identity = form.color_identity.data,
            partner = partner,
            image_uri = img,
            cedh = form.cedh.data,
            version = 1,
            patch = 0,
            change = 0,
            last_rework = func.current_date(),
            last_patch = func.current_date(),
            last_change = func.current_date()
        )
        db.session.add(deck)
        write_audit_log('deck_add', 'Deck', deck.id, f'Added deck: {deck.name} ({deck.commander}) for {form.player.data}')
        db.session.commit()
        flash('Deck added!')
        return redirect(url_for('stats.game_hub'))
    else:
        logger.debug("Form validation errors: %s", form.errors)
    return render_template('stats/DeckAdd.html', form=form, ci_data=ci_data)

@bp.route('/game-add', methods=['GET', 'POST'])
@role_required('admin')
@login_required
def game_add():
    form = GameAddForm()
    player = get_players()
    decks = get_active_decks()
    ci_data = get_color_identities()
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
                               game_condition_suggestions=game_condition_suggestions, ci_data=ci_data,
                               show_my_game=has_personal_stats_access(current_user))

    # Handle remove player action
    if form.remove_player.data and len(form.players) > form.players.min_entries:
        form.players.pop_entry()
        return render_template('stats/GameAdd.html', form=form, player=player, decks=decks,
                               game_condition_suggestions=game_condition_suggestions, ci_data=ci_data,
                               show_my_game=has_personal_stats_access(current_user))

    if not form.validate_on_submit():
        logger.debug("Form validation errors: %s", form.errors)

        # Handle form submission
    if form.validate_on_submit():
        winner = db.session.scalar(
            sa.select(Player.id).where(Player.name == form.winner.data)
        )
        first = db.session.scalar(
            sa.select(Player.id).where(Player.name == form.first.data)
        )

        game = Game( date = form.date.data,
                     first_player_id = first,
                     winner_id = winner,
                     planechase = False,
                     turns = form.turns.data,
                     final_blow = form.final_blow.data if form.final_blow.data else None,
                     first_ko_turn = form.first_ko_turn.data,
                     first_ko_by = form.first_ko_by.data if form.first_ko_by.data else None,
                     cedh = form.cedh.data,
                     added_by_user_id = current_user.id
        )
        db.session.add(game)
        db.session.flush()
        for participant in form.players:
            player = db.session.scalar(
                sa.select(Player.id).where(Player.name == participant.player.data)
            )
            # Set owner to participant and then overwrite with lender if Deck was borrowed
            owner = participant.player.data
            if participant.borrowed.data == True:
                owner = participant.lender.data

            # Contains Deck Name is necessary, because the form also contains the commander, so equal wouldn't work
            # To prevent similar named Decks to be confused we add the query for Deck owner
            deck = Deck.query.filter(and_(literal(participant.deck.data).contains(Deck.name),
                                          Deck.player_id == (Player.query.filter_by(name=owner).first().id))).first().id

            # Grab per-participant interaction values before overwriting the variable
            p_early_fast_mana = participant.early_fast_mana.data
            p_removal_played = participant.removal_played.data
            p_targeted_by_removal = participant.targeted_by_removal.data
            p_protection_played = participant.protection_played.data

            if (player == 1):
                participant = Participant (
                    game_id = game.id,
                    player_id = player,
                    deck_id = deck,
                    early_sol_ring = p_early_fast_mana,
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
                    fun_moments = form.fun_moments.data,
                    removal_played = p_removal_played,
                    targeted_by_removal = p_targeted_by_removal,
                    protection_played = p_protection_played
                )
            else:
                participant = Participant(
                    game_id=game.id,
                    player_id=player,
                    deck_id=deck,
                    early_sol_ring = p_early_fast_mana,
                    removal_played = p_removal_played,
                    targeted_by_removal = p_targeted_by_removal,
                    protection_played = p_protection_played
                )
            db.session.add(participant)
        write_audit_log('game_add', 'Game', game.id, f'Added game on {game.date}')
        db.session.commit()
        flash('Game added successfully!')
        return redirect(url_for('stats.game_hub'))

    # Render the form normally
    return render_template('stats/GameAdd.html', form=form, player=player, decks=decks,
                           game_condition_suggestions=game_condition_suggestions, ci_data=ci_data,
                           show_my_game=has_personal_stats_access(current_user))

@bp.route('/PlayerStats')
@login_required
def playerstats():
    from datetime import date, timedelta
    from app.models import Player, Game, Participant
    one_year_ago = date.today() - timedelta(days=365)
    active_player_names = set(
        row[0] for row in db.session.query(Player.name)
        .join(Participant, Participant.player_id == Player.id)
        .join(Game, Game.id == Participant.game_id)
        .filter(Game.date >= one_year_ago)
        .distinct()
        .all()
    )
    color_usage_player = [
        cup for cup in ColorUsagePlayer.query.all()
        if cup.Player in active_player_names
    ]
    return render_template('stats/playerstats.html', color_usage_player=color_usage_player)

@bp.route('/ColorStats')
@login_required
def colorstats():
    return render_template('stats/colorstats.html')

@bp.route('/DeckStats')
@login_required
def deckstats():
    return render_template('stats/deckstats.html')


@bp.route('/tracking-sheets')
@login_required
def tracking_sheets():
    return render_template('stats/tracking_sheets.html')


@bp.route('/tracking-sheets/standard')
@login_required
def tracking_sheet_standard():
    return render_template('stats/tracking_sheet_standard.html')


@bp.route('/tracking-sheets/personal')
@login_required
def tracking_sheet_personal():
    return render_template('stats/tracking_sheet_personal.html')


@bp.route('/audit-log')
@role_required('admin')
@login_required
def audit_log():
    
    page = request.args.get('page', 1, type=int)
    query = (
        sa.select(AuditLog)
        .order_by(AuditLog.timestamp.desc())
    )
    pagination = db.paginate(query, page=page, per_page=50, error_out=False)
    
    return render_template('stats/audit_log.html', pagination=pagination, entries=pagination.items)
