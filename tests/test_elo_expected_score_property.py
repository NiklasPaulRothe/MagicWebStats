# Feature: power-level rating model — win-share curve properties
"""Property-based tests for the win-share curve ``expected_share``.

The old pairwise ``expected_score`` (and its A/B symmetry) was replaced by the
power-level model's single curve ``expected_share(gap)``: the expected share of
games a deck wins given its rating gap to the reference power. These properties
pin the curve's shape:

1. Bounded in (0, 1) for any gap.
2. Pinned at the even-gap baseline: ``expected_share(0) == EVEN_SHARE``.
3. Monotonic: a larger gap never lowers the expected share.
"""

import math

from hypothesis import given, settings, strategies as st

from app.services.elo_service import expected_share, EVEN_SHARE


gap_strategy = st.floats(min_value=-1000.0, max_value=1000.0, allow_nan=False, allow_infinity=False)


@given(gap=gap_strategy)
@settings(max_examples=200)
def test_expected_share_in_unit_interval(gap):
    """The expected win share is always a probability in (0, 1)."""
    s = expected_share(gap)
    assert 0.0 < s < 1.0, f"expected_share({gap}) = {s} outside (0, 1)"


def test_expected_share_even_gap_is_baseline():
    """At a zero power gap the deck wins the even-pod baseline share."""
    assert math.isclose(expected_share(0.0), EVEN_SHARE, rel_tol=1e-9)


@given(
    gap=gap_strategy,
    delta=st.floats(min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_expected_share_monotonic_in_gap(gap, delta):
    """A larger rating gap never decreases the expected win share."""
    assert expected_share(gap + delta) >= expected_share(gap) - 1e-12
