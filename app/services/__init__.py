"""Service layer package for MagicWebStats business logic.

This package contains service modules that encapsulate business logic
separate from Flask route handlers. Service functions are plain Python
functions callable without a Flask request context for their core logic.

Modules:
    audit          - Consolidated audit logging (write_audit_log)
    stats_service  - Player, deck, and color identity statistics
    elo_service    - Elo rating calculations
    color_service  - Color identity image resolution
    deck_service   - Deck versioning, archiving, and card loading
    game_service   - Game creation, update, and deletion
"""
