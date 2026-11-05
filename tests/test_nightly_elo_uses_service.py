"""Guard: the nightly job must not re-implement the rating algorithm.

A duplicated copy of the Elo math in ``scripts/fetch_card_data.py`` silently
drifted out of sync with the authoritative ``app/services/elo_service.py`` in
the past (the nightly computed different ratings than the web app). To prevent
that recurring, the nightly's ``calculate_elo_ratings`` must delegate to
``elo_service.recalculate_all_elo`` rather than carry its own copy of the math.

These are source-level checks (no DB / network), so they run fast and fail loudly
if someone re-introduces a parallel implementation in the script.
"""

import ast
import inspect
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "fetch_card_data.py"


def _source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_script_delegates_to_elo_service():
    """calculate_elo_ratings must call the service, not reimplement it."""
    src = _source()
    assert "recalculate_all_elo" in src, (
        "scripts/fetch_card_data.py no longer references recalculate_all_elo -- "
        "the nightly must delegate to app.services.elo_service, not reimplement "
        "the rating algorithm."
    )


def test_script_has_no_duplicated_rating_math():
    """The script must not redefine the algorithm's helper functions.

    These names live in elo_service as the single source of truth; if any of
    them is defined at module scope in the script again, a second (driftable)
    copy of the math has been reintroduced.
    """
    tree = ast.parse(_source())
    defined = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    forbidden = {
        "expected_score",
        "expected_multiplayer_score",
        "expected_share",
        "pod_power",
        "movement",
        "bootstrap_seed",
        "_edge_damp",
        "confidence_interval",
    }
    leaked = defined & forbidden
    assert not leaked, (
        f"scripts/fetch_card_data.py redefines rating-algorithm functions "
        f"{sorted(leaked)} -- these belong only to app/services/elo_service.py. "
        f"Delegate to the service instead of duplicating the math."
    )


def test_calculate_elo_ratings_signature_is_backwards_compatible():
    """The Phase 6 caller passes the raw psycopg2 conn; the function must still
    accept it (even though it now opens its own ORM session)."""
    from scripts.fetch_card_data import calculate_elo_ratings

    sig = inspect.signature(calculate_elo_ratings)
    params = list(sig.parameters.values())
    assert len(params) == 1, "expected a single (conn) parameter"
    assert params[0].default is None, (
        "conn should default to None so the function can be called without a "
        "raw connection"
    )
