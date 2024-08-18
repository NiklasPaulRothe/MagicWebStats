from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, BooleanField, TextAreaField, FieldList, DateField, FormField, Form
from wtforms.validators import ValidationError, DataRequired, NumberRange, Optional
import sqlalchemy as sa
from app import db
from app.models import Player, Deck

class PlayerAddForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    submit = SubmitField('Add Player')

    def validate_name(self, name):
        player = db.session.scalar(sa.select(Player).where(
            Player.Name == name.data))
        if player is not None:
            raise ValidationError('Ein User mit diesem Namen existiert bereits.')

class DeckAddForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    commander = StringField('Commander', validators=[DataRequired()])
    player = StringField('Player', validators=[DataRequired()])
    color_identity = StringField('Color_Identity', validators=[DataRequired()])
    partner = StringField('Partner')
    submit = SubmitField('Add Deck')

    def validate_name(self, name):
        name = db.session.scalar(sa.select(Deck).where(
            Deck.Name == name.data))
        if name is not None:
            raise ValidationError('Es gibt schon ein Deck mit diesem Namen.')

# Define a subform for Player-related fields
class PlayerForm(Form):
    player = StringField('Player', validators=[DataRequired()])
    deck = StringField('Deck', validators=[DataRequired()])
    early_fast_mana = BooleanField('Early Fast Mana', default=False)

# Main GameAddForm
class GameAddForm(FlaskForm):
    winner = StringField('Winner', validators=[DataRequired()])
    first = StringField('First', validators=[DataRequired()])
    fun = IntegerField('Fun', validators=[DataRequired(), NumberRange(min=0, max=10)])
    mulligan = IntegerField('Mulligan', validators=[DataRequired(), NumberRange(min=0, max=7)])
    performance = IntegerField('Performance', validators=[DataRequired(), NumberRange(min=0, max=10)])
    comment = TextAreaField('Comment', validators=[Optional()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    planechase = BooleanField('Planechase', default=False)

    # Repeating fields for players, decks, and early fast mana
    players = FieldList(FormField(PlayerForm), min_entries=3, max_entries=5)

    # Submit button
    submit = SubmitField('Submit')

    # Add another player button (for dynamically adding players)
    add_player = SubmitField('Add another player')

    # Remove last player button (for dynamically removing players)
    remove_player = SubmitField('Remove last player')