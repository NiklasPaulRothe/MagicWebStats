import sqlalchemy as sa
import sqlalchemy.orm as so
from flask_login import current_user

from app import create_app, db
from app.models import User
from flask_principal import RoleNeed, identity_loaded, UserNeed

app = create_app()

@identity_loaded.connect_via(app)
def on_identity_loaded(sender, identity):
    # Set the identity user object
    identity.user = current_user

    # Add the UserNeed to the identity
    if hasattr(current_user, 'id'):
        identity.provides.add(UserNeed(current_user.id))

    # Assuming the User model has a list of roles, update the
    # identity with the roles that the user provides
    identity.provides.add(RoleNeed('admin'))
    identity.provides.add(RoleNeed('maintainer'))

@app.shell_context_processor
def make_shell_context():
    return {'sa': sa, 'so': so, 'db': db, 'User': User}