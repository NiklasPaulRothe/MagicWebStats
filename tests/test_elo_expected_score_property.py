# Feature: service-layer-security-refactor, Property 5: Elo expected score symmetry
"""Property-based test for Elo expected score symmetry.

**Validates: Requirements 4.1**

For any two ratings A and B, expected_score(A, B) + expected_score(B, A)
SHALL equal 1.0 (within floating-point tolerance).
"""

import math

from hypothesis import given, settings, strategies as st

from app.services.elo_service import expected_score


# Strategy: generate realistic Elo ratings between 0 and 3000
rating_strategy = st.floats(min_value=0.0, max_value=3000.0, allow_nan=False, allow_infinity=False)


@given(rating_a=rating_strategy, rating_b=rating_strategy)
@settings(max_examples=100)
def test_expected_score_symmetry(rating_a, rating_b):
    """Property 5: Elo expected score symmetry.

    For any two ratings A and B, the pairwise expected scores must
    sum to 1.0, reflecting that one player's gain is the other's loss.
    """
    score_a = expected_score(rating_a, rating_b)
    score_b = expected_score(rating_b, rating_a)

    assert math.isclose(score_a + score_b, 1.0, rel_tol=1e-9), (
        f"expected_score({rating_a}, {rating_b}) + expected_score({rating_b}, {rating_a}) "
        f"= {score_a} + {score_b} = {score_a + score_b}, expected 1.0"
    )
