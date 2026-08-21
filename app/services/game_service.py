"""Game service module for atomic game creation, update, and deletion.

Provides functions for managing games and their participants with proper
transaction handling — single commit per operation, full rollback on failure.
"""

from dataclasses import dataclass
from datetime import date as date_type

import sqlalchemy as sa

from app import db
from app.models import Game, Participant
from app.services.audit import write_audit_log


@dataclass
class ParticipantInput:
    """Input data for a single game participant.

    Captures all per-participant fields from the game creation/edit form.
    """

    player_id: int
    deck_id: int
    early_sol_ring: bool = False
    mulligans: int | None = None
    comments: str | None = None
    landdrops: int | None = None
    lands: int | None = None
    enough_mana: bool | None = None
    enough_gas: bool | None = None
    deckplan: bool | None = None
    unanswered_threats: bool | None = None
    loss_without_answer: bool | None = None
    selfmade_win: bool | None = None
    fun_moments: bool | None = None
    removal_played: int | None = None
    targeted_by_removal: int | None = None
    protection_played: int | None = None


def create_game(
    date: date_type,
    first_player_id: int,
    winner_id: int,
    participants: list[ParticipantInput],
    turns: int | None = None,
    final_blow: str | None = None,
    first_ko_turn: int | None = None,
    first_ko_by: str | None = None,
    cedh: bool = False,
    added_by_user_id: int | None = None,
) -> Game:
    """Create a game with all participants in a single atomic transaction.

    Flushes after inserting the Game row to obtain game.id, then inserts
    all participant rows and an audit log entry before issuing a single
    commit. On any failure the entire transaction is rolled back — no
    partial game or participant rows will remain in the database.

    Args:
        date: Date the game was played.
        first_player_id: Player ID of the first player.
        winner_id: Player ID of the winner.
        participants: List of ParticipantInput dataclass instances.
        turns: Total number of turns in the game.
        final_blow: Description of how the game ended.
        first_ko_turn: Turn number of the first player elimination.
        first_ko_by: Description of how the first KO happened.
        cedh: Whether this was a cEDH game.
        added_by_user_id: User ID of the person who recorded the game.

    Returns:
        The newly created Game instance with its assigned ID.

    Raises:
        Exception: Re-raises any exception after rolling back the session.
    """
    game = Game(
        date=date,
        first_player_id=first_player_id,
        winner_id=winner_id,
        planechase=False,
        turns=turns,
        final_blow=final_blow,
        first_ko_turn=first_ko_turn,
        first_ko_by=first_ko_by,
        cedh=cedh,
        added_by_user_id=added_by_user_id,
    )
    db.session.add(game)
    db.session.flush()  # Get game.id without committing

    try:
        for p in participants:
            participant = Participant(
                game_id=game.id,
                player_id=p.player_id,
                deck_id=p.deck_id,
                early_sol_ring=p.early_sol_ring,
                mulligans=p.mulligans,
                comments=p.comments,
                landdrops=p.landdrops,
                lands=p.lands,
                enough_mana=p.enough_mana,
                enough_gas=p.enough_gas,
                deckplan=p.deckplan,
                unanswered_threats=p.unanswered_threats,
                loss_without_answer=p.loss_without_answer,
                selfmade_win=p.selfmade_win,
                fun_moments=p.fun_moments,
                removal_played=p.removal_played,
                targeted_by_removal=p.targeted_by_removal,
                protection_played=p.protection_played,
            )
            db.session.add(participant)

        write_audit_log("game_add", "Game", game.id, f"Added game on {game.date}")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return game


def update_game(game: Game, **kwargs) -> None:
    """Update game fields and optionally its participants in a single commit.

    Accepts arbitrary game field updates via kwargs. If a 'participants' key
    is provided, it should be a list of ParticipantInput instances that will
    replace the existing participants for the game.

    Args:
        game: The Game instance to update.
        **kwargs: Game field names and their new values. Special keys:
            - participants: list[ParticipantInput] to replace all participants.

    Raises:
        Exception: Re-raises any exception after rolling back the session.
    """
    participants_input: list[ParticipantInput] | None = kwargs.pop("participants", None)

    try:
        # Update game-level fields
        for field, value in kwargs.items():
            if hasattr(game, field):
                setattr(game, field, value)

        # Replace participants if provided
        if participants_input is not None:
            # Remove existing participants
            db.session.execute(
                sa.delete(Participant).where(Participant.game_id == game.id)
            )

            # Insert new participants
            for p in participants_input:
                participant = Participant(
                    game_id=game.id,
                    player_id=p.player_id,
                    deck_id=p.deck_id,
                    early_sol_ring=p.early_sol_ring,
                    mulligans=p.mulligans,
                    comments=p.comments,
                    landdrops=p.landdrops,
                    lands=p.lands,
                    enough_mana=p.enough_mana,
                    enough_gas=p.enough_gas,
                    deckplan=p.deckplan,
                    unanswered_threats=p.unanswered_threats,
                    loss_without_answer=p.loss_without_answer,
                    selfmade_win=p.selfmade_win,
                    fun_moments=p.fun_moments,
                    removal_played=p.removal_played,
                    targeted_by_removal=p.targeted_by_removal,
                    protection_played=p.protection_played,
                )
                db.session.add(participant)

        write_audit_log("game_edit", "Game", game.id, f"Edited game on {game.date}")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def delete_game(game_id: int) -> None:
    """Delete a game and all its participants atomically.

    Removes all participant rows for the given game, then the game itself,
    and logs the deletion — all within a single commit. On failure the
    entire operation is rolled back.

    Args:
        game_id: Primary key of the game to delete.

    Raises:
        Exception: Re-raises any exception after rolling back the session.
    """
    try:
        game = db.session.get(Game, game_id)
        if game is None:
            raise ValueError(f"Game with id {game_id} not found")

        game_date = game.date

        # Delete all participants for this game
        db.session.execute(
            sa.delete(Participant).where(Participant.game_id == game_id)
        )

        # Delete the game itself
        db.session.delete(game)

        write_audit_log("game_delete", "Game", game_id, f"Deleted game on {game_date}")
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
