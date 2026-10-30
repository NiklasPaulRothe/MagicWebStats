from app import db
from app.api import bp
from app.api import queries
from app.api.formatters import format_deck_data, format_player_stats, format_user_deck, format_user_deck_archive
from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import func
import sqlalchemy as sa

from app.auth import role_required
from app.models import Player, User, Color, ColorComponent, Deck, Card, ColorIdentity, AuditLog
from app.services.audit import write_audit_log
from app.services.color_service import resolve_color_images

# --- CSRF Audit (Requirement 16.1) ---
# All POST endpoints in this module are protected by Flask-WTF CSRFProtect (init'd in app/__init__.py).
# - quick_add_player: JSON API, receives CSRF token via X-CSRFToken header from JavaScript (GameAdd.html)
# - quick_add_deck: JSON API, receives CSRF token via X-CSRFToken header from JavaScript (GameAdd.html)
# CSRFProtect automatically validates the X-CSRFToken header for AJAX POST requests.
# No exemptions are needed.
# ---


@bp.route('/data')
@login_required
def data():
    results = queries.get_player_stats(db.session)
    return jsonify([format_player_stats(r) for r in results])

@bp.route('/color-data')
@login_required
def color_data():
    results = queries.get_color_data(db.session)
    response = []
    for r in results:
        imgs = resolve_color_images(r['name'])
        response.append({
            "name": r['name'],
            "games": r['games'],
            "wins": r['wins'],
            "winrate_pct": r['winrate_pct'],
            "color_imgs": imgs,
        })
    return jsonify(response)

@bp.route('/deck-data')
@login_required
def deck_data():
    results = queries.get_deck_data(db.session)
    response = []
    for r in results:
        # Colorless fallback: query layer returns empty list for decks with no color images
        if not r['color_imgs']:
            r['color_imgs'] = resolve_color_images(r['color_identity'])
        response.append(format_deck_data(r))
    return jsonify(response)

@bp.route('/userdecks/archive/<spieler>')
@login_required
def userdecks_archive(spieler):
    results = queries.get_user_decks_archive(db.session, spieler)
    for r in results:
        if not r['color_imgs']:
            r['color_imgs'] = resolve_color_images(r['color_identity'])
    return jsonify([format_user_deck_archive(r) for r in results])


@bp.route('/userdecks/<spieler>')
@login_required
def userdecks(spieler):
    results = queries.get_user_decks(db.session, spieler)
    for r in results:
        if not r['color_imgs']:
            r['color_imgs'] = resolve_color_images(r['color_identity'])
    return jsonify([format_user_deck(r) for r in results])


@bp.route('/quick-add-player', methods=['POST'])
@role_required('admin')
@login_required
def quick_add_player():
    """Add a new player via AJAX. Returns the new player name on success."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({'error': 'Name is required'}), 400

    name = data['name'].strip()
    if not name:
        return jsonify({'error': 'Name is required'}), 400

    # Check if player already exists
    existing = db.session.scalar(sa.select(Player).where(Player.name == name))
    if existing:
        return jsonify({'error': 'Ein Spieler mit diesem Namen existiert bereits.'}), 409

    player = Player(name=name)
    db.session.add(player)
    write_audit_log('player_add', 'Player', player.id, f'Quick-added player: {player.name}')
    db.session.commit()

    return jsonify({'name': player.name}), 201


@bp.route('/quick-add-deck', methods=['POST'])
@role_required('admin')
@login_required
def quick_add_deck():
    """Add a new deck via AJAX. Returns deck info on success."""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400

    name = (data.get('name') or '').strip()
    commander = (data.get('commander') or '').strip()
    player_name = (data.get('player') or '').strip()
    color_identity = (data.get('color_identity') or '').strip()
    partner = (data.get('partner') or '').strip() or None
    cedh = bool(data.get('cedh', False))

    # Validate required fields
    if not name:
        return jsonify({'error': 'Name is required'}), 400
    if not commander:
        return jsonify({'error': 'Commander is required'}), 400
    if not player_name:
        return jsonify({'error': 'Player is required'}), 400
    if not color_identity:
        return jsonify({'error': 'Color Identity is required'}), 400

    # Check deck name uniqueness
    existing_deck = db.session.scalar(sa.select(Deck).where(Deck.name == name))
    if existing_deck:
        return jsonify({'error': 'Es gibt schon ein Deck mit diesem Namen.'}), 409

    # Validate commander exists in card database
    card = db.session.scalar(sa.select(Card).where(Card.name == commander))
    if not card:
        return jsonify({'error': 'Der Commander existiert nicht in der Datenbank.'}), 400

    # Validate player exists
    player = db.session.scalar(sa.select(Player).where(Player.name == player_name))
    if not player:
        return jsonify({'error': 'Spieler existiert nicht.'}), 400

    # Validate color identity exists
    ci = db.session.scalar(sa.select(ColorIdentity).where(ColorIdentity.name == color_identity))
    if not ci:
        return jsonify({'error': 'Color Identity existiert nicht.'}), 400

    # Get commander image from front face
    front_face = next((f for f in card.faces if f.face_index == 0), None)
    img = front_face.image_uri if front_face else None

    deck = Deck(
        name=name,
        commander=commander,
        player_id=player.id,
        color_identity=color_identity,
        partner=partner,
        image_uri=img,
        cedh=cedh,
        version=1,
        patch=0,
        change=0,
        last_rework=func.current_date(),
        last_patch=func.current_date(),
        last_change=func.current_date()
    )
    db.session.add(deck)
    write_audit_log('deck_add', 'Deck', deck.id, f'Quick-added deck: {deck.name} ({deck.commander}) for {player_name}')
    db.session.commit()

    return jsonify({
        'name': deck.name,
        'commander': deck.commander,
        'player': player_name
    }), 201


@bp.route('/deck-participant-averages/<deckname>')
@role_required('admin')
@login_required
def deck_participant_averages(deckname):
    """Return participant averages for a deck, optionally filtered by a 'since' date."""
    from app.models import Deck, Participant, Game
    import statistics

    deck = Deck.query.filter_by(name=deckname).first()
    if not deck:
        return jsonify({'error': 'Deck not found'}), 404

    since = request.args.get('since')  # ISO date string e.g. '2024-06-01'

    # Query participants for this deck and player
    query = (
        sa.select(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.player_id == deck.player_id)
        .where(Participant.deck_id == deck.id)
    )

    if since:
        from datetime import date as date_type
        try:
            since_date = date_type.fromisoformat(since)
            query = query.where(Game.date >= since_date)
        except ValueError:
            pass

    participants = db.session.scalars(query).all()

    if not participants:
        return jsonify({'empty': True, 'message': 'No games found for this filter'})

    # Also need games lookup for win/loss analysis
    game_ids = [p.game_id for p in participants]
    games = {g.id: g for g in Game.query.filter(Game.id.in_(game_ids)).all()}

    # Calculate averages
    fields = ["mulligans", "landdrops", "enough_mana", "enough_gas", "deckplan", "unanswered_threats", "fun_moments", "lands"]
    percent_fields = {"enough_mana", "enough_gas", "deckplan", "unanswered_threats", "fun_moments"}
    result = {}

    for f in fields:
        numeric_values = []
        for p in participants:
            raw = getattr(p, f, None)
            if raw is None:
                continue
            try:
                num = float(raw)
            except (TypeError, ValueError):
                continue
            if (f == "lands" or f == "landdrops") and num == -1:
                continue
            numeric_values.append(num)

        if not numeric_values:
            result[f] = "–"
            continue

        if f in percent_fields:
            result[f] = f"{round(statistics.mean(numeric_values) * 100, 1)}% ({len(numeric_values)})"
        else:
            result[f] = f"{round(statistics.mean(numeric_values), 2)} ({len(numeric_values)})"

    # Lockout loss without answer (only losses)
    loss_values = []
    for p in participants:
        game_obj = games.get(p.game_id)
        if not game_obj or game_obj.winner_id == deck.player_id:
            continue
        raw = getattr(p, "loss_without_answer", None)
        if raw is None:
            continue
        try:
            loss_values.append(float(raw))
        except (TypeError, ValueError):
            continue
    result["lockout_loss_without_answer"] = f"{round(statistics.mean(loss_values) * 100, 1)}% ({len(loss_values)})" if loss_values else "–"

    # Selbsterspielter sieg (only wins)
    win_values = []
    for p in participants:
        game_obj = games.get(p.game_id)
        if not game_obj or game_obj.winner_id != deck.player_id:
            continue
        raw = getattr(p, "selfmade_win", None)
        if raw is None:
            continue
        try:
            win_values.append(float(raw))
        except (TypeError, ValueError):
            continue
    result["selbsterspielter_sieg"] = f"{round(statistics.mean(win_values) * 100, 1)}% ({len(win_values)})" if win_values else "–"

    # All landdrops (-1 percentage)
    all_landdrops_count = 0
    total_landdrops_filled = 0
    for p in participants:
        raw = getattr(p, "landdrops", None)
        if raw is None:
            continue
        try:
            num = float(raw)
            total_landdrops_filled += 1
            if num == -1:
                all_landdrops_count += 1
        except (TypeError, ValueError):
            continue
    result["all_landdrops"] = f"{round((all_landdrops_count / total_landdrops_filled) * 100, 1)}% ({all_landdrops_count})" if total_landdrops_filled else "–"

    result['empty'] = False
    result['games_count'] = len(participants)

    return jsonify(result)


@bp.route('/deck-performance/<deckname>')
@login_required
def deck_performance(deckname):
    """Return deck performance stats (games, wins, winrate, turn stats, pod size breakdown), optionally filtered by a 'since' date."""
    from collections import defaultdict
    from app.models import Deck, Participant, Game
    from app.services.elo_service import DECK_OWNER_OVERRIDE_PLAYER_ID
    from app.services.stats_service import compute_deck_performance

    deck = Deck.query.filter_by(name=deckname).first()
    if not deck:
        return jsonify({'error': 'Deck not found'}), 404

    since = request.args.get('since')

    # Shared/community "precon" decks (owner == DECK_OWNER_OVERRIDE_PLAYER_ID)
    # count every game the deck appears in regardless of pilot; normal decks
    # count only games their owner piloted. Win attribution (handled inside
    # compute_deck_performance via the per-game pilot) is correct either way.
    is_shared_deck = (deck.player_id == DECK_OWNER_OVERRIDE_PLAYER_ID)
    query = (
        sa.select(Participant)
        .join(Game, Game.id == Participant.game_id)
        .where(Participant.deck_id == deck.id)
    )
    if not is_shared_deck:
        query = query.where(Participant.player_id == deck.player_id)

    if since:
        from datetime import date as date_type
        try:
            since_date = date_type.fromisoformat(since)
            query = query.where(Game.date >= since_date)
        except ValueError:
            pass

    participants = db.session.scalars(query).all()

    if not participants:
        return jsonify({'empty': True, 'message': 'No games found for this filter'})

    game_ids = [p.game_id for p in participants]
    games = {g.id: g for g in Game.query.filter(Game.id.in_(game_ids)).all()}

    all_participants_in_games = Participant.query.filter(Participant.game_id.in_(game_ids)).all()
    participants_by_game = defaultdict(list)
    for p in all_participants_in_games:
        participants_by_game[p.game_id].append(p)

    # Delegate to the shared (override-safe) computation so this filter endpoint
    # and the server-rendered page can never diverge.
    result = compute_deck_performance(deck, participants, games, participants_by_game)
    result['empty'] = False
    return jsonify(result)


@bp.route('/data/years')
@login_required
def data_years():
    """Return a list of distinct years that have game data."""
    return jsonify(queries.get_game_years(db.session))


@bp.route('/data/<int:year>')
@login_required
def data_by_year(year):
    """Return player stats for a specific calendar year."""
    results = queries.get_player_stats_by_year(db.session, year)
    return jsonify([format_player_stats(r) for r in results])


@bp.route('/cards/autocomplete')
@login_required
def cards_autocomplete():
    q = request.args.get('q', '')
    if len(q) < 2:
        return jsonify([])
    results = db.session.execute(
        sa.select(sa.distinct(Card.name))
        .where(Card.name.ilike(f'%{q}%'))
        .order_by(Card.name)
        .limit(10)
    ).scalars().all()
    return jsonify(results)
