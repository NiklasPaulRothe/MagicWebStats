# Feature: service-layer-security-refactor, Property 10: Game deletion completeness
"""Property-based test for game deletion completeness.

**Validates: Requirements 7.5**

For any existing Game with N participants, `delete_game(game_id)` SHALL remove
the Game row and all N associated Participant rows, leaving zero rows referencing
that game_id. An audit log entry SHALL be created recording the deletion.
"""

import itertools
from datetime import date
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, strategies as st

from app import db
from app.models import AuditLog, Deck, Game, Participant, Player
from app.services.game_service import delete_game


# Counter to generate unique IDs across hypothesis examples
_id_counter = itertools.count(start=1)


# Strategy: number of participants per game (1-5 as specified)
num_participants_strategy = st.integers(min_value=1, max_value=5)


@given(num_participants=num_participants_strategy)
@settings(max_examples=100, deadline=None)
def test_game_deletion_completeness(app, num_participants):
    """Property 10: Game deletion completeness.

    For any existing Game with N participants, delete_game(game_id) removes
    the Game row and all N associated Participant rows, leaving zero rows
    referencing that game_id, and creates an audit log entry.
    """
    with app.app_context():
        db.session.rollback()

        # Generate unique base ID for this example to avoid PK collisions
        base_id = next(_id_counter) * 100

        # Mock current_user for audit log
        mock_user = MagicMock()
        mock_user.id = 99998
        mock_user.username = "deletion_testuser"

        with patch("app.services.audit.current_user", mock_user):
            # Ensure prerequisite records exist for FK constraints
            from app.models import ColorIdentity, User

            # Create a user for audit log FK (if not already present)
            if db.session.get(User, 99998) is None:
                audit_user = User(
                    id=99998,
                    username="deletion_testuser",
                    email=f"deletion_test_{base_id}@example.com",
                    player_id=1,
                    active=True,
                    role="admin",
                )
                audit_user.set_password("password")
                db.session.add(audit_user)
                db.session.flush()

            # Ensure ColorIdentity "Colorless" exists for Deck FK
            if db.session.get(ColorIdentity, "Colorless") is None:
                ci = ColorIdentity(name="Colorless", amount=0)
                db.session.add(ci)
                db.session.flush()

            # Create prerequisite Player and Deck records for FK constraints
            players = []
            for i in range(num_participants):
                player = Player(id=base_id + i, name=f"Player_{base_id}_{i}")
                db.session.add(player)
                players.append(player)
            db.session.flush()

            decks = []
            for i, player in enumerate(players):
                deck = Deck(
                    id=base_id + 50 + i,
                    name=f"Deck_{base_id}_{i}",
                    commander=f"Commander_{base_id}_{i}",
                    player_id=player.id,
                    color_identity="Colorless",
                    active=True,
                )
                db.session.add(deck)
                decks.append(deck)
            db.session.flush()

            # Create a game (let DB auto-assign ID)
            game = Game(
                date=date(2024, 1, 15),
                first_player_id=players[0].id,
                winner_id=players[0].id,
                planechase=False,
            )
            db.session.add(game)
            db.session.flush()
            game_id = game.id

            # Create N participants for the game
            for i in range(num_participants):
                participant = Participant(
                    game_id=game_id,
                    player_id=players[i].id,
                    deck_id=decks[i].id,
                    early_sol_ring=False,
                )
                db.session.add(participant)
            db.session.commit()

            # Verify setup: game and participants exist
            assert db.session.get(Game, game_id) is not None
            participant_count = (
                db.session.query(Participant)
                .filter(Participant.game_id == game_id)
                .count()
            )
            assert participant_count == num_participants

            # Execute deletion
            delete_game(game_id)

            # Verify: zero Game rows for that game_id
            assert db.session.get(Game, game_id) is None

            # Verify: zero Participant rows referencing that game_id
            remaining_participants = (
                db.session.query(Participant)
                .filter(Participant.game_id == game_id)
                .count()
            )
            assert remaining_participants == 0

            # Verify: audit log entry was created for the deletion
            audit_entry = (
                db.session.query(AuditLog)
                .filter(
                    AuditLog.action == "game_delete",
                    AuditLog.entity_type == "Game",
                    AuditLog.entity_id == str(game_id),
                )
                .first()
            )
            assert audit_entry is not None
            assert "Deleted game on" in audit_entry.details
