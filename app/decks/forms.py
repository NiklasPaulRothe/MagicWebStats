from flask_wtf import FlaskForm
from wtforms.fields.simple import StringField, SubmitField, HiddenField, BooleanField, TextAreaField
from wtforms.validators import DataRequired, Optional, ValidationError
import sqlalchemy as sa

from app import db
from app.models import Deck

# NOTE: DB queries in form validators is an intentional WTForms pattern.
# Uniqueness checks run during validation to provide immediate user feedback.


class DeckEditForm(FlaskForm):
    current_name = HiddenField()
    name = StringField('Name', validators=[DataRequired()])
    decklist = StringField('Link', validators=[Optional()])
    version_comment = TextAreaField('Version Change Comment', validators=[Optional()])
    submit = SubmitField('Deck ändern')
    archive_button = SubmitField('Archivieren')
    version_changed = SubmitField('Deck Changed')
    version_patched = SubmitField('Deck Patched')
    version_reworked = SubmitField('Deck Reworked')

    def validate_name(self, name):
        deckname = db.session.scalar(sa.select(Deck).where(
            Deck.name == name.data))
        if deckname is not None and deckname.name != self.current_name.data:
            raise ValidationError('Es gibt schon ein Deck mit diesem Namen.')