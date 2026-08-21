# Feature: service-layer-security-refactor, Property 1: Audit log round-trip preservation
"""Property-based test for audit log round-trip preservation.

**Validates: Requirements 2.2, 2.5**

For any valid combination of (action, entity_type, entity_id, details) and
for any authenticated user context, calling write_audit_log() SHALL produce
an AuditLog entry whose action, entity_type, entity_id, and details fields
match the inputs, and whose user_id and username fields match the current user.
"""

from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app import db
from app.models import AuditLog
from app.services.audit import write_audit_log


# Strategies for generating valid audit log inputs
# Action and entity_type must be non-empty strings (DB columns are NOT NULL)
non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
    min_size=1,
    max_size=100,
)

# entity_id can be a string, int, or None
entity_id_strategy = st.one_of(
    st.none(),
    st.integers(min_value=0, max_value=2**31 - 1),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=50,
    ),
)

# details can be a string or None
details_strategy = st.one_of(
    st.none(),
    st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "S", "Z")),
        min_size=0,
        max_size=200,
    ),
)

# User context: id and username
user_id_strategy = st.integers(min_value=1, max_value=2**31 - 1)
username_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=64,
)


@given(
    action=non_empty_text,
    entity_type=non_empty_text,
    entity_id=entity_id_strategy,
    details=details_strategy,
    user_id=user_id_strategy,
    username=username_strategy,
)
@settings(max_examples=100)
def test_audit_log_round_trip_preservation(
    app, action, entity_type, entity_id, details, user_id, username
):
    """Property 1: Audit log round-trip preservation.

    For any valid inputs and authenticated user context, write_audit_log()
    produces an AuditLog entry whose fields match the inputs and current user.
    """
    with app.app_context():
        # Mock current_user with the generated user context
        mock_user = MagicMock()
        mock_user.id = user_id
        mock_user.username = username

        with patch("app.services.audit.current_user", mock_user):
            # Clear session to ensure clean state
            db.session.rollback()

            write_audit_log(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
            )

            # Flush to assign defaults and make the entry queryable
            db.session.flush()

            # Query the last-added AuditLog entry
            entry = (
                db.session.query(AuditLog)
                .order_by(AuditLog.id.desc())
                .first()
            )

            assert entry is not None, "AuditLog entry was not created"

            # Verify round-trip: all fields match inputs
            assert entry.action == action
            assert entry.entity_type == entity_type

            # entity_id is converted to str if not None
            if entity_id is not None:
                assert entry.entity_id == str(entity_id)
            else:
                assert entry.entity_id is None

            assert entry.details == details

            # Verify user context fields match the mocked current_user
            assert entry.user_id == user_id
            assert entry.username == username

            # Cleanup: rollback to not accumulate entries across examples
            db.session.rollback()
