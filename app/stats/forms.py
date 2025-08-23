from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, IntegerField, BooleanField, TextAreaField, FieldList, DateField, FormField, Form
from wtforms.fields.choices import SelectField
from wtforms.validators import ValidationError, DataRequired, NumberRange, Optional
from wtforms_sqlalchemy.fields import QuerySelectField
import sqlalchemy as sa
from app import db
from app.models import Player, Deck, Card


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
    player = SelectField('Player', choices=[])
    color_identity = SelectField('Color Identity', choices=[])
    partner = StringField('Partner')
    submit = SubmitField('Add Deck')

    def validate_name(self, name):
        name = db.session.scalar(sa.select(Deck).where(
            Deck.Name == name.data))
        if name is not None:
            raise ValidationError('Es gibt schon ein Deck mit diesem Namen.')

    def validate_commander(self, commander):
        commander = db.session.scalar(sa.select(Card).where(Card.Name == commander.data))
        if commander is None:
            raise ValidationError('Der Commander existiert nicht.')

# Define a subform for Player-related fields
class PlayerForm(Form):
    player = SelectField('Player', validate_choice=False)
    deck = SelectField('Deck', validate_choice=False)
    borrowed = BooleanField('Borrowed', default=False)
    lender = SelectField('Geliehen von', validate_choice=False)
    early_fast_mana = BooleanField('Early Fast Mana', default=False)

# Main GameAddForm
class GameAddForm(FlaskForm):
    winner = SelectField('Winner', choices=[])
    first = SelectField('First', choices=[])
    turns = IntegerField('Turns', validators=[Optional()])
    final_blow = TextAreaField('Final Blow', validators=[Optional()])
    first_ko_turn = IntegerField('First KO in Turn', validators=[Optional()])
    first_ko_by = TextAreaField('First KO by', validators=[Optional()])
    fun = IntegerField('Fun', validators=[Optional(), NumberRange(min=0, max=10)])
    mulligan = IntegerField('Mulligan', validators=[Optional(), NumberRange(min=0, max=7)])
    landdrops = IntegerField('Landdrops', validators=[Optional()])
    performance = IntegerField('Performance', validators=[Optional(), NumberRange(min=0, max=10)])
    comment = TextAreaField('Comment', validators=[Optional()])
    date = DateField('Date', format='%Y-%m-%d', validators=[DataRequired()])
    enough_mana = BooleanField('Genug Mana', default=False)
    enough_gas = BooleanField('Genug Möglichkeiten', default=False)
    deckplan = BooleanField('Deckplan umgesetzt', default=False)
    unanswered_threats = BooleanField('Unanswered Threats', default=False)
    loss_without_answer = BooleanField('Lockout/Loss ohne Antwort', default=False)
    selfmade_win = BooleanField('Selbst erspielter sieg', default=False)
    fun_moments = BooleanField('Fun Moments', default=False)
    planechase = BooleanField('Planechase', default=False)

    # Repeating fields for players, decks, and early fast mana
    players = FieldList(FormField(PlayerForm), min_entries=3, max_entries=5)

    # Submit button
    submit = SubmitField('Abschicken')

    # Add another player button (for dynamically adding players)
    add_player = SubmitField('Add another player')

    # Remove last player button (for dynamically removing players)
    remove_player = SubmitField('Remove last player')