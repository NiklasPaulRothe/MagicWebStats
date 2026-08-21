import logging
from collections import defaultdict

from flask import render_template, flash, redirect, url_for, request, abort
from flask_login import login_required, current_user
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from app import db, models
from app.auth import role_required
from app.decks import bp
from app.decks.forms import DeckEditForm
from app.models import Deck, Player, User, Game, Participant
from app.services.audit import write_audit_log
from app.services.deck_service import (
    version_change, version_patch, version_rework,
    archive_deck, dearchive_deck, update_decklist,
    build_game_history,
)
from app.services.elo_service import recalculate_all_elo
from app.services.stats_service import compute_participant_averages, compute_deck_performance

# --- CSRF Audit (Requirement 16.1) ---
# All POST endpoints in this module are protected by Flask-WTF CSRFProtect (init'd in app/__init__.py).
# - deck_edit: WTForms (auto CSRF token)
# - set_commander_image: HTML form POST (CSRFProtect validates hidden token)
# - set_achievement_progress: JSON API (CSRF via X-CSRFToken header from JS)
# - delete_achievement: JSON API (CSRF via X-CSRFToken header from JS)
# - add_achievement: JSON/form (CSRF via X-CSRFToken header or form hidden token)
# - dearchive: HTML form POST (CSRFProtect validates hidden token)
# No exemptions are needed.
# ---


@bp.route('/edit/<deckname>', methods=['GET', 'POST'])
@login_required
def deck_edit(deckname):
    deck = db.session.execute(sa.select(Deck).where(Deck.name == deckname)).scalar_one()
    user = db.session.execute(sa.select(User).where(User.username == current_user.username)).scalar_one()
    owner = db.session.execute(sa.select(Player).where(Player.id == user.player_id)).scalar_one()
    if deck.player_id != owner.id:
        flash('Du bist nicht berechtigt dieses Deck zu bearbeiten')
        return redirect(url_for('main.index'))

    form = DeckEditForm()

    deckname = deckname + " (" + deck.commander + ")"

    # Handle version updates without full form validation
    if request.method == 'POST':
        if form.archive_button.data:
            archive_deck(deck)
            write_audit_log('deck_archive', 'Deck', deck.id, f'Archived deck: {deck.name}')
            db.session.commit()
            flash(f'Deck "{deck.name}" wurde archiviert')
            return redirect(url_for('main.user', spieler=current_user.username))

        elif form.version_changed.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_change(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version change: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return redirect(url_for('main.user', spieler=current_user.username))

        elif form.version_patched.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_patch(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version patch: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return redirect(url_for('main.user', spieler=current_user.username))

        elif form.version_reworked.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_rework(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version rework: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return redirect(url_for('main.user', spieler=current_user.username))

    if not form.validate_on_submit():
        logger.debug("Form validation errors: %s", form.errors)

    if form.validate_on_submit():
            deck.name = form.name.data
            if (form.decklist.data != ""):
                try:
                    update_decklist(deck, form.decklist.data)
                except Exception:
                    flash('Karten für dieses Deck konnten nicht korrekt geladen werden.')
            write_audit_log('deck_edit', 'Deck', deck.id, f'Edited deck: {deck.name}')
            db.session.commit()
            return redirect(url_for('main.user', spieler=current_user.username))

    form.name.default = deck.name
    form.decklist.default = deck.decklist
    form.current_name.default = deck.name
    form.process()

    current_version = f"{deck.version}.{deck.patch}.{deck.change}"

    return render_template('decks/edit.html', form=form, deckname=deckname, current_version=current_version)

@bp.route('/choose_image/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def choose_commander_image(deckname):
    deck = db.session.execute(sa.select(models.Deck).where(models.Deck.name == deckname)).scalar_one_or_none()
    if not deck:
        flash("Deck not found", "error")
        return redirect(url_for('main.index'))

    # Query the new cards table, get front face images
    cards = db.session.scalars(sa.select(models.Card).where(models.Card.name == deck.commander)).all()
    images = []
    for card in cards:
        front_face = next((f for f in card.faces if f.face_index == 0), None)
        if front_face and front_face.image_uri:
            images.append(front_face.image_uri)

    return render_template('decks/choose_image.html', deckname=deckname, commander=deck.commander, images=images)

@bp.route('/set_commander_image/<deckname>', methods=['POST'])
@login_required
def set_commander_image(deckname):
    image_uri = request.form.get('image_uri')
    deck = db.session.execute(sa.select(models.Deck).where(models.Deck.name == deckname)).scalar_one_or_none()

    if not deck or not image_uri:
        flash("Fehler beim Aktualisieren des Bildes", "error")
        return redirect(url_for('decks.deck_show', deckname=deckname))
    deck.image_uri = image_uri
    db.session.commit()

    flash("Commander-Bild aktualisiert!", "success")
    return redirect(url_for('decks.deck_show', deckname=deckname))


@bp.route('/version-history/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def version_history(deckname):
    deck = db.first_or_404(sa.select(models.Deck).where(models.Deck.name == deckname))

    # Get all version history entries for this deck, ordered by timestamp descending
    history = db.session.scalars(
        sa.select(models.DeckVersionHistory)
        .where(models.DeckVersionHistory.deck_id == deck.id)
        .order_by(models.DeckVersionHistory.timestamp.desc())
    ).all()

    return render_template(
        'decks/version_history.html',
        deckname=deck.name,
        history=history
    )

@bp.route('/show/<deckname>', methods=['GET'], strict_slashes=False)
@login_required
def deck_show(deckname):
    deck = db.first_or_404(sa.select(models.Deck).where(models.Deck.name == deckname))
    user = db.session.execute(sa.select(models.User).where(models.User.username == current_user.username)).scalar_one()
    is_owner = (deck.player_id == user.player_id)

    participants = db.session.scalars(
        sa.select(models.Participant)
        .where(models.Participant.player_id == deck.player_id, models.Participant.deck_id == deck.id)
        .order_by(models.Participant.game_id.desc())
    ).all()

    game_ids = [p.game_id for p in participants]
    games = {}
    participants_by_game = defaultdict(list)
    players, decks = {}, {}

    if game_ids:
        games = {g.id: g for g in db.session.scalars(
            sa.select(models.Game).where(models.Game.id.in_(game_ids))
        ).all()}
        all_participants = db.session.scalars(
            sa.select(models.Participant).where(models.Participant.game_id.in_(game_ids))
        ).all()

        player_ids = {p.player_id for p in all_participants}
        deck_ids = {p.deck_id for p in all_participants}

        players = {p.id: p for p in db.session.scalars(
            sa.select(models.Player).where(models.Player.id.in_(player_ids))
        ).all()}
        decks = {d.id: d for d in db.session.scalars(
            sa.select(models.Deck).where(models.Deck.id.in_(deck_ids))
        ).all()}

        for p in all_participants:
            participants_by_game[p.game_id].append(p)

    try:
        row = build_game_history(deck, participants, games, participants_by_game, players, decks)
    except Exception:
        logger.exception("Failed to build game history for deck %s", deckname)
        db.session.rollback()
        row = []
        flash("Ein Fehler ist aufgetreten beim Laden der Spielhistorie.")

    # === Deck performance stats via stats_service ===
    try:
        deck_performance = compute_deck_performance(deck, participants, games, participants_by_game)
    except Exception:
        logger.exception("Failed to compute deck performance for deck %s", deckname)
        db.session.rollback()
        deck_performance = {
            'games': 0, 'wins': 0, 'winrate': "\u2013",
            'last_played': None, 'avg_turns': "\u2013",
            'median_turns': "\u2013", 'min_turns': "\u2013",
            'max_turns': "\u2013", 'avg_participants': "\u2013",
            'by_size': {},
        }

    deck_stats = {
        "games": deck_performance['games'],
        "wins": deck_performance['wins'],
        "winrate": deck_performance['winrate'],
        "last_played": deck_performance['last_played'],
        "avg_turns": deck_performance['avg_turns'],
        "median_turns": deck_performance['median_turns'],
        "min_turns": deck_performance['min_turns'],
        "max_turns": deck_performance['max_turns'],
        "avg_participants": deck_performance['avg_participants'],
    }

    deck_stats_by_size = {}
    for size in (3, 4, 5):
        size_data = deck_performance['by_size'].get(str(size), {})
        deck_stats_by_size[size] = {
            "games": size_data.get('games', 0),
            "wins": size_data.get('wins', 0),
            "winrate": size_data.get('winrate', "\u2013"),
            "avg_turns": size_data.get('avg_turns', "\u2013"),
            "median_turns": size_data.get('median_turns', "\u2013"),
        }

    # Load achievements for this deck (non-functional checkboxes for now)
    achievements = db.session.scalars(
        sa.select(models.Achievement).where(models.Achievement.deck_id == deck.id)
    ).all()

    # === Participant field averages (strictly for Player 1 and User ID 1) ===
    show_private_avgs = (deck.player_id == 1 and getattr(current_user, "id", None) == 1)
    participant_avgs = {}
    if show_private_avgs and participants:
        participant_avgs = compute_participant_averages(deck, participants, games)

    # === Private comments (Player 1 owner and User ID 1) ===
    show_private_comments = (deck.player_id == 1 and getattr(current_user, "id", None) == 1)
    private_comments = []
    if show_private_comments and participants:
        last_rework_date = getattr(deck, "last_patch")
        for p in participants:
            text = getattr(p, "comments", None)
            if not text:
                continue
            game_obj = games.get(p.game_id)
            if not game_obj:
                continue
            if game_obj.date < last_rework_date:
                continue
            private_comments.append({
                "game_id": p.game_id,
                "date": game_obj.date.strftime("%Y-%m-%d") if getattr(game_obj, "date", None) else "",
                "text": text
            })
        # Sort newest first
        private_comments.sort(key=lambda x: x["date"], reverse=True)

    return render_template(
        'decks/show.html',
        deckname=deck.name,
        deck_version=f"{deck.version}.{deck.patch}.{deck.change}",
        commander=deck.image_uri or "/static/img/default_commander.png",
        games=row,
        deck_stats=deck_stats,
        deck_stats_by_size=deck_stats_by_size,
        is_owner=is_owner,
        achievements=achievements,
        show_private_avgs=show_private_avgs,
        participant_avgs=participant_avgs,
        show_private_comments=show_private_comments,
        private_comments=private_comments,
        last_rework_date=deck.last_rework.isoformat() if deck.last_rework else None,
        last_patch_date=deck.last_patch.isoformat() if deck.last_patch else None
    )


@bp.route('/achievements/<int:achievement_id>/set', methods=['POST'])
@login_required
def set_achievement_progress(achievement_id):
    from flask import request, jsonify

    ach = db.get_or_404(models.Achievement, achievement_id)

    # Read desired value from JSON
    payload = request.get_json(silent=True) or {}
    try:
        desired = int(payload.get('achieved', 0))
    except (TypeError, ValueError):
        desired = ach.achieved or 0

    # Clamp to [0, anzahl]
    max_allowed = ach.amount or 0
    desired = max(0, min(desired, max_allowed))

    # Only write if changed
    if (ach.achieved or 0) != desired:
        ach.achieved = desired
        db.session.commit()

    return jsonify({
        "ok": True,
        "achievement_id": ach.id,
        "achieved": ach.achieved or 0,
        "max": max_allowed
    })

@bp.route('/achievements/<int:achievement_id>/delete', methods=['POST'])
@login_required
def delete_achievement(achievement_id):
    from flask import jsonify

    ach = db.get_or_404(models.Achievement, achievement_id)

    # Only the deck owner may delete an achievement
    deck = db.get_or_404(models.Deck, ach.deck_id)
    user = db.session.execute(sa.select(models.User).where(models.User.username == current_user.username)).scalar_one()
    if deck.player_id != user.player_id:
        return jsonify({"ok": False, "message": "Nicht berechtigt."}), 403

    db.session.delete(ach)
    db.session.commit()

    return jsonify({"ok": True, "deleted_id": achievement_id})


@bp.route('/achievements/add', methods=['POST'])
@login_required
def add_achievement():
    from flask import request, jsonify

    # Accept both JSON and form submissions to improve robustness
    if request.is_json:
        data = request.get_json(silent=True) or {}
        deckname = (data.get('deckname') or '').strip()
        titel = (data.get('titel') or '').strip()
        beschreibung = (data.get('beschreibung') or '').strip()
        anzahl = data.get('anzahl')
    else:
        form = request.form or {}
        deckname = (form.get('deckname') or '').strip()
        titel = (form.get('titel') or '').strip()
        beschreibung = (form.get('beschreibung') or '').strip()
        anzahl = form.get('anzahl')

    if not deckname or not titel:
        return jsonify({"ok": False, "message": "Deckname und Titel sind erforderlich."}), 400

    try:
        anzahl = int(anzahl)
    except (TypeError, ValueError):
        anzahl = 1
    if anzahl < 1:
        anzahl = 1

    deck = db.first_or_404(sa.select(models.Deck).where(models.Deck.name == deckname))

    ach = models.Achievement(
        title=titel,
        description=beschreibung,
        amount=anzahl,
        achieved=0,
        deck_id=deck.id
    )
    db.session.add(ach)
    db.session.commit()

    return jsonify({
        "ok": True,
        "achievement": {
            "id": ach.id,
            "title": ach.title,
            "description": ach.description,
            "amount": ach.amount,
            "achieved": ach.achieved
        }
    }), 201


@bp.route('/archive/<player_name>', methods=['GET'])
@login_required
def deck_archive(player_name):
    player = db.first_or_404(sa.select(Player).where(Player.name == player_name))
    is_owner = (current_user.player_id == player.id)
    is_admin = (current_user.role == 'admin')
    return render_template(
        'decks/archive.html',
        spieler=player,
        player_name=player_name,
        is_owner=is_owner,
        is_admin=is_admin
    )


@bp.route('/dearchive/<int:deck_id>', methods=['POST'])
@login_required
def dearchive(deck_id):
    deck = db.get_or_404(Deck, deck_id)
    player_name = request.form.get('player_name')
    if deck.player_id != current_user.player_id and current_user.role != 'admin':
        abort(403)
    dearchive_deck(deck)
    db.session.commit()
    return redirect(url_for('decks.deck_archive', player_name=player_name))


@bp.route('/elo', methods=['GET'])
@role_required('admin')
@login_required
def calculate_elo():
    # Fetch all data needed for Elo recalculation
    decks = db.session.scalars(sa.select(Deck)).all()
    games = db.session.scalars(sa.select(Game)).all()

    # Build participants_by_game lookup
    all_participants = db.session.scalars(sa.select(Participant)).all()
    participants_by_game = defaultdict(list)
    for p in all_participants:
        participants_by_game[p.game_id].append(p)

    # Delegate to elo_service
    results = recalculate_all_elo(decks, games, dict(participants_by_game))

    # Persist the results
    for result in results:
        deck = db.session.get(Deck, result.deck_id)
        if result.games_played >= 5:
            deck.elo_rating = result.new_rating
        else:
            deck.elo_rating = 0
        db.session.add(deck)

    db.session.commit()
    return redirect(url_for('main.index'), code=302)
