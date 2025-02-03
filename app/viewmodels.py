from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask_login import UserMixin
from flask_security import RoleMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db

class ColorUsage(db.Model):
  __tablename__ = 'v_color_usage'
  __table_args__ = {'info': dict(is_view=True), 'schema': 'data_owner'}
  color = db.Column(db.String, primary_key=True)
  likelihood = db.Column(db.Float)
  average = db.Column(db.Float)
  deck_percentage = db.Column(db.Float)

class ColorUsagePlayer(db.Model):
  __tablename__ = 'v_color_usage_player'
  __table_args__ = {'info': dict(is_view=True), 'schema': 'data_owner'}
  Player = db.Column(db.String, primary_key=True)
  Decks = db.Column(db.Integer)
  white = db.Column(db.Float)
  blue = db.Column(db.Float)
  black = db.Column(db.Float)
  red = db.Column(db.Float)
  green = db.Column(db.Float)
  avg_number_of_colors = db.Column(db.Float)