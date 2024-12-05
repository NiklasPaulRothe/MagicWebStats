from flask import Blueprint
from functools import wraps
from flask import abort
from flask_login import current_user

bp = Blueprint('auth', __name__)

from app.auth import routes

def role_required(*roles):
    def wrapper(func):
        @wraps(func)
        def decorated_view(*args, **kwargs):
            if current_user.role not in roles:
                return abort(403)  # Forbidden access
            return func(*args, **kwargs)
        return decorated_view
    return wrapper