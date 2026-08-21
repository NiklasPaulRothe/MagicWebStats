import logging
from datetime import date, timedelta

from app import db
from app.main import bp
from flask import render_template
from flask_login import login_required, current_user
import sqlalchemy as sa

logger = logging.getLogger(__name__)

from app.models import User, Player, Game, Participant
from app.services.stats_service import compute_chart_data
from app.viewmodels import ColorUsage, ColorUsagePlayer


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


@bp.route('/user/<spieler>')
@login_required
def user(spieler):
    logger.debug("Loading user profile: %s", spieler)
    user = db.first_or_404(sa.select(User).where(User.username == spieler))
    owner = (user.id == current_user.id)
    username = user.username
    spieler = db.session.scalar(sa.select(Player).where(Player.id == user.player_id))
    return render_template(
        'user.html',
        spieler=spieler,
        owner=owner,
        username=username)

@bp.route('/player/<spieler>')
@login_required
def player(spieler):
    player = db.session.scalar(sa.select(Player).where(Player.name == spieler))
    username = None
    try:
        user = db.session.scalar(sa.select(User).where(User.player_id == player.id))
        owner = (user.id == current_user.id)
        username = user.username
    except Exception:
        owner = False
    return render_template(
        'user.html',
        spieler=player,
        owner=owner,
        username=username)

