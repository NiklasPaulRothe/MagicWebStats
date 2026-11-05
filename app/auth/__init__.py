from flask import Blueprint, current_app
from functools import wraps
from flask import abort
from flask_login import current_user

bp = Blueprint('auth', __name__)


# ── Role model ──────────────────────────────────────────────────────────────
# Three tiers, strictly increasing in capability (admin is a SUPERSET of
# maintainer, which is a superset of user):
#
#   user       — normal authenticated rights (view stats, own decks/collection).
#   maintainer — user + content management: add players/decks/games, edit/delete
#                games, quick-add, bulk deck import, and moderate archives.
#   admin      — maintainer + oversight: audit log, Elo recalculation, and role
#                management.
#
# Authorization is checked by LEVEL (see ``min_role_required`` /
# ``has_min_role``), never by an exact string, so a higher tier automatically
# inherits every lower-tier capability.
ROLE_USER = 'user'
ROLE_MAINTAINER = 'maintainer'
ROLE_ADMIN = 'admin'

# Canonical ordering. Higher number = more capability.
ROLE_LEVELS = {
    ROLE_USER: 0,
    ROLE_MAINTAINER: 10,
    ROLE_ADMIN: 20,
}

# The set of roles the application accepts (e.g. for the role-management UI and
# the DB CHECK constraint). Kept in sync with scripts/schema.sql.
VALID_ROLES = tuple(ROLE_LEVELS.keys())


def role_level(role) -> int:
    """Numeric capability level for a role string.

    Unknown / NULL roles resolve to -1 so they rank below ``user`` and are
    denied by every ``has_min_role`` gate (fail-closed).
    """
    if role is None:
        return -1
    return ROLE_LEVELS.get(role, -1)


def has_min_role(user, minimum: str) -> bool:
    """True when ``user`` is authenticated and ranks at or above ``minimum``.

    ``minimum`` is one of the ROLE_* constants. Because the check is by level,
    an admin satisfies ``has_min_role(user, ROLE_MAINTAINER)`` automatically.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return role_level(getattr(user, 'role', None)) >= role_level(minimum)


def is_admin(user) -> bool:
    """True when ``user`` is an admin (the top tier)."""
    return has_min_role(user, ROLE_ADMIN)


def is_maintainer(user) -> bool:
    """True when ``user`` is a maintainer OR higher (i.e. maintainer or admin)."""
    return has_min_role(user, ROLE_MAINTAINER)


def min_role_required(minimum: str):
    """Route decorator: require the current user to rank at or above ``minimum``.

    Hierarchy-aware — a user whose role outranks ``minimum`` is allowed. Returns
    403 otherwise. Use this for all new authorization gates:

        @min_role_required(ROLE_MAINTAINER)   # maintainer or admin
        @min_role_required(ROLE_ADMIN)        # admin only
    """
    def wrapper(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if not has_min_role(current_user, minimum):
                return abort(403)
            return func(*args, **kwargs)
        return decorated_view
    return wrapper


def role_required(*roles):
    """Legacy exact-match role gate (kept for compatibility).

    Prefer ``min_role_required`` for new code: this checks membership in an
    explicit set and is NOT hierarchy-aware. Retained so any remaining call
    sites keep their original semantics.
    """
    def wrapper(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                return abort(403)  # Forbidden access
            return func(*args, **kwargs)
        return decorated_view
    return wrapper


def has_personal_stats_access(user) -> bool:
    """Check if the given user has access to personal stats fields."""
    return user.is_authenticated and user.username == current_app.config['PERSONAL_STATS_USERNAME']


# Import routes LAST so that this module's blueprint, constants and helpers are
# fully defined before app/auth/routes.py imports them (avoids a circular
# import — see the standard Flask blueprint pattern).
from app.auth import routes  # noqa: E402
