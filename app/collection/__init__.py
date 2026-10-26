from flask import Blueprint

bp = Blueprint('collection', __name__)

from app.collection import routes  # noqa: E402,F401
