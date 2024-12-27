from flask import Blueprint

bp = Blueprint('third_party', __name__)

from app.third_party_data import scryfall
from app.third_party_data import deckbuilder