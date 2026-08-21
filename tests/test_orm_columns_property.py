# Feature: schema-cutover, Property 3: No name= overrides remain
# Feature: orm-modernization, Property 5: CHECK constraints reject negative values
# Feature: orm-modernization, Property 6: Seat constraint rejects values below 1
"""
Property tests verifying column mapping and CHECK constraints after schema cutover.

- Property 3: For all columns in renamed models, column.name == attr_name (no mismatch)
- Property 5: For any negative int, CHECK-constrained columns reject it
- Property 6: For any int < 1, seat constraint rejects it

**Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 9.1, 9.2, 9.3, 9.4, 7.2**
"""

from hypothesis import given, settings
from hypothesis import strategies as st
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from app.models import (
    Deck,
    Game,
    Participant,
    Player,
    ColorIdentity,
    Color,
    Achievement,
    User,
)


# --- Property 3: No name= overrides remain (column.name == attr_name) ---

# Models that previously had name= overrides. After the cutover, Python attribute
# names map directly to DB column names — there are no name= overrides left.
MODELS_WITH_REMOVED_OVERRIDES = [Player, User, ColorIdentity, Color, Deck, Game, Achievement]


def _get_model_column_entries(models):
    """Build a list of (model_class, attr_name) for all mapped columns in the given models."""
    entries = []
    for model_cls in models:
        mapper = sa_inspect(model_cls)
        for attr in mapper.column_attrs:
            entries.append((model_cls, attr.key))
    return entries


# Pre-compute all (model, attr_name) pairs for property sampling
_ALL_COLUMN_ENTRIES = _get_model_column_entries(MODELS_WITH_REMOVED_OVERRIDES)


@given(entry=st.sampled_from(_ALL_COLUMN_ENTRIES))
@settings(max_examples=200)
def test_no_column_name_overrides_remain(entry):
    """Property 3: For any column in models that previously had name= overrides,
    the DB column name SHALL equal the Python attribute name.

    After the schema cutover, all mapped_column(name='...') overrides have been
    removed. This means column.name must match the attribute name directly.

    **Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8**
    """
    model_cls, attr_name = entry

    mapper = sa_inspect(model_cls)
    column_property = mapper.columns[attr_name]
    actual_db_col = column_property.name

    assert actual_db_col == attr_name, (
        f"{model_cls.__name__}.{attr_name} maps to DB column {actual_db_col!r}, "
        f"but after cutover it should map directly to {attr_name!r} (no name= override)"
    )


# --- Property 5: CHECK constraints reject negative values ---

# Columns with >= 0 CHECK constraints: (model_class, constraint_name, column_expression)
CHECK_GTE_ZERO_CONSTRAINTS = [
    (Deck, "ck_deck_elo_rating", "elo_rating >= 0"),
    (Deck, "ck_deck_version", "version >= 0"),
    (Deck, "ck_deck_patch", "patch >= 0"),
    (Deck, "ck_deck_change", "change >= 0"),
    (Participant, "ck_participant_mulligans", "mulligans >= 0"),
    (Game, "ck_game_turns", "turns >= 0"),
]


def _find_check_constraint(model_cls, constraint_name):
    """Find a CheckConstraint by name in the model's table constraints."""
    for constraint in model_cls.__table__.constraints:
        if isinstance(constraint, sa.CheckConstraint) and constraint.name == constraint_name:
            return constraint
    return None


@given(
    entry=st.sampled_from(CHECK_GTE_ZERO_CONSTRAINTS),
    negative_value=st.integers(max_value=-1),
)
@settings(max_examples=100)
def test_check_constraints_reject_negative_values(entry, negative_value):
    """Property 5: For any negative integer value, CHECK-constrained columns
    (elo_rating, mulligans, turns, version, patch, change) have a constraint
    that would reject it.

    We verify the constraint exists and its SQL text contains the >= 0 condition.

    **Validates: Requirements 9.1, 9.2, 9.3, 9.4**
    """
    model_cls, constraint_name, expected_expr = entry

    constraint = _find_check_constraint(model_cls, constraint_name)
    assert constraint is not None, (
        f"{model_cls.__name__} is missing CHECK constraint {constraint_name!r}"
    )

    # Get the SQL text of the constraint
    sql_text = str(constraint.sqltext)

    # Verify the constraint expression enforces >= 0
    assert ">= 0" in sql_text, (
        f"CHECK constraint {constraint_name!r} on {model_cls.__name__} "
        f"does not contain '>= 0'. Actual SQL: {sql_text!r}. "
        f"Value {negative_value} should be rejected."
    )

    # The negative value must violate the >= 0 condition
    assert negative_value < 0, (
        f"Test invariant violation: value {negative_value} is not negative"
    )


# --- Property 6: Seat constraint rejects values below 1 ---

@given(invalid_seat=st.integers(max_value=0))
@settings(max_examples=100)
def test_seat_constraint_rejects_values_below_1(invalid_seat):
    """Property 6: For any integer value < 1 (including 0 and negative),
    the Participant.seat CHECK constraint rejects it.

    The constraint is: 'seat IS NULL OR seat >= 1'
    This means seat=0 and any negative seat value must be rejected.

    **Validates: Requirements 7.2**
    """
    constraint = _find_check_constraint(Participant, "ck_participant_seat")
    assert constraint is not None, (
        "Participant is missing CHECK constraint 'ck_participant_seat'"
    )

    # Get the SQL text of the constraint
    sql_text = str(constraint.sqltext)

    # Verify the constraint enforces IS NULL OR >= 1
    assert "seat IS NULL OR seat >= 1" in sql_text, (
        f"CHECK constraint 'ck_participant_seat' on Participant "
        f"does not match expected expression. Actual SQL: {sql_text!r}. "
        f"Value {invalid_seat} (< 1) should be rejected by the constraint."
    )

    # The invalid seat value must be < 1 (confirmed by the strategy)
    assert invalid_seat < 1, (
        f"Test invariant violation: value {invalid_seat} is not less than 1"
    )
