# Feature: schema-cutover, Property 1: Schema configuration consistency
# Feature: schema-cutover, Property 2: Table name correctness
# Feature: orm-modernization, Property 2: All models use SA2 style exclusively
"""
Property tests verifying ORM model structure after schema cutover.

- Property 1: For any model class, __table_args__ schema equals DB_SCHEMA ('magic_stats_owner')
- Property 2: For any model, all columns are MappedColumn instances (not legacy Column)
- Property 3: For any model, __tablename__ matches expected snake_case name

**Validates: Requirements 9.2, 9.3**
"""
import typing

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Mapped

from app.models import (
    DB_SCHEMA,
    User,
    ColorIdentity,
    Color,
    Deck,
    Game,
    Participant,
    Player,
    ColorComponent,
    Card,
    CardFace,
    CardColor,
    CardColorIdentity,
    CardKeyword,
    CardLegality,
    OracleTag,
    DeckComponent,
    Achievement,
    DeckVersionHistory,
    DeckTag,
    AuditLog,
)
from app.viewmodels import (
    ColorUsage,
    ColorUsagePlayer,
)

# All model classes in the Model_Layer
ALL_MODELS = [
    User,
    ColorIdentity,
    Color,
    Deck,
    Game,
    Participant,
    Player,
    ColorComponent,
    Card,
    CardFace,
    CardColor,
    CardColorIdentity,
    CardKeyword,
    CardLegality,
    OracleTag,
    DeckComponent,
    Achievement,
    DeckVersionHistory,
    DeckTag,
    AuditLog,
    ColorUsage,
    ColorUsagePlayer,
]

# Expected table names (snake_case names under magic_stats_owner schema)
EXPECTED_TABLE_NAMES = {
    User: "users",
    ColorIdentity: "color_identities",
    Color: "colors",
    Deck: "decks",
    Game: "games",
    Participant: "participants",
    Player: "players",
    ColorComponent: "color_components",
    Card: "cards",
    CardFace: "card_faces",
    CardColor: "card_colors",
    CardColorIdentity: "card_color_identity",
    CardKeyword: "card_keywords",
    CardLegality: "card_legalities",
    OracleTag: "oracle_tags",
    DeckComponent: "deck_component",
    Achievement: "achievements",
    DeckVersionHistory: "deck_version_history",
    DeckTag: "deck_tags",
    AuditLog: "audit_log",
    ColorUsage: "v_color_usage",
    ColorUsagePlayer: "v_color_usage_player",
}


def _extract_schema(model_cls):
    """Extract schema value from __table_args__, handling both dict and tuple forms."""
    table_args = getattr(model_cls, '__table_args__', None)
    if table_args is None:
        return None
    if isinstance(table_args, dict):
        return table_args.get('schema')
    if isinstance(table_args, tuple):
        # Last element is the dict with schema info
        for item in reversed(table_args):
            if isinstance(item, dict):
                return item.get('schema')
    return None


def _get_column_attributes(model_cls):
    """Get all column-mapped attributes from a model class via SQLAlchemy inspection."""
    mapper = model_cls.__mapper__
    return list(mapper.column_attrs)


# --- Property 1: Schema configuration consistency ---

@given(model_cls=st.sampled_from(ALL_MODELS))
@settings(max_examples=100)
def test_schema_configuration_consistency(model_cls):
    """Property 1: For any model class, __table_args__ schema equals DB_SCHEMA.

    **Validates: Requirements 9.3**
    """
    schema = _extract_schema(model_cls)
    assert schema == DB_SCHEMA, (
        f"{model_cls.__name__}.__table_args__ schema is {schema!r}, "
        f"expected {DB_SCHEMA!r}"
    )


# --- Property 2: All models use SA2 style exclusively ---

@given(model_cls=st.sampled_from(ALL_MODELS))
@settings(max_examples=100)
def test_all_models_use_sa2_style(model_cls):
    """Property 2: For any model, all columns use SA2 Mapped[] annotations.

    In SA2 style, every column attribute is declared with a so.Mapped[type]
    annotation and so.mapped_column(). This test verifies that every column
    property in the mapper has a corresponding Mapped[...] type annotation
    on the model class.

    **Validates: Requirements 2.1**
    """
    annotations = getattr(model_cls, '__annotations__', {})
    for attr in _get_column_attributes(model_cls):
        # Every mapped column attribute must have a Mapped[...] annotation
        assert attr.key in annotations, (
            f"{model_cls.__name__}.{attr.key} has no type annotation — "
            f"likely uses legacy db.Column() style instead of SA2 mapped_column()"
        )
        ann_type = annotations[attr.key]
        origin = typing.get_origin(ann_type)
        assert origin is Mapped, (
            f"{model_cls.__name__}.{attr.key} annotation is {ann_type!r}, "
            f"expected so.Mapped[...] (SA2 style)"
        )


# --- Property 4: Table names are unchanged ---

@given(model_cls=st.sampled_from(ALL_MODELS))
@settings(max_examples=100)
def test_table_names_unchanged(model_cls):
    """Property 2: For any model, __tablename__ matches expected snake_case name.

    **Validates: Requirements 9.2, 9.3**
    """
    expected = EXPECTED_TABLE_NAMES[model_cls]
    actual = model_cls.__tablename__
    assert actual == expected, (
        f"{model_cls.__name__}.__tablename__ is {actual!r}, "
        f"expected {expected!r}"
    )
