import io
import logging

from flask import render_template, redirect, url_for, request, flash, abort, jsonify
import sqlalchemy as sa
from flask_login import login_required, current_user

from app import db
from app import models
from app.collection import bp
from app.services.collection_service import (
    import_player_collection,
    get_player_collection,
    get_collection_statuses,
    get_decks_containing_card,
    COLL_STATUS_SPARE,
)

logger = logging.getLogger(__name__)

# Only accept .csv uploads; keep the limit modest — a collection export is text.
MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB


@bp.route('/collection', methods=['GET'])
@login_required
def collection():
    """The current user's card collection: import form + card image gallery."""
    player_id = current_user.player_id
    cards = []
    total_cards = 0
    total_value = None
    if player_id is not None:
        cards = get_player_collection(player_id)
        total_cards = sum(c['count'] for c in cards)
        priced = [c['price'] * c['count'] for c in cards if c['price'] is not None]
        total_value = sum(priced) if priced else None

        # Attach a per-entry collection status (owned_in_deck /
        # owned_spare_available / owned_no_copy_available). Each entry owns >=1
        # copy of its own pool, so those are the three possible outcomes; an
        # unresolved entry (card_id is None) can't be matched to decks and is
        # treated as spare (it isn't claimed anywhere).
        statuses = get_collection_statuses(player_id)
        for c in cards:
            key = (
                c['card_id'],
                (c['finish'] or '').strip().lower(),
                (c['language'] or '').strip().lower(),
            )
            c['status'] = statuses.get(key, COLL_STATUS_SPARE) if c['card_id'] else COLL_STATUS_SPARE

    return render_template(
        'collection/collection.html',
        cards=cards,
        total_cards=total_cards,
        total_value=total_value,
        has_player=player_id is not None,
    )


@bp.route('/collection/import', methods=['POST'])
@login_required
def import_collection():
    """Import a collection CSV for the current user's player (replace mode)."""
    player_id = current_user.player_id
    if player_id is None:
        flash('Your account is not linked to a player, so a collection '
              'cannot be imported.', 'error')
        return redirect(url_for('collection.collection'))

    file = request.files.get('csv_file')
    if file is None or not file.filename:
        flash('Please choose a CSV file to import.', 'error')
        return redirect(url_for('collection.collection'))

    if not file.filename.lower().endswith('.csv'):
        flash('The collection import expects a .csv file.', 'error')
        return redirect(url_for('collection.collection'))

    raw = file.read(MAX_CSV_BYTES + 1)
    if len(raw) > MAX_CSV_BYTES:
        flash('That file is too large (limit 10 MB).', 'error')
        return redirect(url_for('collection.collection'))

    # Decode as UTF-8 (BOM-tolerant, matching the CLI importer).
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        flash('The file could not be read as UTF-8 text.', 'error')
        return redirect(url_for('collection.collection'))

    try:
        result = import_player_collection(
            player_id, io.StringIO(text), replace=True
        )
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'error')
        return redirect(url_for('collection.collection'))
    except Exception:
        db.session.rollback()
        logger.exception('Collection import failed for player %s', player_id)
        flash('The collection import failed. No changes were saved.', 'error')
        return redirect(url_for('collection.collection'))

    flash(
        f'Imported {result.imported} card entr'
        f'{"y" if result.imported == 1 else "ies"} '
        f'({result.total_quantity} cards total).',
        'success',
    )
    if result.unimported:
        # Surface the cards that were skipped because their exact printing
        # isn't in our database yet — never silently substituted.
        preview = ', '.join(
            f'{e.name} [{e.set_code or "?"}#{e.collector_number or "?"}]'
            for e in result.unimported[:10]
        )
        more = '' if len(result.unimported) <= 10 else f' (+{len(result.unimported) - 10} more)'
        flash(
            f'{len(result.unimported)} entr'
            f'{"y" if len(result.unimported) == 1 else "ies"} could not be '
            f'matched to a known printing and {"was" if len(result.unimported) == 1 else "were"} '
            f'skipped: {preview}{more}.',
            'warning',
        )

    return redirect(url_for('collection.collection'))


def _front_image(card):
    """Front-face (face_index == 0) image_uri for a Card, or None.

    Falls back to the first face with any image when face 0 has none, so a
    double-faced card still gets a thumbnail even if its front image is missing.
    """
    faces = sorted(card.faces, key=lambda f: f.face_index)
    front = next((f for f in faces if f.face_index == 0), None)
    if front and front.image_uri:
        return front.image_uri
    return next((f.image_uri for f in faces if f.image_uri), None)


def _card_faces_payload(card):
    """Faces for the popup: each face's name, type, oracle text, and image.

    For a single-face card this is one entry; for a double-faced card it's both
    faces in order, so the popup can show both sides' text.
    """
    return [
        {
            'name': f.name,
            'mana_cost': f.mana_cost,
            'type_line': f.type_line,
            'oracle_text': f.oracle_text,
            'image': f.image_uri,
        }
        for f in sorted(card.faces, key=lambda f: f.face_index)
    ]


# --- Collection card popup data: for a clicked collection card, return its
# detail, every deck of the player that contains the card (any printing) with
# the per-deck collection status, and all printings of the card so the popup
# can offer a read-only printing slider that flags a non-clicked printing.
# Read-only and scoped to the current user's player. ---
@bp.route('/collection/card/<card_id>', methods=['GET'], strict_slashes=False)
@login_required
def collection_card(card_id):
    player_id = current_user.player_id
    if player_id is None:
        return jsonify({'ok': False, 'message': 'No player linked to this account.'}), 400

    card = db.session.get(models.Card, card_id)
    if card is None:
        return jsonify({'ok': False, 'message': 'Card not found.'}), 404

    # Decks that contain this card (by oracle_id, across printings), each with
    # its computed per-deck collection status. Mark which deck entries use the
    # exact printing the user clicked.
    decks = get_decks_containing_card(player_id, card.oracle_id)
    for d in decks:
        d['same_printing'] = (d['card_id'] == card_id)

    # All printings of this card (shared oracle_id), oldest-first. Each carries
    # its front image so the slider can show it; 'current' marks the clicked
    # printing so the UI can flag "different printing" clearly.
    printings = db.session.scalars(
        sa.select(models.Card)
        .where(models.Card.oracle_id == card.oracle_id)
        .order_by(models.Card.released_at.asc().nulls_last(), models.Card.set_code.asc())
    ).all()
    printings_payload = [
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
        'id': card.id,
        'name': card.name,
        'type_line': card.type_line,
        'image': _front_image(card),
        'faces': _card_faces_payload(card),
        'decks': decks,
        'printings': printings_payload,
    })
