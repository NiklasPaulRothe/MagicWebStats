import logging
from collections import defaultdict

from flask import render_template, flash, redirect, url_for, request, abort, jsonify
from flask_login import login_required, current_user
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from app import db, models
from app.auth import role_required
from app.decks import bp
from app.decks.forms import DeckEditForm
from app.models import Deck, Player, User, Game, Participant, DeckFolder
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
# - create_folder: JSON API (CSRF via X-CSRFToken header from JS)
# - move_deck_to_folder: JSON API (CSRF via X-CSRFToken header from JS)
# - set_component_collection: JSON API (CSRF via X-CSRFToken header from JS)
# - reload_deck: JSON API (CSRF via X-CSRFToken header from JS)
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

    # Where to go after a successful edit/version action. When the edit modal
    # on the deck overview submits, it sends next=overview so the user returns
    # to the overview instead of the My Decks list. Defaults to My Decks (the
    # standalone edit page's original behavior).
    def _after_edit_redirect():
        if (request.form.get('next') or '').strip() == 'overview':
            return redirect(url_for('decks.deck_overview', deck_id=deck.id))
        return redirect(url_for('main.user', identifier=current_user.player_id))

    # Handle version updates without full form validation
    if request.method == 'POST':
        if form.archive_button.data:
            archive_deck(deck)
            write_audit_log('deck_archive', 'Deck', deck.id, f'Archived deck: {deck.name}')
            db.session.commit()
            flash(f'Deck "{deck.name}" wurde archiviert')
            # Archive always returns to My Decks — the deck has left the active
            # list, so the overview would 404/no longer be the right place.
            return redirect(url_for('main.user', identifier=current_user.player_id))

        elif form.version_changed.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_change(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version change: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return _after_edit_redirect()

        elif form.version_patched.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_patch(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version patch: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return _after_edit_redirect()

        elif form.version_reworked.data:
            comment = form.version_comment.data.strip() if form.version_comment.data else None
            new_version = version_rework(deck, comment)
            write_audit_log('deck_version', 'Deck', deck.id, f'Version rework: {deck.name} → {new_version}')
            db.session.commit()
            flash(f'Deck version updated to {new_version}')
            return _after_edit_redirect()

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
            return _after_edit_redirect()

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
            deck.elo_rating = round(result.new_rating)
        else:
            deck.elo_rating = 0
        db.session.add(deck)

    db.session.commit()
    return redirect(url_for('main.index'), code=302)


# --- Archidekt-style deck overview (link-only, no auth) ---
#
# This page is intentionally NOT @login_required: it is reachable by anyone who
# holds the deck link (the deck id acts as the shareable handle for now; a
# dedicated share-token can replace it later without changing the template).
# It renders the deck's cards as image stacks grouped by card type, mirroring
# the Archidekt deck view.

# Display order of type groups. A card is placed in the first bucket whose
# keyword appears in its Scryfall type_line. "Land" is checked early so e.g.
# "Artifact Land" lands in Land. The Commander column (see below) is emitted
# before all of these.
_TYPE_GROUP_ORDER = [
    ('Artifact', 'Artifact'),
    ('Creature', 'Creature'),
    ('Planeswalker', 'Planeswalker'),
    ('Battle', 'Battle'),
    ('Enchantment', 'Enchantment'),
    ('Sorcery', 'Sorcery'),
    ('Instant', 'Instant'),
    ('Land', 'Land'),
]
_COMMANDER_GROUP = 'Commander'
_OTHER_GROUP = 'Other'
_UNCATEGORIZED_GROUP = 'Uncategorized'


def _name_keys(name):
    """Return the set of comparable keys for a card name.

    Double-faced cards use the Scryfall "Front // Back" format, but a deck's
    commander field and a DeckComponent may each store either the full name or
    just the front-face name (e.g. "Etali, Primal Conqueror //
    Etali, Primal Sickness" vs. "Etali, Primal Conqueror"). We key on the full
    normalized name plus each face so a match succeeds regardless of which form
    either side stored.
    """
    if not name:
        return set()
    full = name.strip().lower()
    keys = {full}
    if '//' in full:
        keys.update(part.strip() for part in full.split('//') if part.strip())
    return keys


# Classification priority for cards that carry more than one type. A card is
# placed in the FIRST bucket here whose keyword is in its type_line. This is a
# separate concern from the column DISPLAY order (_TYPE_GROUP_ORDER): e.g. an
# "Artifact Creature" is classified as Creature, a "Land Creature" (Dryad
# Arbor) as Creature, an "Artifact Land" as Land. The user-specified hierarchy
# is Creature > Land > Planeswalker > Artifact > Enchantment; the remaining
# single-type buckets (Battle, Sorcery, Instant) follow for completeness.
_TYPE_PRIORITY = [
    ('Creature', 'Creature'),
    ('Land', 'Land'),
    ('Planeswalker', 'Planeswalker'),
    ('Battle', 'Battle'),
    ('Artifact', 'Artifact'),
    ('Enchantment', 'Enchantment'),
    ('Sorcery', 'Sorcery'),
    ('Instant', 'Instant'),
]


def _classify_type(type_line):
    """Map a Scryfall type_line to one group label using the type hierarchy.

    When a card has multiple types, the highest-priority type wins
    (Creature > Land > Planeswalker > Artifact > Enchantment, then
    Battle/Sorcery/Instant).
    """
    tl = (type_line or '')
    for keyword, label in _TYPE_PRIORITY:
        if keyword in tl:
            return label
    return _OTHER_GROUP


# "By collection" group headings and their fixed display order. Shared by the
# full overview and the collection-board fragment endpoint so both render the
# same grouping.
_COLLECTION_LABELS = {
    'in_deck_ok': 'In deck',
    'in_deck_faulty': 'In deck (not enough copies)',
    'proxy': 'Proxy',
    'available': 'Available',
    'owned_no_copy': 'Owned (no free copy)',
    'owned_other': 'Owned (other printing)',
    'not_owned': 'Not owned',
}
_COLLECTION_ORDER = [
    'in_deck_ok', 'in_deck_faulty', 'available', 'owned_no_copy',
    'owned_other', 'proxy', 'not_owned',
]


def _collection_entry(comp, card, deck):
    """Build the minimal card entry dict the collection board renders."""
    image_uri = None
    if card:
        front_face = next((f for f in card.faces if f.face_index == 0), None)
        if front_face and front_face.image_uri:
            image_uri = front_face.image_uri
    card_name = comp.name or (card.name if card else 'Unknown')
    # Keep commander art in sync with the deck stats page choice.
    if deck.image_uri:
        keys = _name_keys(card_name) | (_name_keys(card.name) if card else set())
        cmdr_keys = _name_keys(deck.commander) | _name_keys(deck.partner)
        if keys & cmdr_keys:
            image_uri = deck.image_uri
    return {
        'id': comp.card_id,
        'component_id': comp.id,
        'name': card_name,
        'image': image_uri,
        'count': comp.count or 1,
        'physical_status': comp.physical_status,
        'physical_finish': comp.physical_finish,
        'physical_language': comp.physical_language,
        'collection_status': None,
    }


def build_collection_card_groups(deck, viewer_player_id):
    """Build the "By collection" board groups for a deck and viewer.

    Returns a list of group dicts ({label, status, cards, card_count}) in the
    fixed status order, or None when no viewer player is linked. This is the
    single source of truth for the collection grouping — used by both the full
    overview and the fragment endpoint so a swapped-in board is identical to a
    freshly loaded one.
    """
    if viewer_player_id is None:
        return None

    from app.services.collection_service import compute_deck_collection_status

    components = db.session.scalars(
        sa.select(models.DeckComponent).where(
            models.DeckComponent.deck_id == deck.id,
            models.DeckComponent.in_deck.is_(True),
        )
    ).all()
    card_ids = [c.card_id for c in components if c.card_id]
    cards_by_id = {}
    if card_ids:
        cards_by_id = {
            c.id: c for c in db.session.scalars(
                sa.select(models.Card).where(models.Card.id.in_(card_ids))
            ).all()
        }

    statuses = compute_deck_collection_status(viewer_player_id, deck.id)

    coll_groups = defaultdict(list)
    for comp in components:
        entry = _collection_entry(comp, cards_by_id.get(comp.card_id), deck)
        info = statuses.get(comp.id)
        entry['collection_status'] = info['status'] if info else 'not_owned'
        coll_groups[entry['collection_status']].append(entry)

    groups = []
    for key in _COLLECTION_ORDER:
        cards = coll_groups.get(key)
        if not cards:
            continue
        cards = sorted(cards, key=lambda c: c['name'].lower())
        groups.append({
            'label': _COLLECTION_LABELS[key],
            'status': key,
            'cards': cards,
            'card_count': sum(c['count'] for c in cards),
        })
    return groups


@bp.route('/overview/<int:deck_id>', methods=['GET'], strict_slashes=False)
def deck_overview(deck_id):
    """Public, link-only overview of a deck's cards as type-grouped stacks."""
    deck = db.get_or_404(models.Deck, deck_id)

    # Only cards that are actually part of the deck (excludes Maybeboard /
    # "Considered" / sideboard rows imported with in_deck = False).
    components = db.session.scalars(
        sa.select(models.DeckComponent).where(
            models.DeckComponent.deck_id == deck.id,
            models.DeckComponent.in_deck.is_(True),
        )
    ).all()

    # Resolve the cards referenced by the components in one query, then index
    # them so we can attach type_line + front-face image to each component.
    card_ids = [c.card_id for c in components if c.card_id]
    cards_by_id = {}
    if card_ids:
        cards_by_id = {
            card.id: card
            for card in db.session.scalars(
                sa.select(models.Card).where(models.Card.id.in_(card_ids))
            ).all()
        }

    # Commander name key(s) for this deck, used to split commanders into their
    # own leftmost column. Keys include each face of a double-faced name so
    # matching works whether the full "Front // Back" name or just a face is
    # stored on either side.
    commander_keys = set()
    for n in (deck.commander, deck.partner):
        commander_keys |= _name_keys(n)

    # Build a card entry per component, and record which type label and which
    # category label it belongs to, so we can produce two groupings (by type
    # and by category) from the same entries.
    type_groups = defaultdict(list)
    category_groups = defaultdict(list)
    all_entries = []  # flat list, reused for the ownership (collection) view
    for comp in components:
        card = cards_by_id.get(comp.card_id)
        type_line = card.type_line if card else None

        image_uri = None
        if card:
            front_face = next((f for f in card.faces if f.face_index == 0), None)
            if front_face and front_face.image_uri:
                image_uri = front_face.image_uri

        card_name = comp.name or (card.name if card else 'Unknown')

        # A card matching the deck's commander/partner goes to the Commander
        # column in BOTH views; everything else is grouped by type / category.
        card_keys = _name_keys(card_name)
        if card is not None:
            card_keys |= _name_keys(card.name)
        is_commander = bool(card_keys & commander_keys)
        if is_commander and deck.image_uri:
            # Keep commander art in sync with the deck stats page choice.
            image_uri = deck.image_uri

        entry = {
            'id': comp.card_id,
            'component_id': comp.id,
            'name': card_name,
            'image': image_uri,
            'count': comp.count or 1,
            'type_line': type_line or '',
            'physical_status': comp.physical_status,
            'physical_finish': comp.physical_finish,
            'physical_language': comp.physical_language,
            # Filled in below for an owner viewer; None otherwise.
            'collection_status': None,
        }
        all_entries.append(entry)

        # By-type grouping.
        type_label = _COMMANDER_GROUP if is_commander else _classify_type(type_line)
        type_groups[type_label].append(entry)

        # By-category grouping (main category only for now; falls back when a
        # card has no category, e.g. Moxfield imports).
        category_label = _COMMANDER_GROUP if is_commander else (
            comp.primary_category or _UNCATEGORIZED_GROUP
        )
        category_groups[category_label].append(entry)

    def _emit(groups_map, ordered_labels):
        """Turn a label->entries map into an ordered list of group dicts."""
        seen = set()
        out = []
        for label in ordered_labels:
            if label in seen:
                continue
            seen.add(label)
            cards = groups_map.get(label)
            if not cards:
                continue
            cards = sorted(cards, key=lambda c: c['name'].lower())
            out.append({
                'label': label,
                'cards': cards,
                'card_count': sum(c['count'] for c in cards),
            })
        return out

    # Type view: Commander first, then the fixed type order, then Other.
    type_order = (
        [_COMMANDER_GROUP]
        + [label for _, label in _TYPE_GROUP_ORDER]
        + [_OTHER_GROUP]
    )
    card_groups = _emit(type_groups, type_order)

    # Category view: Commander first, then remaining categories alphabetically,
    # with Uncategorized last.
    other_categories = sorted(
        label for label in category_groups
        if label not in (_COMMANDER_GROUP, _UNCATEGORIZED_GROUP)
    )
    category_order = [_COMMANDER_GROUP] + other_categories + [_UNCATEGORIZED_GROUP]
    category_card_groups = _emit(category_groups, category_order)

    total_cards = sum(g['card_count'] for g in card_groups)

    # Collection tracking: for a logged-in viewer linked to a player, resolve
    # each in-deck card's collection status (in_deck_ok / in_deck_faulty /
    # proxy / available / owned_no_copy / owned_other / not_owned) and attach it
    # to the entries (which are shared across all groupings). Only the deck's
    # OWNER sees the editable marker; any linked viewer sees their own status.
    ownership_card_groups = None
    viewer_player_id = getattr(current_user, 'player_id', None) if current_user.is_authenticated else None
    is_owner = viewer_player_id is not None and viewer_player_id == deck.player_id
    finish_options = []
    language_options = []
    if viewer_player_id is not None:
        from app.services.collection_service import compute_deck_collection_status

        # Attach status to the shared entries so the type/category boards' own
        # markers show it too.
        statuses = compute_deck_collection_status(viewer_player_id, deck.id)
        for entry in all_entries:
            info = statuses.get(entry['component_id'])
            entry['collection_status'] = info['status'] if info else 'not_owned'

        # The "By collection" board comes from the shared builder (same code the
        # fragment endpoint uses) so a freshly loaded board and a swapped-in one
        # are identical.
        ownership_card_groups = build_collection_card_groups(deck, viewer_player_id)

        # Dropdown options for the owner's collection editor: the exact finish
        # and language tokens present in their collection (plus Normal/EN).
        if is_owner:
            from app.services.collection_service import (
                get_collection_finish_language_options,
            )
            opts = get_collection_finish_language_options(viewer_player_id)
            finish_options = opts['finishes']
            language_options = opts['languages']

    # Edit-deck modal (owner only): a prefilled DeckEditForm + the current
    # version string, so the modal shows the same options as the standalone
    # edit page without a separate GET.
    edit_form = None
    deck_version = f"{deck.version}.{deck.patch}.{deck.change}"
    deck_has_source = bool(deck.decksite and deck.archidekt_id)
    if is_owner:
        edit_form = DeckEditForm()
        edit_form.name.default = deck.name
        edit_form.decklist.default = deck.decklist
        edit_form.current_name.default = deck.name
        edit_form.process()

    return render_template(
        'decks/overview.html',
        deck_id=deck.id,
        deckname=deck.name,
        commander=deck.commander,
        card_groups=card_groups,
        category_card_groups=category_card_groups,
        ownership_card_groups=ownership_card_groups,
        total_cards=total_cards,
        is_owner=is_owner,
        finish_options=finish_options,
        language_options=language_options,
        edit_form=edit_form,
        deck_version=deck_version,
        deck_has_source=deck_has_source,
    )


# --- Card detail JSON (powers the overview's card popup) ---
# Public, like the overview it serves: returns a card's image(s), faces with
# readable oracle text, and its rulings (by oracle_id). Rulings are empty until
# the nightly fetch populates card_rulings. This is intentionally a small JSON
# endpoint so a lightweight modal can render it now and a full card page can
# reuse the same data later.
@bp.route('/card/<card_id>', methods=['GET'], strict_slashes=False)
def card_detail(card_id):
    from flask import jsonify

    card = db.session.get(models.Card, card_id)
    if card is None:
        return jsonify({'ok': False, 'message': 'Card not found.'}), 404

    faces = [
        {
            'name': face.name,
            'mana_cost': face.mana_cost,
            'type_line': face.type_line,
            'oracle_text': face.oracle_text,
            'image': face.image_uri,
        }
        for face in sorted(card.faces, key=lambda f: f.face_index)
    ]

    # Rulings are shared across printings, so query by oracle_id. Ordered
    # oldest-first (NULL dates last). Empty until the nightly fetch runs.
    rulings = db.session.scalars(
        sa.select(models.Ruling)
        .where(models.Ruling.oracle_id == card.oracle_id)
        .order_by(models.Ruling.published_at.asc().nulls_last())
    ).all()

    rulings_payload = [
        {
            'source': r.source,
            'published_at': r.published_at.isoformat() if r.published_at else None,
            'comment': r.comment,
        }
        for r in rulings
    ]

    return jsonify({
        'ok': True,
        'id': card.id,
        'name': card.name,
        'mana_cost': card.mana_cost,
        'type_line': card.type_line,
        'oracle_text': card.oracle_text,
        'faces': faces,
        'rulings': rulings_payload,
    })


def _front_image(card):
    """Front-face image_uri for a Card, or None."""
    front = next((f for f in card.faces if f.face_index == 0), None)
    return front.image_uri if front else None


# --- Printings for a card, in a deck context (powers the popup's printing
# picker). All printings share the same oracle_id; each Card row is one
# printing. (Names can differ for reversible_card layouts, so we key on
# oracle_id rather than name.) ---
@bp.route('/<int:deck_id>/card/<card_id>/printings', methods=['GET'], strict_slashes=False)
def card_printings(deck_id, card_id):
    from flask import jsonify

    card = db.session.get(models.Card, card_id)
    if card is None:
        return jsonify({'ok': False, 'message': 'Card not found.'}), 404

    # List every printing of this card by oracle_id (shared across all
    # printings), NOT by name: reversible_card printings are stored with a
    # "Front // Back" name (e.g. "Steam Vents // Steam Vents") that differs from
    # the normal printing's name ("Steam Vents"), so a name match would hide
    # them from the picker even though they're the same card.
    printings = db.session.scalars(
        sa.select(models.Card)
        .where(models.Card.oracle_id == card.oracle_id)
        .order_by(models.Card.released_at.asc().nulls_last(), models.Card.set_code.asc())
    ).all()

    payload = [
        {
            'id': p.id,
            'set_code': p.set_code,
            'set_name': p.set_name,
            'image': _front_image(p),
            'current': (p.id == card_id),
        }
        for p in printings
    ]

    return jsonify({
        'ok': True,
        'deck_id': deck_id,
        'card_id': card_id,
        'name': card.name,
        'printings': payload,
    })


# --- Set the printing used for a card in THIS deck only. Updates the matching
# DeckComponent.card_id to the chosen printing. CSRF via X-CSRFToken header. ---
@bp.route('/<int:deck_id>/card/<card_id>/printing', methods=['POST'], strict_slashes=False)
@login_required
def set_card_printing(deck_id, card_id):
    from flask import request, jsonify

    deck = db.get_or_404(models.Deck, deck_id)

    # Only the deck owner may change its printings.
    user = db.session.execute(
        sa.select(models.User).where(models.User.username == current_user.username)
    ).scalar_one()
    if deck.player_id != user.player_id:
        return jsonify({'ok': False, 'message': 'Nicht berechtigt.'}), 403

    payload = request.get_json(silent=True) or {}
    new_card_id = (payload.get('printing_id') or '').strip()
    if not new_card_id:
        return jsonify({'ok': False, 'message': 'printing_id is required.'}), 400

    # The component currently pointing at the old printing in this deck.
    component = db.session.scalar(
        sa.select(models.DeckComponent).where(
            models.DeckComponent.deck_id == deck.id,
            models.DeckComponent.card_id == card_id,
        )
    )
    if component is None:
        return jsonify({'ok': False, 'message': 'Card is not in this deck.'}), 404

    old_card = db.session.get(models.Card, card_id)
    new_card = db.session.get(models.Card, new_card_id)
    if new_card is None:
        return jsonify({'ok': False, 'message': 'Chosen printing not found.'}), 404

    # Guard: the new printing must be the SAME card, so we only ever swap
    # art/set, never change which card is in the deck. Compare by oracle_id
    # (shared across all printings) rather than name: reversible_card printings
    # carry a "Front // Back" name that differs from the normal printing's name,
    # so a name check would wrongly reject a valid same-card printing.
    if old_card is not None and new_card.oracle_id != old_card.oracle_id:
        return jsonify({'ok': False, 'message': 'Printing does not match the card.'}), 400

    component.card_id = new_card_id
    db.session.commit()

    # Changing the printing changes the card's collection pool, so recompute
    # its status and return it (plus the deck-wide faulty count) so the deck
    # overview's collection marker/grouping can refresh in place.
    from app.services.collection_service import compute_deck_collection_status
    statuses = compute_deck_collection_status(user.player_id, deck.id)
    this = statuses.get(component.id, {})
    faulty_count = sum(1 for s in statuses.values() if s['status'] == 'in_deck_faulty')

    return jsonify({
        'ok': True,
        'deck_id': deck.id,
        'card_id': new_card_id,
        'image': _front_image(new_card),
        'set_code': new_card.set_code,
        'set_name': new_card.set_name,
        'component_id': component.id,
        'collection_status': this.get('status'),
        'physical_status': this.get('physical_status'),
        'finish': this.get('finish'),
        'language': this.get('language'),
        'deck_faulty_count': faulty_count,
    })


# --- Collection tracking: set a deck card's physical marker (in_deck / proxy /
# unset) and optionally its printing / finish / language, identified by the
# component id (so two copies of the same card in a deck are distinct). Owner-
# only. CSRF via X-CSRFToken header. Returns the recomputed status for the
# component plus the deck's faulty count so the UI can refresh in place. ---
@bp.route('/<int:deck_id>/component/<int:component_id>/collection',
          methods=['POST'], strict_slashes=False)
@login_required
def set_component_collection(deck_id, component_id):
    from flask import request, jsonify
    from app.services.collection_service import (
        update_deck_component_collection,
        compute_deck_collection_status,
        VALID_PHYSICAL_STATUSES,
    )

    player_id = getattr(current_user, 'player_id', None)
    payload = request.get_json(silent=True) or {}

    physical_status = payload.get('physical_status')
    if physical_status is not None and physical_status not in VALID_PHYSICAL_STATUSES:
        return jsonify({'ok': False, 'message': 'Invalid status.'}), 400

    # 'printing_id' present (even null) means "set the printing"; absent means
    # "leave it". Validate a provided printing is the same card (same oracle).
    set_card_id = 'printing_id' in payload
    new_card_id = (payload.get('printing_id') or None)

    finish = payload.get('finish')      # None -> leave unchanged
    language = payload.get('language')  # None -> leave unchanged

    try:
        if set_card_id and new_card_id is not None:
            comp = db.session.get(models.DeckComponent, component_id)
            new_card = db.session.get(models.Card, new_card_id)
            if new_card is None:
                return jsonify({'ok': False, 'message': 'Chosen printing not found.'}), 404
            old_card = db.session.get(models.Card, comp.card_id) if comp and comp.card_id else None
            if old_card is not None and new_card.oracle_id != old_card.oracle_id:
                return jsonify({'ok': False, 'message': 'Printing does not match the card.'}), 400

        update_deck_component_collection(
            player_id, deck_id, component_id,
            physical_status=physical_status,
            card_id=new_card_id,
            finish=finish,
            language=language,
            set_card_id=set_card_id,
        )
    except PermissionError:
        return jsonify({'ok': False, 'message': 'Nicht berechtigt.'}), 403
    except LookupError:
        return jsonify({'ok': False, 'message': 'Not found.'}), 404
    except ValueError as e:
        return jsonify({'ok': False, 'message': str(e)}), 400

    db.session.commit()

    # Recompute statuses for the whole deck (cheap: a couple of bulk queries)
    # so the client gets this card's new state plus the deck-wide faulty count.
    statuses = compute_deck_collection_status(player_id, deck_id)
    this = statuses.get(component_id, {})
    faulty_count = sum(1 for s in statuses.values() if s['status'] == 'in_deck_faulty')

    return jsonify({
        'ok': True,
        'component_id': component_id,
        'status': this.get('status'),
        'physical_status': this.get('physical_status'),
        'finish': this.get('finish'),
        'language': this.get('language'),
        'owned': this.get('owned'),
        'claimed': this.get('claimed'),
        'deck_faulty_count': faulty_count,
    })


# --- Collection board fragment: the server-rendered "By collection" board for
# a deck, used by the deck overview to swap the board in place after a status
# or printing change (no full page reload). Rendered from the SAME shared macro
# as the full page, so the swapped-in board is identical to a fresh load. ---
@bp.route('/<int:deck_id>/collection-board', methods=['GET'], strict_slashes=False)
@login_required
def collection_board_fragment(deck_id):
    deck = db.get_or_404(models.Deck, deck_id)
    viewer_player_id = getattr(current_user, 'player_id', None)
    is_owner = viewer_player_id is not None and viewer_player_id == deck.player_id
    groups = build_collection_card_groups(deck, viewer_player_id)
    return render_template(
        'decks/_collection_board_fragment.html',
        ownership_card_groups=groups or [],
        is_owner=is_owner,
    )


# --- Reload a single deck's cards from its source link. Does exactly what the
# nightly reload_all_decks does, but for one deck, on demand. Owner-only, CSRF
# via X-CSRFToken header. The owner's manual collection marks (physical_status/
# finish/language) are snapshotted and re-applied by card_id, since the import
# recreates the components. ---
@bp.route('/<int:deck_id>/reload', methods=['POST'], strict_slashes=False)
@login_required
def reload_deck(deck_id):
    from app.third_party_data.deckbuilder import (
        load_cards_from_archidekt, load_cards_from_moxfield,
    )

    deck = db.get_or_404(models.Deck, deck_id)
    if deck.player_id != getattr(current_user, 'player_id', None):
        return jsonify({'ok': False, 'message': 'Nicht berechtigt.'}), 403

    if not deck.decksite or not deck.archidekt_id:
        return jsonify({
            'ok': False,
            'message': 'This deck has no source link to reload from.',
        }), 400

    # Snapshot the owner's manual collection marks before the re-import (which
    # deletes + recreates components). Re-apply them by card_id afterwards so a
    # reload doesn't silently discard in-deck/proxy markings. Keyed by card_id;
    # when the same card appears multiple times, marks are applied in order.
    from collections import deque
    marks_by_card: dict[str, deque] = {}
    existing = db.session.scalars(
        sa.select(models.DeckComponent).where(models.DeckComponent.deck_id == deck.id)
    ).all()
    for comp in existing:
        if comp.card_id and comp.physical_status != 'unset':
            marks_by_card.setdefault(comp.card_id, deque()).append({
                'physical_status': comp.physical_status,
                'physical_finish': comp.physical_finish,
                'physical_language': comp.physical_language,
            })

    try:
        if 'archidekt' in deck.decksite:
            load_cards_from_archidekt(deck.archidekt_id.strip(), deck.id)
        elif 'moxfield' in deck.decksite:
            load_cards_from_moxfield(deck.archidekt_id.strip(), deck.id)
        else:
            return jsonify({
                'ok': False,
                'message': f'Unsupported deck source: {deck.decksite}.',
            }), 400
    except Exception:
        db.session.rollback()
        logger.exception('Manual reload failed for deck %s', deck.id)
        return jsonify({
            'ok': False,
            'message': 'Could not load the deck from its link. Nothing was changed.',
        }), 502

    # Re-apply the snapshotted marks to the freshly imported components. Only
    # the physical_finish/language the owner set are restored; the import sets a
    # default finish from the source, which we override only where a mark
    # existed.
    if marks_by_card:
        new_components = db.session.scalars(
            sa.select(models.DeckComponent).where(models.DeckComponent.deck_id == deck.id)
        ).all()
        for comp in new_components:
            bucket = marks_by_card.get(comp.card_id)
            if bucket:
                mark = bucket.popleft()
                comp.physical_status = mark['physical_status']
                if mark['physical_finish']:
                    comp.physical_finish = mark['physical_finish']
                if mark['physical_language']:
                    comp.physical_language = mark['physical_language']
        db.session.commit()

    write_audit_log('deck_reload', 'Deck', deck.id, f'Reloaded deck from link: {deck.name}')
    db.session.commit()

    return jsonify({'ok': True})


# --- "My Decks" gallery: a responsive grid of deck cards (name + commander
# image), Archidekt-style. Each card links to the deck overview page. Scoped to
# the logged-in user's player, matching the existing My Decks semantics. ---
def _art_crop(image_uri):
    """Derive the Scryfall art-crop URL from a stored 'large' card image.

    Scryfall serves every size variant of a printing from the same CDN path
    with only the size segment changing, e.g.
      .../large/front/<a>/<b>/<id>.jpg   ->   .../art_crop/front/<a>/<b>/<id>.jpg
    So we swap the size segment to get just the illustration (no frame/text),
    without storing an extra column or re-fetching. Falls back to the original
    URL when it isn't a recognizable Scryfall image path.
    """
    if not image_uri:
        return None
    for size in ('/large/', '/normal/', '/small/', '/png/', '/border_crop/'):
        if size in image_uri:
            return image_uri.replace(size, '/art_crop/', 1)
    return image_uri


@bp.route('/mine', methods=['GET'], strict_slashes=False)
@bp.route('/mine/folder/<int:folder_id>', methods=['GET'], strict_slashes=False)
@login_required
def my_decks(folder_id=None):
    """The "My Decks" gallery, scoped to the current folder.

    Folders are shown as small cards above the deck grid; the decks shown are
    those in the current folder (``folder_id``), or the root when no folder is
    given. Everything is scoped to the logged-in user's player.
    """
    from app.services.color_service import resolve_color_images

    player_id = getattr(current_user, 'player_id', None)

    # Resolve the current folder (owner-scoped). A folder id that doesn't belong
    # to this player 404s so users can't peek into others' folders by id.
    current_folder = None
    if folder_id is not None:
        current_folder = db.session.get(DeckFolder, folder_id)
        if current_folder is None or current_folder.player_id != player_id:
            abort(404)

    folders = []
    decks = []
    breadcrumbs = []
    if player_id is not None:
        # Child folders of the current level (root when current_folder is None).
        folders = db.session.scalars(
            sa.select(DeckFolder)
            .where(
                DeckFolder.player_id == player_id,
                DeckFolder.parent_id == (current_folder.id if current_folder else None),
            )
            .order_by(DeckFolder.name.asc())
        ).all()

        # Active decks in the current folder.
        decks = db.session.scalars(
            sa.select(Deck)
            .where(
                Deck.player_id == player_id,
                Deck.active.is_(True),
                Deck.folder_id == (current_folder.id if current_folder else None),
            )
            .order_by(Deck.name.asc())
        ).all()

        # Breadcrumb trail from root to the current folder.
        node = current_folder
        while node is not None:
            breadcrumbs.append({'id': node.id, 'name': node.name})
            node = db.session.get(DeckFolder, node.parent_id) if node.parent_id else None
        breadcrumbs.reverse()

    # Per-folder deck counts (active decks directly inside each folder) for the
    # folder card subtitle.
    folder_cards = []
    for folder in folders:
        count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(Deck)
            .where(Deck.folder_id == folder.id, Deck.active.is_(True))
        ) or 0
        folder_cards.append({'id': folder.id, 'name': folder.name, 'deck_count': count})

    deck_cards = []
    for deck in decks:
        tags = db.session.scalars(
            sa.select(models.DeckTag.tag)
            .where(models.DeckTag.deck_id == deck.id)
            .order_by(models.DeckTag.tag)
        ).all()
        deck_cards.append({
            'id': deck.id,
            'name': deck.name,
            'commander': deck.commander,
            'image': _art_crop(deck.image_uri),
            'color_imgs': resolve_color_images(deck.color_identity),
            'tags': list(tags),
        })

    return render_template(
        'decks/my_decks.html',
        deck_cards=deck_cards,
        folder_cards=folder_cards,
        current_folder={'id': current_folder.id, 'name': current_folder.name} if current_folder else None,
        parent_folder_id=(current_folder.parent_id if current_folder else None),
        breadcrumbs=breadcrumbs,
    )


@bp.route('/folders', methods=['POST'], strict_slashes=False)
@login_required
def create_folder():
    """Create a new folder for the current user, optionally nested.

    JSON body: {name: str, parent_id: int|null}. Owner-scoped: a provided
    parent_id must belong to the current player. Returns the created folder.
    CSRF is enforced via the X-CSRFToken header (CSRFProtect).
    """
    player_id = getattr(current_user, 'player_id', None)
    if player_id is None:
        return jsonify({'ok': False, 'message': 'No player linked to this account.'}), 400

    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    parent_id = data.get('parent_id')

    if not name:
        return jsonify({'ok': False, 'message': 'Folder name is required.'}), 400
    if len(name) > 255:
        return jsonify({'ok': False, 'message': 'Folder name is too long.'}), 400

    if parent_id is not None:
        parent = db.session.get(DeckFolder, parent_id)
        if parent is None or parent.player_id != player_id:
            return jsonify({'ok': False, 'message': 'Parent folder not found.'}), 404

    folder = DeckFolder(player_id=player_id, name=name, parent_id=parent_id)
    db.session.add(folder)
    db.session.flush()
    write_audit_log('folder_create', 'DeckFolder', folder.id, f'Created folder: {name}')
    db.session.commit()

    return jsonify({
        'ok': True,
        'folder': {'id': folder.id, 'name': folder.name, 'parent_id': folder.parent_id, 'deck_count': 0},
    }), 201


@bp.route('/<int:deck_id>/folder', methods=['POST'], strict_slashes=False)
@login_required
def move_deck_to_folder(deck_id):
    """Move a deck into a folder (or to the root).

    JSON body: {folder_id: int|null}. null moves the deck to the root. Both the
    deck and the target folder must belong to the current player. CSRF via the
    X-CSRFToken header (CSRFProtect). Returns {ok: true}.
    """
    player_id = getattr(current_user, 'player_id', None)
    deck = db.session.get(Deck, deck_id)
    if deck is None:
        return jsonify({'ok': False, 'message': 'Deck not found.'}), 404
    if deck.player_id != player_id:
        return jsonify({'ok': False, 'message': 'Nicht berechtigt.'}), 403

    data = request.get_json(silent=True) or {}
    target_folder_id = data.get('folder_id')

    if target_folder_id is not None:
        folder = db.session.get(DeckFolder, target_folder_id)
        if folder is None or folder.player_id != player_id:
            return jsonify({'ok': False, 'message': 'Target folder not found.'}), 404

    deck.folder_id = target_folder_id
    write_audit_log('deck_move_folder', 'Deck', deck.id, f'Moved deck {deck.name} to folder {target_folder_id}')
    db.session.commit()

    return jsonify({'ok': True})
