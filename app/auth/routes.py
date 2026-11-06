from flask import render_template, redirect, url_for, flash, request, abort
from urllib.parse import urlsplit
from flask_login import login_user, logout_user, current_user, login_required
import sqlalchemy as sa
from app import db, limiter
from app.auth import bp, min_role_required, ROLE_ADMIN, VALID_ROLES
from app.auth.forms import LoginForm, RegistrationForm
from app.models import User
from app.services.audit import write_audit_log

# --- CSRF Audit (Requirement 16.1) ---
# All POST endpoints in this module are protected by Flask-WTF CSRFProtect (init'd in app/__init__.py).
# - login: WTForms LoginForm (auto CSRF token)
# - register: WTForms RegistrationForm (auto CSRF token)
# No exemptions are needed.
# ---


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10/minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == form.username.data))
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password')
            return redirect(url_for('auth.login'))
        if user.active is False:
            flash('Account ist nicht aktiviert')
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or urlsplit(next_page).netloc != '':
            next_page = url_for('main.index')
        return redirect(next_page)
    return render_template('auth/login.html', title='Sign In', form=form)



@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('main.index'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        user.active = False
        db.session.add(user)
        db.session.commit()
        flash('Congratulations, you are now a registered user!')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', title='Register', form=form)


# ── Role management (admin only) ─────────────────────────────────────────────
# CSRF: the role form is an HTML POST carrying the hidden csrf token validated
# by the global CSRFProtect, so no exemption is needed.

@bp.route('/manage/roles', methods=['GET'])
@min_role_required(ROLE_ADMIN)
@login_required
def manage_roles():
    """List all accounts with their current role and linked player.

    Users are ordered by role rank (admins first) then username so the table
    reads top-down by privilege. Also provides the full player list (for the
    assignment dropdown) and a player_id -> name map for display.
    """
    from app.auth import role_level
    from app.models import Player

    users = db.session.scalars(sa.select(User)).all()
    users.sort(key=lambda u: (-role_level(u.role), (u.username or '').lower()))

    players = db.session.scalars(
        sa.select(Player).order_by(Player.name)
    ).all()
    player_names = {p.id: p.name for p in players}

    return render_template(
        'auth/manage_roles.html',
        users=users,
        valid_roles=VALID_ROLES,
        players=players,
        player_names=player_names,
    )


@bp.route('/manage/roles/<int:user_id>', methods=['POST'])
@min_role_required(ROLE_ADMIN)
@login_required
def set_user_role(user_id):
    """Set a single user's role to one of VALID_ROLES.

    Guards against lockout: demoting the last remaining admin is rejected so the
    instance always keeps at least one admin. (An admin may still demote
    themselves as long as another admin remains.)
    """
    target = db.get_or_404(User, user_id)
    new_role = (request.form.get('role') or '').strip()

    if new_role not in VALID_ROLES:
        flash(f'Unknown role: {new_role!r}.', 'error')
        return redirect(url_for('auth.manage_roles'))

    old_role = target.role
    if old_role == new_role:
        flash(f'{target.username} is already {new_role}.', 'warning')
        return redirect(url_for('auth.manage_roles'))

    # Lockout guard: if this change removes the last admin, refuse.
    if old_role == ROLE_ADMIN and new_role != ROLE_ADMIN:
        admin_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(User).where(User.role == ROLE_ADMIN)
        )
        if admin_count is not None and admin_count <= 1:
            flash('Cannot remove the last admin — promote another admin first.', 'error')
            return redirect(url_for('auth.manage_roles'))

    target.role = new_role
    write_audit_log(
        'role_change', 'User', target.id,
        f'Role for {target.username}: {old_role} \u2192 {new_role}',
    )
    db.session.commit()
    flash(f'{target.username} is now {new_role}.', 'success')
    return redirect(url_for('auth.manage_roles'))


@bp.route('/manage/roles/<int:user_id>/player', methods=['POST'])
@min_role_required(ROLE_ADMIN)
@login_required
def set_user_player(user_id):
    """Assign (or clear) the Player linked to a user account.

    An empty value unlinks the account (player_id = NULL). A player may be
    linked to at most one user, since the profile/stats pages resolve a
    player's account via a single ``User.player_id == player.id`` lookup; an
    attempt to assign a player already linked elsewhere is rejected.
    """
    from app.models import Player

    target = db.get_or_404(User, user_id)
    raw = (request.form.get('player_id') or '').strip()

    # Empty selection clears the link.
    if raw == '':
        new_player_id = None
    else:
        try:
            new_player_id = int(raw)
        except ValueError:
            flash('Invalid player selection.', 'error')
            return redirect(url_for('auth.manage_roles'))

        player = db.session.get(Player, new_player_id)
        if player is None:
            flash('That player does not exist.', 'error')
            return redirect(url_for('auth.manage_roles'))

        # Enforce the one-user-per-player assumption used across the app.
        existing = db.session.scalar(
            sa.select(User).where(
                User.player_id == new_player_id,
                User.id != target.id,
            )
        )
        if existing is not None:
            flash(
                f'Player "{player.name}" is already linked to {existing.username}. '
                f'Unassign it there first.',
                'error',
            )
            return redirect(url_for('auth.manage_roles'))

    old_player_id = target.player_id
    if old_player_id == new_player_id:
        flash('No change to the linked player.', 'warning')
        return redirect(url_for('auth.manage_roles'))

    def _name(pid):
        if pid is None:
            return '(none)'
        p = db.session.get(Player, pid)
        return p.name if p else f'#{pid}'

    target.player_id = new_player_id
    write_audit_log(
        'user_player_change', 'User', target.id,
        f'Player for {target.username}: {_name(old_player_id)} \u2192 {_name(new_player_id)}',
    )
    db.session.commit()
    flash(f'{target.username} is now linked to {_name(new_player_id)}.', 'success')
    return redirect(url_for('auth.manage_roles'))
