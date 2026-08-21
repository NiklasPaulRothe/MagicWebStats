# Feature: codebase-normalization, Property 2: Chart data computation produces correct statistical aggregations
"""
Property test verifying that `compute_chart_data()` produces correct statistical
aggregations: for any non-empty list of game turn counts, the sum of all turn_data
counts equals the length of the input list, the average equals the arithmetic mean
of the input, and the median equals the statistical median of the input.

**Validates: Requirements 2.5, 2.7**
"""

import statistics
from datetime import date

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import Game, Player
from app.services.stats_service import compute_chart_data


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate non-empty lists of positive turn counts (typical game turns: 1-30)
turn_counts_strategy = st.lists(
    st.integers(min_value=1, max_value=30),
    min_size=1,
    max_size=50,
)


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


@given(turn_counts=turn_counts_strategy)
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_chart_data_statistical_correctness(app, turn_counts):
    """Property 2: For any non-empty list of game turn counts, compute_chart_data()
    SHALL produce turn_data where:
    - The sum of all counts equals the length of the input list
    - The average equals the arithmetic mean of the input (rounded to 2 decimals)
    - The median equals the statistical median of the input (rounded to 2 decimals)
    """
    with app.app_context():
        # Clean slate
        db.session.rollback()
        db.session.query(Game).delete()
        db.session.query(Player).delete()
        db.session.commit()

        # Create a player for the winner FK (optional, but keeps data consistent)
        player = Player(id=1, name="TestPlayer")
        db.session.add(player)
        db.session.flush()

        # Seed the database with Game records using the generated turn counts
        for i, turns in enumerate(turn_counts):
            game = Game(
                id=i + 1,
                date=date(2024, 1, 1),
                turns=turns,
                planechase=False,
                cedh=False,
            )
            db.session.add(game)
        db.session.commit()

        # Call the function under test
        result = compute_chart_data(exclude_cedh=True)

        # --- Property: Sum of all turn_data counts equals input list length ---
        total_count = sum(item["count"] for item in result["turn_data"])
        assert total_count == len(turn_counts), (
            f"Sum of turn_data counts ({total_count}) != input list length ({len(turn_counts)})"
        )

        # --- Property: avg_turns equals arithmetic mean rounded to 2 decimals ---
        expected_mean = round(statistics.mean(turn_counts), 2)
        assert result["avg_turns"] == expected_mean, (
            f"avg_turns ({result['avg_turns']}) != expected mean ({expected_mean})"
        )

        # --- Property: median_turns equals statistical median rounded to 2 decimals ---
        expected_median = round(statistics.median(turn_counts), 2)
        assert result["median_turns"] == expected_median, (
            f"median_turns ({result['median_turns']}) != expected median ({expected_median})"
        )

        # Cleanup for next hypothesis example
        db.session.query(Game).delete()
        db.session.query(Player).delete()
        db.session.commit()
