"""Deck service module for versioning, archiving, and card-loading orchestration.

Extracts business logic from app/decks/routes.py into testable, reusable functions.
None of the functions in this module commit the session — the caller is responsible
for committing.
"""

from __future__ import annotations

from sqlalchemy import func

from app import db
from app.models import Deck, DeckVersionHistory, Game, Participant, Player
from app.third_party_data.deckbuilder import get_id_from_url, load_cards_from_archidekt


def version_change(deck: Deck, comment: str | None = None) -> str:
    """Bump the 'change' component: X.Y.Z → X.Y.(Z+1).

    Creates a DeckVersionHistory entry recording the previous and new
    version values. Updates the deck object in-place.
    Does NOT commit — caller commits.

    Args:
        deck: The Deck model instance to version bump.
        comment: Optional comment describing the change.

    Returns:
        The new version string in "V.P.C" format.
    """
    history_entry = DeckVersionHistory(
        deck_id=deck.id,
        change_type='change',
        previous_version=deck.version,
        previous_patch=deck.patch,
        previous_change=deck.change,
        new_version=deck.version,
        new_patch=deck.patch,
        new_change=deck.change + 1,
        comment=comment,
    )
    db.session.add(history_entry)

    deck.change += 1
    deck.last_change = func.current_date()

    return f"{deck.version}.{deck.patch}.{deck.change}"


def version_patch(deck: Deck, comment: str | None = None) -> str:
    """Bump the 'patch' component: X.Y.Z → X.(Y+1).0.

    Creates a DeckVersionHistory entry recording the previous and new
    version values. Updates the deck object in-place.
    Does NOT commit — caller commits.

    Args:
        deck: The Deck model instance to version bump.
        comment: Optional comment describing the patch.

    Returns:
        The new version string in "V.P.C" format.
    """
    history_entry = DeckVersionHistory(
        deck_id=deck.id,
        change_type='patch',
        previous_version=deck.version,
        previous_patch=deck.patch,
        previous_change=deck.change,
        new_version=deck.version,
        new_patch=deck.patch + 1,
        new_change=0,
        comment=comment,
    )
    db.session.add(history_entry)

    deck.patch += 1
    deck.change = 0
    deck.last_patch = func.current_date()

    return f"{deck.version}.{deck.patch}.{deck.change}"


def version_rework(deck: Deck, comment: str | None = None) -> str:
    """Bump the 'rework' (major) component: X.Y.Z → (X+1).0.0.

    Creates a DeckVersionHistory entry recording the previous and new
    version values. Updates the deck object in-place.
    Does NOT commit — caller commits.

    Args:
        deck: The Deck model instance to version bump.
        comment: Optional comment describing the rework.

    Returns:
        The new version string in "V.P.C" format.
    """
    history_entry = DeckVersionHistory(
        deck_id=deck.id,
        change_type='rework',
        previous_version=deck.version,
        previous_patch=deck.patch,
        previous_change=deck.change,
        new_version=deck.version + 1,
        new_patch=0,
        new_change=0,
        comment=comment,
    )
    db.session.add(history_entry)

    deck.version += 1
    deck.patch = 0
    deck.change = 0
    deck.last_rework = func.current_date()

    return f"{deck.version}.{deck.patch}.{deck.change}"


def archive_deck(deck: Deck) -> None:
    """Set deck.active = False. Does NOT commit — caller commits.

    Args:
        deck: The Deck model instance to archive.
    """
    deck.active = False


def dearchive_deck(deck: Deck) -> None:
    """Set deck.active = True. Does NOT commit — caller commits.

    Args:
        deck: The Deck model instance to dearchive.
    """
    deck.active = True


def update_decklist(deck: Deck, decklist_url: str) -> None:
    """Parse Archidekt URL, update deck fields, and load cards.

    Parses the decklist URL to extract the deck site and archidekt ID,
    updates the deck's fields, then triggers card loading from Archidekt.

    On card-loading failure: rolls back the session and re-raises the exception.
    On success: deck.decklist, deck.decksite, deck.archidekt_id, and
    DeckComponents are updated but NOT committed — caller commits.

    Args:
        deck: The Deck model instance to update.
        decklist_url: The Archidekt deck URL to parse and load from.

    Raises:
        Exception: If card loading from Archidekt fails. The session is
            rolled back before the exception propagates.
    """
    deckbuilder = get_id_from_url(decklist_url)
    deck.decklist = decklist_url
    deck.decksite = deckbuilder[0].strip()
    deck.archidekt_id = deckbuilder[1].strip()

    try:
        load_cards_from_archidekt(deck.archidekt_id, deck.id)
    except Exception:
        db.session.rollback()
        raise


def build_game_history(
    deck: Deck,
    participants: list[Participant],
    games: dict[int, Game],
    participants_by_game: dict[int, list[Participant]],
    players: dict[int, Player],
    decks: dict[int, Deck],
) -> list[dict]:
    """Build the game-history row list for a deck's show page.

    Assembles one dict per game the deck participated in, containing
    opponent info, winner name, turn count, final blow, participant
    performance data, and win flag.

    This is a pure computation function — no Flask request context dependency.

    Args:
        deck: The deck being viewed.
        participants: Participant records for this deck's owner/deck combo,
            ordered by game_id descending.
        games: Game lookup by ID.
        participants_by_game: All participants grouped by game ID.
        players: Player lookup by ID.
        decks: Deck lookup by ID.

    Returns:
        A list of dicts, each containing keys: datum, gegner, winner,
        turns, final_blow, participant_data, is_win.
    """
    rows: list[dict] = []

    for participant in participants:
        game_id = participant.game_id
        game_data = games.get(game_id)
        if game_data is None:
            continue

        all_participants_in_game = participants_by_game.get(game_id, [])

        # Resolve opponents (participants whose player_id differs from the deck's owner)
        opponents = [p for p in all_participants_in_game if p.player_id != deck.player_id]
        opponent_data = []
        for opp in opponents:
            player = players.get(opp.player_id)
            deck_obj = decks.get(opp.deck_id)
            opponent_data.append({
                "player_name": player.name if player else "Unknown",
                "deck_name": deck_obj.name if deck_obj else "Unknown Deck",
                "commander_image": deck_obj.image_uri if deck_obj and deck_obj.image_uri else "/static/img/default_commander.png",
            })

        winner_name = (
            players.get(game_data.winner_id).name
            if players.get(game_data.winner_id)
            else "Unbekannt"
        )
        turn_count = game_data.turns if game_data.turns else "-"
        final_blow = game_data.final_blow if game_data.final_blow else "Not Tracked"

        # Get participant data for this deck in this game
        my_participant = next(
            (p for p in all_participants_in_game
             if p.player_id == deck.player_id and p.deck_id == deck.id),
            None,
        )
        participant_data = None
        if my_participant:
            is_win = game_data.winner_id == deck.player_id
            participant_data = {
                "mulligans": getattr(my_participant, "mulligans", None),
                "landdrops": getattr(my_participant, "landdrops", None),
                "lands": getattr(my_participant, "lands", None),
                "enough_mana": getattr(my_participant, "enough_mana", None),
                "enough_gas": getattr(my_participant, "enough_gas", None),
                "deckplan": getattr(my_participant, "deckplan", None),
                "unanswered_threats": getattr(my_participant, "unanswered_threats", None),
                "fun_moments": getattr(my_participant, "fun_moments", None),
                "loss_without_answer": getattr(my_participant, "loss_without_answer", None) if not is_win else None,
                "selfmade_win": getattr(my_participant, "selfmade_win", None) if is_win else None,
                "comments": getattr(my_participant, "comments", None),
                "is_win": is_win,
            }

        rows.append({
            "datum": game_data.date.strftime("%Y-%m-%d"),
            "gegner": opponent_data,
            "winner": winner_name,
            "turns": turn_count,
            "final_blow": final_blow,
            "participant_data": participant_data,
            "is_win": game_data.winner_id == deck.player_id,
        })

    return sorted(rows, key=lambda r: r["datum"], reverse=True)
