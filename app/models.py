from datetime import datetime
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db, login
from config import Config

DB_SCHEMA = Config.DB_SCHEMA


@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    __table_args__ = {'schema': DB_SCHEMA}
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True,
                                                unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True,
                                             unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
    player_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.players.id', ondelete='SET NULL'),
    )
    active: so.Mapped[bool] = so.mapped_column(sa.Boolean)
    role: so.Mapped[str] = so.mapped_column(sa.String(64))

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ColorIdentity(db.Model):
    __tablename__ = 'color_identities'
    __table_args__ = {'schema': DB_SCHEMA}

    name: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    amount: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)

class Color(db.Model):
    __tablename__ = 'colors'
    __table_args__ = {'schema': DB_SCHEMA}

    name: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    abbreviation: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    img: so.Mapped[Optional[str]] = so.mapped_column(sa.String)

class Deck(db.Model):
    __tablename__ = 'decks'
    __table_args__ = (
        sa.CheckConstraint('elo_rating >= 0', name='ck_deck_elo_rating'),
        sa.CheckConstraint('version >= 0', name='ck_deck_version'),
        sa.CheckConstraint('patch >= 0', name='ck_deck_patch'),
        sa.CheckConstraint('change >= 0', name='ck_deck_change'),
        {'schema': DB_SCHEMA}
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    active: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    commander: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    player_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.players.id', ondelete='RESTRICT'),
        nullable=False
    )
    color_identity: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.color_identities.name', ondelete='RESTRICT'),
        nullable=False
    )
    partner: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    elo_rating: so.Mapped[Optional[float]] = so.mapped_column(sa.Float, default=1500)
    decklist: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    decksite: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    archidekt_id: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    image_uri: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    last_rework: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.Date, default=sa.func.current_date()
    )
    last_change: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.Date, default=sa.func.current_date()
    )
    last_patch: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.Date, default=sa.func.current_date()
    )
    cedh: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean, default=False)
    version: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer, default=0
    )
    patch: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer, default=0)
    change: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer, default=0)
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relationships
    player_rel: so.Mapped['Player'] = so.relationship(back_populates='decks')
    participations: so.Mapped[list['Participant']] = so.relationship(back_populates='deck')
    version_history: so.Mapped[list['DeckVersionHistory']] = so.relationship(back_populates='deck_rel')
    achievements: so.Mapped[list['Achievement']] = so.relationship(back_populates='deck_rel')
    tags: so.Mapped[list['DeckTag']] = so.relationship(back_populates='deck_rel')
    components: so.Mapped[list['DeckComponent']] = so.relationship(back_populates='deck_rel')

class Game(db.Model):
    __tablename__ = 'games'
    __table_args__ = (
        sa.CheckConstraint('turns >= 0', name='ck_game_turns'),
        {'schema': DB_SCHEMA}
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    date: so.Mapped[datetime] = so.mapped_column(sa.Date, nullable=False)
    first_player_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.players.id', ondelete='RESTRICT'),
    )
    winner_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.players.id', ondelete='RESTRICT'),
    )
    planechase: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=False)
    turns: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    final_blow: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    first_ko_turn: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    first_ko_by: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    cedh: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean, default=False)
    added_by_user_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.users.id', ondelete='SET NULL')
    )
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relationships
    participants: so.Mapped[list['Participant']] = so.relationship(back_populates='game')

class Participant(db.Model):
    __tablename__ = 'participants'
    __table_args__ = (
        sa.CheckConstraint('seat IS NULL OR seat >= 1', name='ck_participant_seat'),
        sa.CheckConstraint('mulligans >= 0', name='ck_participant_mulligans'),
        {'schema': DB_SCHEMA}
    )

    game_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.games.id', ondelete='RESTRICT'),
        primary_key=True
    )
    player_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.players.id', ondelete='RESTRICT'),
        primary_key=True
    )
    deck_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.decks.id', ondelete='RESTRICT'),
        nullable=False
    )
    seat: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    early_sol_ring: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=False)
    mulligans: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    comments: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    landdrops: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    lands: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    enough_mana: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    enough_gas: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    deckplan: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    unanswered_threats: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    loss_without_answer: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    selfmade_win: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    fun_moments: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)
    removal_played: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    targeted_by_removal: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    protection_played: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relationships
    game: so.Mapped['Game'] = so.relationship(back_populates='participants')
    player_rel: so.Mapped['Player'] = so.relationship(back_populates='participations')
    deck: so.Mapped['Deck'] = so.relationship(back_populates='participations')

class Player(db.Model):
    __tablename__ = 'players'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relationships (forward references to not-yet-migrated models)
    decks: so.Mapped[list['Deck']] = so.relationship(back_populates='player_rel')
    participations: so.Mapped[list['Participant']] = so.relationship(back_populates='player_rel')

class ColorComponent(db.Model):
    __tablename__ = 'color_components'
    __table_args__ = {'schema': DB_SCHEMA}

    color_identity: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.color_identities.name'),
        primary_key=True
    )
    color: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.colors.name'),
        primary_key=True
    )

class Card(db.Model):
    __tablename__ = 'cards'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    oracle_id: so.Mapped[str] = so.mapped_column(sa.String, nullable=False, index=True)
    name: so.Mapped[str] = so.mapped_column(sa.String, nullable=False, index=True)
    mana_cost: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    cmc: so.Mapped[float] = so.mapped_column(sa.Float, nullable=False, default=0)
    type_line: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    oracle_text: so.Mapped[Optional[str]] = so.mapped_column(sa.Text)
    layout: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    set_code: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    set_name: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    rarity: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    released_at: so.Mapped[Optional[datetime]] = so.mapped_column(sa.Date)

    # Relationships
    faces: so.Mapped[list['CardFace']] = so.relationship(back_populates='card', order_by='CardFace.face_index', cascade='all, delete-orphan')
    colors: so.Mapped[list['CardColor']] = so.relationship(back_populates='card', cascade='all, delete-orphan')
    color_identity: so.Mapped[list['CardColorIdentity']] = so.relationship(back_populates='card', cascade='all, delete-orphan')
    keywords: so.Mapped[list['CardKeyword']] = so.relationship(back_populates='card', cascade='all, delete-orphan')
    legalities: so.Mapped[list['CardLegality']] = so.relationship(back_populates='card', cascade='all, delete-orphan')

    @property
    def oracle_tags(self):
        return OracleTag.query.filter_by(oracle_id=self.oracle_id).all()


class CardFace(db.Model):
    __tablename__ = 'card_faces'
    __table_args__ = (
        sa.UniqueConstraint('card_id', 'face_index', name='uq_card_face'),
        {'schema': DB_SCHEMA}
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    card_id: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id', ondelete='CASCADE'),
        nullable=False
    )
    face_index: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    name: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    mana_cost: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    type_line: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    oracle_text: so.Mapped[Optional[str]] = so.mapped_column(sa.Text)
    image_uri: so.Mapped[Optional[str]] = so.mapped_column(sa.String)

    # Relationship
    card: so.Mapped['Card'] = so.relationship(back_populates='faces')


class CardColor(db.Model):
    __tablename__ = 'card_colors'
    __table_args__ = {'schema': DB_SCHEMA}

    card_id: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id', ondelete='CASCADE'),
        primary_key=True
    )
    color: so.Mapped[str] = so.mapped_column(sa.String(1), primary_key=True)

    # Relationship
    card: so.Mapped['Card'] = so.relationship(back_populates='colors')


class CardColorIdentity(db.Model):
    __tablename__ = 'card_color_identity'
    __table_args__ = {'schema': DB_SCHEMA}

    card_id: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id', ondelete='CASCADE'),
        primary_key=True
    )
    color: so.Mapped[str] = so.mapped_column(sa.String(1), primary_key=True)

    # Relationship
    card: so.Mapped['Card'] = so.relationship(back_populates='color_identity')


class CardKeyword(db.Model):
    __tablename__ = 'card_keywords'
    __table_args__ = {'schema': DB_SCHEMA}

    card_id: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id', ondelete='CASCADE'),
        primary_key=True
    )
    keyword: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)

    # Relationship
    card: so.Mapped['Card'] = so.relationship(back_populates='keywords')


class CardLegality(db.Model):
    __tablename__ = 'card_legalities'
    __table_args__ = {'schema': DB_SCHEMA}

    card_id: so.Mapped[str] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id', ondelete='CASCADE'),
        primary_key=True
    )
    format: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    status: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)

    # Relationship
    card: so.Mapped['Card'] = so.relationship(back_populates='legalities')


class OracleTag(db.Model):
    __tablename__ = 'oracle_tags'
    __table_args__ = (
        sa.UniqueConstraint('oracle_id', 'tag', name='uq_oracle_tag'),
        {'schema': DB_SCHEMA}
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    oracle_id: so.Mapped[str] = so.mapped_column(sa.String, nullable=False, index=True)
    tag: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)


class DeckComponent(db.Model):
    __tablename__ = 'deck_component'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    deck_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.decks.id', ondelete='CASCADE')
    )
    card_id: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String,
        sa.ForeignKey(f'{DB_SCHEMA}.cards.id')
    )
    count: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    name: so.Mapped[Optional[str]] = so.mapped_column(sa.String)

    # Relationship
    deck_rel: so.Mapped['Deck'] = so.relationship(back_populates='components')

class Achievement(db.Model):
    __tablename__ = 'achievements'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    title: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    amount: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    deck_id: so.Mapped[Optional[int]] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.decks.id', ondelete='CASCADE'),
    )
    achieved: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)

    # Relationship
    deck_rel: so.Mapped['Deck'] = so.relationship(back_populates='achievements')

class DeckVersionHistory(db.Model):
    __tablename__ = 'deck_version_history'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    deck_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.decks.id', ondelete='CASCADE'),
        nullable=False
    )
    change_type: so.Mapped[str] = so.mapped_column(sa.String(20), nullable=False)
    previous_version: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    previous_patch: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    previous_change: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    new_version: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    new_patch: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    new_change: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    comment: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    timestamp: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, nullable=False, default=sa.func.current_timestamp()
    )

    # Relationship
    deck_rel: so.Mapped['Deck'] = so.relationship(back_populates='version_history')

class DeckTag(db.Model):
    __tablename__ = 'deck_tags'
    __table_args__ = (
        sa.UniqueConstraint('deck_id', 'tag', name='unique_deck_tag'),
        {'schema': DB_SCHEMA}
    )

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    deck_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.decks.id', ondelete='CASCADE'),
        nullable=False
    )
    tag: so.Mapped[str] = so.mapped_column(sa.String(255), nullable=False)
    created_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, default=sa.func.current_timestamp()
    )

    # Relationship
    deck_rel: so.Mapped['Deck'] = so.relationship(back_populates='tags')


class AuditLog(db.Model):
    __tablename__ = 'audit_log'
    __table_args__ = {'schema': DB_SCHEMA}

    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    timestamp: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, nullable=False, default=sa.func.current_timestamp()
    )
    user_id: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        sa.ForeignKey(f'{DB_SCHEMA}.users.id'),
        nullable=False
    )
    username: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    action: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    entity_type: so.Mapped[str] = so.mapped_column(sa.String, nullable=False)
    entity_id: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    details: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
