from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db
from config import Config

DB_SCHEMA = Config.DB_SCHEMA


class ColorUsage(db.Model):
    __tablename__ = 'v_color_usage'
    __table_args__ = {'info': dict(is_view=True), 'schema': DB_SCHEMA}

    color: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    likelihood: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    average: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    deck_percentage: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)


class ColorUsagePlayer(db.Model):
    __tablename__ = 'v_color_usage_player'
    __table_args__ = {'info': dict(is_view=True), 'schema': DB_SCHEMA}

    Player: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    Decks: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    white: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    blue: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    black: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    red: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    green: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)
    avg_number_of_colors: so.Mapped[Optional[float]] = so.mapped_column(sa.Float)


class PlayerPrintingAvailability(db.Model):
    """Read-only view: per (player, printing, finish, language) how many copies
    are owned vs. claimed by decks, with an over-claimed flag.

    Mirrors magic_stats_owner.v_player_printing_availability. The composite
    natural key is (player_id, card_id, finish_key, language_key)."""

    __tablename__ = 'v_player_printing_availability'
    __table_args__ = {'info': dict(is_view=True), 'schema': DB_SCHEMA}

    player_id: so.Mapped[int] = so.mapped_column(sa.Integer, primary_key=True)
    card_id: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    finish_key: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    language_key: so.Mapped[str] = so.mapped_column(sa.String, primary_key=True)
    owned_count: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    claimed_count: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    over_claimed: so.Mapped[Optional[bool]] = so.mapped_column(sa.Boolean)


class DeckCardCollectionStatus(db.Model):
    """Read-only view: resolved collection status per deck component.

    Mirrors magic_stats_owner.v_deck_card_collection_status. ``status`` is one
    of: in_deck_ok, in_deck_faulty, proxy, available, owned_no_copy,
    owned_other, not_owned."""

    __tablename__ = 'v_deck_card_collection_status'
    __table_args__ = {'info': dict(is_view=True), 'schema': DB_SCHEMA}

    deck_component_id: so.Mapped[int] = so.mapped_column(sa.Integer, primary_key=True)
    deck_id: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    player_id: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    card_id: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    physical_status: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    physical_finish: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    physical_language: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
    owned_count: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    claimed_count: so.Mapped[Optional[int]] = so.mapped_column(sa.Integer)
    status: so.Mapped[Optional[str]] = so.mapped_column(sa.String)
