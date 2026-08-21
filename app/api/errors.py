"""JSON error handlers for the API blueprint.

These are registered as app-wide error handlers that check the request path
to ensure API routes always return JSON responses instead of HTML error pages.
"""

from flask import jsonify, request
from app import db
from app.api import bp


@bp.app_errorhandler(404)
def not_found_error(error):
    if request.path.startswith('/api/'):
        return jsonify({"error": "Not found"}), 404
    # Let non-API routes fall through to the default handler
    return error


@bp.app_errorhandler(500)
def internal_error(error):
    if request.path.startswith('/api/'):
        db.session.rollback()
        return jsonify({"error": "Internal server error"}), 500
    return error
