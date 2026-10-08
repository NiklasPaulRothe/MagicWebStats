import logging
from datetime import date, timedelta

from app import db
from app.main import bp
from flask import render_template, redirect, url_for, request, abort
from flask_login import login_required, current_user
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from app.models import User, Player, Game, Participant
from app.services.stats_service import (
    compute_chart_data,
    compute_player_overview,
    build_player_profile,
)
from app.viewmodels import ColorUsage, ColorUsagePlayer


def resolve_player(identifier):
    """Resolve a player by numeric id or by name.

    A numeric identifier (int or all-digit string) is looked up against
    ``Player.id``; any other value is looked up against ``Player.name`` for
    backward-compatible, name-based URLs. Returns ``None`` when no player
    matches so callers can turn that into a 404.

    Requirements: 1.3 (numeric id as primary identifier), 1.4 (legacy name
    URLs still resolve), 1.5 (missing player -> None -> 404 at call site).
    """
    if identifier is None:
        return None
    if isinstance(identifier, int) or str(identifier).isdigit():
        return db.session.get(Player, int(identifier))
    return db.session.scalar(sa.select(Player).where(Player.name == identifier))


@bp.route('/healthz')
def healthz():
    """Deployment health check. No auth required."""
    try:
        db.session.execute(sa.text('SELECT 1'))
        return {'status': 'healthy'}, 200
    except Exception:
        return {'status': 'unhealthy'}, 503


@bp.route('/')
@bp.route('/index')
@login_required
def index():
    color_usage = ColorUsage.query.all()

    # Only include players who have played at least one game in the last year
    one_year_ago = date.today() - timedelta(days=365)
    active_player_stmt = (
        sa.select(Player.name)
        .join(Participant, Participant.player_id == Player.id)
        .join(Game, Game.id == Participant.game_id)
        .where(Game.date >= one_year_ago)
        .distinct()
    )
    active_player_names = set(db.session.scalars(active_player_stmt).all())
    color_usage_player = [
        cup for cup in ColorUsagePlayer.query.all()
        if cup.Player in active_player_names
    ]

    color_usage_data = [
        {
            'color': cu.color,
            'likelihood': cu.likelihood,
            'average': cu.average,
            'deck_percentage': cu.deck_percentage
        } for cu in color_usage
    ]

    # Chart data computed via service layer
    try:
        chart_data = compute_chart_data(exclude_cedh=True)
    except Exception:
        logger.exception("Failed to compute chart data")
        db.session.rollback()
        chart_data = {
            "turn_data": [],
            "ko_turn_data": [],
            "avg_turns": 0,
            "median_turns": 0,
            "avg_ko_turns": 0,
            "median_ko_turns": 0,
            "final_blow_data": {},
            "first_ko_data": {},
        }

    return render_template(
        'index.html',
        color_usage=color_usage_data,
        color_usage_player=color_usage_player,
        turn_data=chart_data["turn_data"],
        final_blow_data=chart_data["final_blow_data"],
        first_ko_data=chart_data["first_ko_data"],
        ko_turn_data=chart_data["ko_turn_data"],
        avg_turns=chart_data["avg_turns"],
        median_turns=chart_data["median_turns"],
        avg_ko_turns=chart_data["avg_ko_turns"],
        median_ko_turns=chart_data["median_ko_turns"]
    )


@bp.route('/user/<identifier>')
@login_required
def user(identifier):
    """Owner/private deck overview page.

    Resolves the player by numeric id or legacy name (Req 1.3/1.4), 404s when
    missing (Req 1.5), and renders the deck overview view (Req 12.1). The route
    lives under ``/user`` as the private/owner view (Req 1.2) and requires auth
    (Req 1.6). Owner/username context is derived from the linked ``User`` so the
    overview still renders when no user is linked (Req 13.2).
    """
    logger.debug("Loading deck overview: %s", identifier)
    spieler = resolve_player(identifier)
    if spieler is None:
        from flask import abort
        abort(404)

    # Owner/username via the linked User (User.player_id == player.id). When no
    # user is linked, owner is False and username is None — the overview still
    # renders.
    linked_user = db.session.scalar(
        sa.select(User).where(User.player_id == spieler.id)
    )
    if linked_user is not None:
        owner = (linked_user.id == current_user.id)
        username = linked_user.username
    else:
        owner = False
        username = None

    player_stats = compute_player_overview(spieler.id)
    return render_template(
        'decks.html',
        spieler=spieler,
        owner=owner,
        username=username,
        player_stats=player_stats)

@bp.route('/player/<identifier>')
@login_required
def player(identifier):
    """Public player profile page.

    Resolves the player by numeric id or legacy name (Req 1.3/1.4), 404s when
    missing (Req 1.5), and renders the profile view (Req 1.1). The route lives
    under ``/player`` as the public profile (Req 1.2) and requires auth (Req
    1.6). Owner/username context is derived from the linked ``User`` so the
    profile still renders when no user is linked (Req 11.3, 13.2).
    """
    player = resolve_player(identifier)
    if player is None:
        from flask import abort
        abort(404)

    # Owner/username via the linked User (User.player_id == player.id). When no
    # user is linked, owner is False and username is None — the profile still
    # renders (Req 11.3, 13.2).
    linked_user = db.session.scalar(
        sa.select(User).where(User.player_id == player.id)
    )
    if linked_user is not None:
        owner = (linked_user.id == current_user.id)
        username = linked_user.username
    else:
        owner = False
        username = None

    # Bio lives on the linked User (Req 11.2); None when no user is linked so
    # the bio section renders a read-only empty state (Req 11.3).
    bio = linked_user.bio if linked_user is not None else None

    profile = build_player_profile(player.id)
    return render_template(
        'profile.html',
        player=player,
        owner=owner,
        username=username,
        bio=bio,
        **profile,
    )


# CSRF: CSRFProtect is enabled globally (app/__init__.py); this HTML form POST
# validates the hidden csrf token automatically, so no exemption is needed.
@bp.route('/user/<identifier>/bio', methods=['POST'])
@login_required
def update_bio(identifier):
    """Persist a bio update for a player's linked user account.

    Server-side ownership is re-checked here, independent of whether the UI
    rendered the edit controls (Req 11.7): the current user is the owner only
    when a ``User`` is linked to the player (``User.player_id == player.id``)
    and that user is ``current_user``; otherwise the request is forbidden.

    The submitted bio is stripped and length-capped to match the
    ``User.bio`` column (``String(1000)``); over-length input is rejected with
    400 (Req 11.8). The raw stripped text is persisted — Jinja autoescaping on
    render guards against stored XSS, so no pre-escaping or ``|safe`` is used.
    On success the request redirects to the profile page so a reload shows the
    new value (Req 11.6).

    Requirements: 11.6, 11.7, 11.8.
    """
    player = resolve_player(identifier)
    if player is None:
        abort(404)

    linked_user = db.session.scalar(
        sa.select(User).where(User.player_id == player.id)
    )
    if not (linked_user is not None and linked_user.id == current_user.id):
        # Server-side ownership check (Req 11.7): only the owner may edit.
        abort(403)

    bio = (request.form.get('bio') or '').strip()
    if len(bio) > 1000:
        # Length limit matching the User.bio column (Req 11.8).
        abort(400)

    linked_user.bio = bio
    db.session.commit()
    return redirect(url_for('main.player', identifier=player.id))

