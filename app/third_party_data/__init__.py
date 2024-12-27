from flask import Blueprint

bp = Blueprint('stats', __name__)

from app.third_party_data import scryfall