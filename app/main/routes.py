import statistics
from collections import Counter

from app import db
from app.main import bp
from flask import render_template
from flask_login import login_required, current_user
import sqlalchemy as sa

from app.models import User, Player
from app.viewmodels import ColorUsage, ColorUsagePlayer


@bp.route('/')
@bp.route('/index')
@login_required
def index():
    color_usage = ColorUsage.query.all()
    color_usage_player = ColorUsagePlayer.query.all()

    color_usage_data = [
        {
            'color': cu.color,
            'likelihood': cu.likelihood,
            'average': cu.average,
            'deck_percentage': cu.deck_percentage
        } for cu in color_usage
    ]

    # === Turn Chart Data ===
    from app.models import Game
    games = Game.query.with_entities(Game.turns).filter(Game.turns.isnot(None)).all()
    turns_list = [g.turns for g in games]

    # Count per turn
    turn_counts = Counter(turns_list)
    sorted_turns = sorted(turn_counts.items())
    turn_data = [{"turn": t, "count": count} for t, count in sorted_turns]

    games = Game.query.with_entities(Game.first_ko_turn).filter(Game.first_ko_turn.isnot(None)).all()
    ko_turns_list = [g.first_ko_turn for g in games]

    # Count per ko_turn
    ko_turn_counts = Counter(ko_turns_list)
    sorted_ko_turns = sorted(ko_turn_counts.items())
    ko_turn_data = [{"turn": t, "count": count} for t, count in sorted_ko_turns]

    # Compute average and median
    avg_turns = round(statistics.mean(turns_list), 2) if turns_list else 0
    median_turns = round(statistics.median(turns_list), 2) if turns_list else 0

    # Final blow pie chart data
    final_blow_counts = (
        db.session.query(Game.final_blow)
        .filter(Game.final_blow.isnot(None))
        .all()
    )
    final_blow_flat = [fb[0] for fb in final_blow_counts]
    final_blow_counter = dict(Counter(final_blow_flat))

    # First KO pie chart data
    first_ko_counts = (
        db.session.query(Game.first_ko_by)
        .filter(Game.first_ko_by.isnot(None))
        .all()
    )
    first_ko_flat = [fb[0] for fb in first_ko_counts]
    first_ko_counter = dict(Counter(first_ko_flat))

    return render_template(
        'index.html',
        color_usage=color_usage_data,
        color_usage_player=color_usage_player,
        turn_data=turn_data,
        final_blow_data=final_blow_counter,
        first_ko_data=first_ko_counter,
        ko_turn_data=ko_turn_data,
        avg_turns=avg_turns,
        median_turns=median_turns
    )


@bp.route('/user/<spieler>')
@login_required
def user(spieler):
    print(spieler)
    user = db.first_or_404(sa.select(User).where(User.username == spieler))
    owner = (user.id == current_user.id)
    spieler = db.session.scalar(sa.select(Player).where(Player.id == user.spieler))
    return render_template(
        'user.html',
        spieler=spieler,
        owner=owner)

@bp.route('/player/<spieler>')
@login_required
def player(spieler):
    player = db.session.scalar(sa.select(Player).where(Player.Name == spieler))
    try:
        user = db.first_or_null(sa.select(User).where(User.spieler == player.id))
        owner = (user.id == current_user.id)
    except:
        owner = False
    return render_template(
        'user.html',
        spieler=player,
        owner=owner)

