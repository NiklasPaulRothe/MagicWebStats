from app import db
from app.main import bp
from flask import render_template
from flask_login import login_required
import sqlalchemy as sa

from app.models import User
from app.viewmodels import ColorUsage, ColorUsagePlayer


@bp.route('/')
@bp.route('/index')
@login_required
def index():  # put application's code here
    color_usage = ColorUsage.query.all()
    color_usage_player = ColorUsagePlayer.query.all()
    return render_template('index.html', color_usage=color_usage, color_usage_player=color_usage_player)

@bp.route('/user/<username>')
@login_required
def user(username):
    user = db.first_or_404(sa.select(User).where(User.username == username))
    return render_template(('user.html', user))

