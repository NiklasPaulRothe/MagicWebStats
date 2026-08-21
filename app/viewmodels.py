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
