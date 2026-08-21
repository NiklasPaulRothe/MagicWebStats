# Feature: raw-sql-to-orm, Property 11: Null-Safe Defaults
"""
Property test verifying that formatting functions substitute "-" for None
nullable numeric fields (winrate_pct, avg_win_turns) and None dates (last_played),
never outputting null or empty values.

**Validates: Requirements 9.3, 3.3, 4.4, 5.4**
"""
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st

from app.api.formatters import format_deck_data, format_user_deck
from app.api.queries import DeckDataResult, UserDeckResult


# ---------------------------------------------------------------------------
# Strategies for generating TypedDicts with None in nullable fields
# ---------------------------------------------------------------------------

# Strategy for DeckDataResult where winrate_pct is always None
deck_data_none_winrate_strategy = st.builds(
    lambda deck_name, player_name, commander, color_identity, games, wins, avg_win_turns, win_turns_count, decklist, elo, color_imgs, tags: DeckDataResult(
        deck_name=deck_name,
        player_name=player_name,
        commander=commander,
        color_identity=color_identity,
        games=games,
        wins=wins,
        winrate_pct=None,
        avg_win_turns=avg_win_turns,
        win_turns_count=win_turns_count,
        decklist=decklist,
        elo=elo,
        color_imgs=color_imgs,
        tags=tags,
    ),
    deck_name=st.text(min_size=1, max_size=50),
    player_name=st.text(min_size=1, max_size=50),
    commander=st.text(min_size=1, max_size=50),
    color_identity=st.text(min_size=1, max_size=20),
    games=st.integers(min_value=0, max_value=1000),
    wins=st.integers(min_value=0, max_value=1000),
    avg_win_turns=st.one_of(st.none(), st.floats(min_value=1.0, max_value=30.0, allow_nan=False)),
    win_turns_count=st.integers(min_value=0, max_value=1000),
    decklist=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
    elo=st.one_of(st.none(), st.floats(min_value=500.0, max_value=2000.0, allow_nan=False)),
    color_imgs=st.lists(st.text(min_size=1, max_size=30), max_size=5),
    tags=st.lists(st.text(min_size=1, max_size=20), max_size=5),
)

# Strategy for UserDeckResult where winrate_pct is always None
user_deck_none_winrate_strategy = st.builds(
    lambda name, commander, color_identity, games, last_played, wins, decklist, color_imgs, tags: UserDeckResult(
        name=name,
        commander=commander,
        color_identity=color_identity,
        games=games,
        last_played=last_played,
        wins=wins,
        winrate_pct=None,
        decklist=decklist,
        color_imgs=color_imgs,
        tags=tags,
    ),
    name=st.text(min_size=1, max_size=50),
    commander=st.text(min_size=1, max_size=50),
    color_identity=st.text(min_size=1, max_size=20),
    games=st.integers(min_value=0, max_value=1000),
    last_played=st.one_of(st.none(), st.dates(min_value=date(2000, 1, 1), max_value=date(2030, 12, 31))),
    wins=st.integers(min_value=0, max_value=1000),
    decklist=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
    color_imgs=st.lists(st.text(min_size=1, max_size=30), max_size=5),
    tags=st.lists(st.text(min_size=1, max_size=20), max_size=5),
)

# Strategy for UserDeckResult where last_played is always None
user_deck_none_last_played_strategy = st.builds(
    lambda name, commander, color_identity, games, wins, winrate_pct, decklist, color_imgs, tags: UserDeckResult(
        name=name,
        commander=commander,
        color_identity=color_identity,
        games=games,
        last_played=None,
        wins=wins,
        winrate_pct=winrate_pct,
        decklist=decklist,
        color_imgs=color_imgs,
        tags=tags,
    ),
    name=st.text(min_size=1, max_size=50),
    commander=st.text(min_size=1, max_size=50),
    color_identity=st.text(min_size=1, max_size=20),
    games=st.integers(min_value=0, max_value=1000),
    wins=st.integers(min_value=0, max_value=1000),
    winrate_pct=st.one_of(st.none(), st.floats(min_value=0.0, max_value=100.0, allow_nan=False)),
    decklist=st.one_of(st.none(), st.text(min_size=1, max_size=100)),
    color_imgs=st.lists(st.text(min_size=1, max_size=30), max_size=5),
    tags=st.lists(st.text(min_size=1, max_size=20), max_size=5),
)


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


@given(r=deck_data_none_winrate_strategy)
@settings(max_examples=100)
def test_format_deck_data_none_winrate_produces_dash(r: DeckDataResult):
    """Property 11: When winrate_pct is None in DeckDataResult,
    format_deck_data SHALL output "-" for "Winrate (in %)", never None or empty.
    """
    output = format_deck_data(r)

    winrate_value = output["Winrate (in %)"]

    # Value is wrapped in a single-element list
    assert isinstance(winrate_value, list), f"Expected list, got {type(winrate_value)}"
    assert len(winrate_value) == 1, f"Expected single-element list, got {len(winrate_value)} elements"

    # The actual value must be the dash string "-"
    assert winrate_value[0] == "-", (
        f"Expected '-' for None winrate_pct, got {winrate_value[0]!r}"
    )
    # Must never be None, "null", or empty string
    assert winrate_value[0] is not None
    assert winrate_value[0] != "null"
    assert winrate_value[0] != ""


@given(r=user_deck_none_winrate_strategy)
@settings(max_examples=100)
def test_format_user_deck_none_winrate_produces_dash(r: UserDeckResult):
    """Property 11: When winrate_pct is None in UserDeckResult,
    format_user_deck SHALL output "-" for "Winrate (in %)", never None or empty.
    """
    output = format_user_deck(r)

    winrate_value = output["Winrate (in %)"]

    # Value is wrapped in a single-element list
    assert isinstance(winrate_value, list), f"Expected list, got {type(winrate_value)}"
    assert len(winrate_value) == 1, f"Expected single-element list, got {len(winrate_value)} elements"

    # The actual value must be the dash string "-"
    assert winrate_value[0] == "-", (
        f"Expected '-' for None winrate_pct, got {winrate_value[0]!r}"
    )
    # Must never be None, "null", or empty string
    assert winrate_value[0] is not None
    assert winrate_value[0] != "null"
    assert winrate_value[0] != ""


@given(r=user_deck_none_last_played_strategy)
@settings(max_examples=100)
def test_format_user_deck_none_last_played_produces_dash(r: UserDeckResult):
    """Property 11: When last_played is None in UserDeckResult,
    format_user_deck SHALL output "-" for "Zuletzt gespielt", never None or empty.
    """
    output = format_user_deck(r)

    last_played_value = output["Zuletzt gespielt"]

    # Value is wrapped in a single-element list
    assert isinstance(last_played_value, list), f"Expected list, got {type(last_played_value)}"
    assert len(last_played_value) == 1, f"Expected single-element list, got {len(last_played_value)} elements"

    # The actual value must be the dash string "-"
    assert last_played_value[0] == "-", (
        f"Expected '-' for None last_played, got {last_played_value[0]!r}"
    )
    # Must never be None, "null", or empty string
    assert last_played_value[0] is not None
    assert last_played_value[0] != "null"
    assert last_played_value[0] != ""
