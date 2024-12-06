from flask_wtf import FlaskForm
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, Optional, ValidationError
import sqlalchemy as sa

from app import db
from app.models import Deck


class DeckEditForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    decklist = StringField('Link', validators=[Optional()])
    submit = SubmitField('Deck ändern')

    def validate_name(self, name):
        name = db.session.scalar(sa.select(Deck).where(
            Deck.Name == name.data))
        if name is not None:
            raise ValidationError('Es gibt schon ein Deck mit diesem Namen.')