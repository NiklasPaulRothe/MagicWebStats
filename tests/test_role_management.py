"""Tests for the admin role-management UI (auth.manage_roles / set_user_role).

Covers: admin-only access to the page and the update endpoint, role validation,
the audit-log entry on a successful change, and the lockout guard that refuses
to demote the last remaining admin.
"""

import pytest

from app import create_app, db as _db
from app.models import User, Player, AuditLog


class RoleMgmtTestConfig:
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    SESSION_COOKIE_DOMAIN = False
    RATELIMIT_ENABLED = False
    PERSONAL_STATS_USERNAME = "Niklas"


@pytest.fixture
def app():
    application = create_app(config_class=RoleMgmtTestConfig)
    with application.app_context():
        _db.session.execute(_db.text("ATTACH DATABASE ':memory:' AS magic_stats_owner"))
        _db.create_all()
        _db.session.add(Player(id=1, name="P1"))
        _db.session.add(Player(id=2, name="P2"))
        _db.session.add(Player(id=3, name="P3"))
        _db.session.commit()
        yield application
        _db.session.remove()
        _db.drop_all()


def _add_user(username, role, uid, player_id):
    u = User(id=uid, username=username, email=f"{username}@e.com",
             player_id=player_id, active=True, role=role)
    u.set_password("pw")
    _db.session.add(u)
    _db.session.commit()
    return u


def _login(client, username):
    return client.post("/auth/login", data={"username": username, "password": "pw"})


def test_non_admin_denied_manage_roles(app):
    """A maintainer (non-admin) cannot see the role manager."""
    with app.app_context():
        _add_user("maint", "maintainer", 1, 1)
        with app.test_client() as client:
            _login(client, "maint")
            assert client.get("/auth/manage/roles").status_code == 403


def test_admin_sees_manage_roles(app):
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            resp = client.get("/auth/manage/roles")
            assert resp.status_code == 200
            assert b"joe" in resp.data


def test_admin_can_promote_user_to_maintainer(app):
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            resp = client.post("/auth/manage/roles/2", data={"role": "maintainer"},
                               follow_redirects=False)
            assert resp.status_code == 302
        # Role persisted + audit entry written.
        assert _db.session.get(User, 2).role == "maintainer"
        entry = AuditLog.query.filter_by(action="role_change").first()
        assert entry is not None and "maintainer" in entry.details


def test_invalid_role_rejected(app):
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            client.post("/auth/manage/roles/2", data={"role": "superadmin"})
        assert _db.session.get(User, 2).role == "user"  # unchanged


def test_cannot_demote_last_admin(app):
    """Demoting the only admin is refused (lockout guard)."""
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        with app.test_client() as client:
            _login(client, "boss")
            client.post("/auth/manage/roles/1", data={"role": "user"})
        assert _db.session.get(User, 1).role == "admin"  # still admin


def test_can_demote_admin_when_another_admin_exists(app):
    """With two admins, one may be demoted."""
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("boss2", "admin", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            client.post("/auth/manage/roles/2", data={"role": "user"})
        assert _db.session.get(User, 2).role == "user"


def test_non_admin_cannot_post_role_change(app):
    """A maintainer cannot hit the update endpoint directly."""
    with app.app_context():
        _add_user("maint", "maintainer", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "maint")
            resp = client.post("/auth/manage/roles/2", data={"role": "admin"})
            assert resp.status_code == 403
        assert _db.session.get(User, 2).role == "user"


# ── Linked-player assignment ─────────────────────────────────────────────────

def test_admin_can_reassign_player(app):
    """Admin can change a user's linked player; audit entry is written."""
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            resp = client.post("/auth/manage/roles/2/player",
                               data={"player_id": "3"}, follow_redirects=False)
            assert resp.status_code == 302
        assert _db.session.get(User, 2).player_id == 3
        entry = AuditLog.query.filter_by(action="user_player_change").first()
        assert entry is not None and "P3" in entry.details


def test_admin_can_clear_player(app):
    """An empty selection unlinks the player (player_id = NULL)."""
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            client.post("/auth/manage/roles/2/player", data={"player_id": ""})
        assert _db.session.get(User, 2).player_id is None


def test_cannot_assign_player_linked_to_another_user(app):
    """A player already linked to another user cannot be assigned (1-user rule)."""
    with app.app_context():
        _add_user("boss", "admin", 1, 1)   # linked to player 1
        _add_user("joe", "user", 2, 2)     # linked to player 2
        with app.test_client() as client:
            _login(client, "boss")
            # Try to give joe player 1, which is boss's.
            client.post("/auth/manage/roles/2/player", data={"player_id": "1"})
        assert _db.session.get(User, 2).player_id == 2  # unchanged


def test_assign_nonexistent_player_rejected(app):
    with app.app_context():
        _add_user("boss", "admin", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "boss")
            client.post("/auth/manage/roles/2/player", data={"player_id": "999"})
        assert _db.session.get(User, 2).player_id == 2  # unchanged


def test_non_admin_cannot_change_player(app):
    with app.app_context():
        _add_user("maint", "maintainer", 1, 1)
        _add_user("joe", "user", 2, 2)
        with app.test_client() as client:
            _login(client, "maint")
            resp = client.post("/auth/manage/roles/2/player", data={"player_id": "3"})
            assert resp.status_code == 403
        assert _db.session.get(User, 2).player_id == 2
