from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask_login import UserMixin
from flask_security import RoleMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db, login


@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))

class User(UserMixin, db.Model):
    __table_args__ = {'schema': 'data_owner'}
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True,
                                                unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True,
                                             unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
    spieler: so.Mapped[int] = so.mapped_column(sa.Integer)
    active: so.Mapped[bool] = so.mapped_column(sa.Boolean)
    role: so.Mapped[str] = so.mapped_column(sa.String(64))

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Role(db.Model, RoleMixin):
    __tablename__ = 'Role'
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(50), unique=True)

class UserRoles(db.Model):
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), db.ForeignKey('user.id'))
    role_id = db.Column(db.Integer(), db.ForeignKey('Role.id'))

class ColorIdentity(db.Model):
    __tablename__ = 'Color_Identities'
    __table_args__ = {'schema': 'data_owner'}
    Name = db.Column(db.String, primary_key=True)
    amount = db.Column(db.Integer, nullable=False)

class Color(db.Model):
    __tablename__ = 'Colors'
    __table_args__ = {'schema': 'data_owner'}
    Name = db.Column(db.String, primary_key=True)
    abbreviation = db.Column(db.String, nullable=False)

class Deck(db.Model):
    __tablename__ = 'Decks'
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer, primary_key=True)
    Name = db.Column(db.String, nullable=False)
    Active = db.Column(db.Boolean, nullable = False, default = True)
    Commander = db.Column(db.String, nullable=False)
    Player = db.Column(db.Integer, db.ForeignKey('data_owner.Player.id'), nullable=False)
    Color_Identity = db.Column(db.String, db.ForeignKey('data_owner.Color_Identities.Name'), nullable=False)
    Partner = db.Column(db.String)
    elo_rating = db.Column(db.Float, default=1500)  # New column to store Elo rating
    decklist = db.Column(db.String)
    decksite = db.Column(db.String)
    archidekt_id = db.Column(db.String)
    image_uri = db.Column(db.String)

class Game(db.Model):
    __tablename__ = 'Games'
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer, primary_key=True)
    Date = db.Column(db.Date, nullable=False)
    First_Player = db.Column(db.Integer)
    Winner = db.Column(db.Integer)
    Planechase = db.Column(db.Boolean, nullable=False, default=False)
    turns = db.Column(db.Integer)
    final_blow = db.Column(db.String)
    first_ko_turn = db.Column(db.Integer)
    first_ko_by = db.Column(db.String)

class Participant(db.Model):
    __tablename__ = 'Participants'
    __table_args__ = {'schema': 'data_owner'}
    game_id = db.Column(db.Integer, db.ForeignKey('data_owner.Games.id'), primary_key=True)
    player_id = db.Column(db.Integer, db.ForeignKey('data_owner.Player.id'), primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('data_owner.Decks.id'), nullable=False)
    early_sol_ring = db.Column(db.Boolean, nullable=False, default=False)
    fun = db.Column(db.Integer)
    performance = db.Column(db.Integer)
    mulligans = db.Column(db.Integer)
    comments = db.Column(db.String)
    landdrops = db.Column(db.Integer)
    enough_mana = db.Column(db.Boolean)
    enough_gas = db.Column(db.Boolean)
    deckplan = db.Column(db.Boolean)
    unanswered_threats = db.Column(db.Boolean)
    loss_without_answer = db.Column(db.Boolean)
    selfmade_win = db.Column(db.Boolean)

class Player(db.Model):
    __tablename__ = 'Player'
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer, primary_key=True)
    Name = db.Column(db.String, nullable=False)

class ColorComponent(db.Model):
    __tablename__ = 'color_components'
    __table_args__ = {'schema': 'data_owner'}
    color_identity = db.Column(db.String, db.ForeignKey('data_owner.Color_Identities.Name'), primary_key=True)
    color = db.Column(db.String, db.ForeignKey('data_owner.Colors.Name'), primary_key=True)

class Card(db.Model):
    __tablename__ = 'card_data'
    __table_args__ = {'schema': 'data_owner'}
    Name = db.Column(db.String)
    id = db.Column(db.String, primary_key=True)
    image_uri = db.Column(db.String)
    back_image_uri = db.Column(db.String)
    commander_legal = db.Column(db.Boolean, nullable=False, default=False)
    cmc = db.Column(db.Integer)
    card_text = db.Column(db.String)
    back_card_text = db.Column(db.String)

class DeckComponent(db.Model):
    __tablename__ = 'deck_component'
    __table_args__ = {'schema': 'data_owner'}
    id = db.Column(db.Integer, primary_key=True)
    deck_id = db.Column(db.Integer, db.ForeignKey('data_owner.Decks.id'))
    card_id = db.Column(db.String, db.ForeignKey('data_owner.card_data.id'))
    count = db.Column(db.Integer)
    name = db.Column(db.String)
