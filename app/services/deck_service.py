"""Deck service module for versioning, archiving, and card-loading orchestration.

Extracts business logic from app/decks/routes.py into testable, reusable functions.
None of the functions in this module commit the session — the caller is responsible
for committing.
"""

from sqlalchemy import func

from app import db
from app.models import Deck, DeckVersionHistory
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
