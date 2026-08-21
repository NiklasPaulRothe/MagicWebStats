from app.models import AuditLog
from app import db
from flask_login import current_user


def write_audit_log(
    action: str,
    entity_type: str,
    entity_id: str | int | None = None,
    details: str | None = None,
) -> None:
    """Write an entry to the audit_log table.

    Populates user_id and username from the currently authenticated user.
    The caller is responsible for committing the session (or this function
    participates in the caller's transaction).
    """
    entry = AuditLog(
        user_id=current_user.id,
        username=current_user.username,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        details=details,
    )
    db.session.add(entry)
