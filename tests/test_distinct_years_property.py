# Feature: raw-sql-to-orm, Property 10: Distinct Years Query
"""
Property test verifying that `get_game_years` returns exactly the set of distinct
years present in non-null-dated games, in descending order, with no duplicates.

The Game.date column has a NOT NULL constraint at the schema level, so null-date
exclusion is guaranteed by the database itself. This test focuses on verifying:
- Correct extraction of distinct years from valid dates
- Descending order of results
- No duplicate years in output
- Empty result when no games exist

**Validates: Requirements 7.1, 7.2, 7.3**
"""

from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Game
from app.api.queries import get_game_years


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate dates spanning 2020-2024 for year variety
valid_date_strategy = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2024, 12, 31),
)


@st.composite
def games_with_various_dates(draw):
    """Generate a set of games with dates spanning multiple years (2020-2024).

    Some games may share the same year to test deduplication.
    Returns a list of game dicts with 'id' and 'date'.
    """
    num_games = draw(st.integers(min_value=0, max_value=20))
    games = []

    for i in range(num_games):
        game_date = draw(valid_date_strategy)
        games.append({"id": i + 1, "date": game_date})

    return games


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(data=games_with_various_dates())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_distinct_years_query(app, db_session, data):
    """Property 10: For any set of games (some with null dates, some with valid
    dates across multiple years), the years query SHALL return exactly the set of
    distinct years present in non-null-dated games, in descending order.

    Note: Since the schema enforces NOT NULL on Game.date, all games have valid
    dates. The null-date exclusion behavior (`.where(Game.date.isnot(None))`)
    is defensive and covered by the schema constraint.
    """
    with app.app_context():
        # Clear existing games
        db_session.query(Game).delete()
        db_session.flush()

        # Insert generated games
        for game_data in data:
            game = Game(
                id=game_data["id"],
                date=game_data["date"],
                cedh=False,
            )
            db_session.add(game)
        db_session.flush()

        # Execute query under test
        result = get_game_years(db_session)

        # Compute expected: distinct years from all dates (all non-null), descending
        expected_years = sorted(
            set(g["date"].year for g in data),
            reverse=True,
        )

        # Verify: returns exactly the distinct years in descending order
        assert result == expected_years, (
            f"Expected years {expected_years}, got {result}. "
            f"Game dates: {[g['date'] for g in data]}"
        )

        # Verify: no duplicates
        assert len(result) == len(set(result)), (
            f"Duplicate years found in result: {result}"
        )

        # Verify: results are in descending order
        for i in range(len(result) - 1):
            assert result[i] > result[i + 1], (
                f"Years not in descending order at index {i}: "
                f"{result[i]} should be > {result[i + 1]}"
            )

        # Verify: empty input produces empty output
        if not data:
            assert result == [], (
                f"Expected empty result when no games exist, got {result}"
            )
