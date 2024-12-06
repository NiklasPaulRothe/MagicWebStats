from flask_wtf import FlaskForm
from wtforms.fields.simple import StringField, SubmitField
from wtforms.validators import DataRequired, Optional


class DeckEditForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired()])
    decklist = StringField('Link', validators=[Optional()])
    submit = SubmitField('Deck ändern')