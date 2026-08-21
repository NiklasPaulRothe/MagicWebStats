# Feature: api-frontend-normalization, Property: Null-Safe Defaults
"""
Property test verifying that formatting functions produce None (JSON null)
for nullable fields (winrate_pct, last_played) when the input value is None.
No dash substitution — None in means None out.

**Validates: Requirements 1.3**
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
def test_format_deck_data_none_winrate_produces_null(r: DeckDataResult):
    """Property: When winrate_pct is None in DeckDataResult,
    format_deck_data SHALL output None for "winrate_pct" (JSON null).
    """
    output = format_deck_data(r)

    winrate_value = output["winrate_pct"]

    # The value must be None (serializes to JSON null)
    assert winrate_value is None, (
        f"Expected None for None winrate_pct, got {winrate_value!r}"
    )


@given(r=user_deck_none_winrate_strategy)
@settings(max_examples=100)
def test_format_user_deck_none_winrate_produces_null(r: UserDeckResult):
    """Property: When winrate_pct is None in UserDeckResult,
    format_user_deck SHALL output None for "winrate_pct" (JSON null).
    """
    output = format_user_deck(r)

    winrate_value = output["winrate_pct"]

    # The value must be None (serializes to JSON null)
    assert winrate_value is None, (
        f"Expected None for None winrate_pct, got {winrate_value!r}"
    )


@given(r=user_deck_none_last_played_strategy)
@settings(max_examples=100)
def test_format_user_deck_none_last_played_produces_null(r: UserDeckResult):
    """Property: When last_played is None in UserDeckResult,
    format_user_deck SHALL output None for "last_played" (JSON null).
    """
    output = format_user_deck(r)

    last_played_value = output["last_played"]

    # The value must be None (serializes to JSON null)
    assert last_played_value is None, (
        f"Expected None for None last_played, got {last_played_value!r}"
    )
