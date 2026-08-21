"""Elo rating calculation service.

Provides functions for computing Elo ratings in a multiplayer (3-5 player)
Commander/EDH context. Extracted from app/decks/routes.py to enable
independent testing without a database or Flask request context.
"""

import statistics
from dataclasses import dataclass


DECK_OWNER_OVERRIDE_PLAYER_ID: int = 24
"""Player ID whose decks are always included in Elo calculations
even when played by a different player (community/shared decks)."""


def expected_score(rating: float, opponent_rating: float) -> float:
    """Pairwise expected score using the standard Elo formula.

    Args:
        rating: The player's current Elo rating.
        opponent_rating: The opponent's current Elo rating.

    Returns:
        A float between 0 and 1 representing the expected probability
        of winning against the opponent.
    """
    return 1 / (1 + 10 ** ((opponent_rating - rating) / 400))


def expected_multiplayer_score(deck_id: int, deck_ratings: dict[int, float]) -> float:
    """Average pairwise expected score against all opponents in a pod.

    Computes the mean of pairwise expected scores for the given deck
    against every other deck in the game.

    Args:
        deck_id: The ID of the deck to compute the expected score for.
        deck_ratings: A mapping of deck_id -> current Elo rating for all
            participants in the game.

    Returns:
        The average pairwise expected score (unnormalized).
    """
    opponents = {did: r for did, r in deck_ratings.items() if did != deck_id}
    my_rating = deck_ratings[deck_id]
    pairwise_sum = sum(expected_score(my_rating, opp_r) for opp_r in opponents.values())
    return pairwise_sum / len(opponents)


def get_game_k_factor(participants_games_played: list[int]) -> int:
    """Determine K-factor for a game based on median experience of participants.

    A single K-factor per game ensures the rating update is zero-sum:
    total Elo gained equals total Elo lost across all participants.

    Args:
        participants_games_played: List of games-played counts for each
            participant in the game.

    Returns:
        60 if median games played <= 10 (new players, high volatility),
        40 if median games played <= 30 (intermediate),
        24 otherwise (experienced players, low volatility).
    """
    median_games = statistics.median(participants_games_played)
    if median_games <= 10:
        return 60
    elif median_games <= 30:
        return 40
    else:
        return 24


@dataclass
class EloResult:
    """Result of an Elo recalculation for a single deck.

    Attributes:
        deck_id: The deck's database ID.
        new_rating: The computed Elo rating after processing all games.
        games_played: The number of valid games the deck participated in.
    """

    deck_id: int
    new_rating: float
    games_played: int


def recalculate_all_elo(
    decks: list,
    games: list,
    participants_by_game: dict[int, list],
) -> list[EloResult]:
    """Recalculate Elo ratings for all decks across all games.

    Processes games in order, applying multiplayer Elo updates with
    normalized expected scores and a single K-factor per game.

    A deck's participant is considered valid if:
    - The deck's owner (player_id attribute) matches the participant's player_id, OR
    - The deck's owner is DECK_OWNER_OVERRIDE_PLAYER_ID (shared/community deck)

    Games with fewer than 3 or more than 5 participants are skipped.
    Games with fewer than 2 valid participants after filtering are skipped.

    Args:
        decks: List of deck objects with `.id` and `.player_id` attributes.
        games: List of game objects with `.id` and `.winner_id` attributes,
            in the order they should be processed.
        participants_by_game: Mapping of game_id -> list of participant
            objects with `.deck_id` and `.player_id` attributes.

    Returns:
        A list of EloResult with the final rating and games_played for
        each deck. The caller is responsible for persisting the results.
    """
    # Initialize ratings: all decks start at 1500
    elo_ratings: dict[int, dict[str, float | int]] = {
        deck.id: {'elo_rating': 1500.0, 'games_played': 0}
        for deck in decks
    }

    # Build a lookup for deck ownership
    deck_owners: dict[int, int] = {deck.id: deck.player_id for deck in decks}

    for game in games:
        participants = participants_by_game.get(game.id, [])
        if len(participants) < 3 or len(participants) > 5:
            continue

        # Build current ratings for this game's valid participants
        deck_ratings: dict[int, float] = {}
        valid_participants = []
        for p in participants:
            deck_owner = deck_owners.get(p.deck_id)
            if deck_owner is None:
                continue
            # Deck is valid if owner matches participant, or owner is the override ID
            if deck_owner != p.player_id and deck_owner != DECK_OWNER_OVERRIDE_PLAYER_ID:
                continue
            if p.deck_id in elo_ratings:
                deck_ratings[p.deck_id] = elo_ratings[p.deck_id]['elo_rating']
                valid_participants.append(p)

        if len(deck_ratings) < 2:
            continue

        # Normalize expected scores so they sum to 1
        raw_expected = {
            did: expected_multiplayer_score(did, deck_ratings)
            for did in deck_ratings
        }
        total_expected = sum(raw_expected.values())
        normalized_expected = {
            did: raw / total_expected
            for did, raw in raw_expected.items()
        }

        # Single K-factor for the whole game → guarantees zero-sum
        games_played_list = [
            elo_ratings[p.deck_id]['games_played'] for p in valid_participants
        ]
        k = get_game_k_factor(games_played_list)

        # Apply updates
        for participant in valid_participants:
            did = participant.deck_id
            actual_score = 1.0 if game.winner_id == participant.player_id else 0.0

            rating = elo_ratings[did]['elo_rating']
            new_rating = rating + k * (actual_score - normalized_expected[did])

            elo_ratings[did]['elo_rating'] = new_rating
            elo_ratings[did]['games_played'] += 1

    # Build result list
    return [
        EloResult(
            deck_id=deck_id,
            new_rating=values['elo_rating'],
            games_played=values['games_played'],
        )
        for deck_id, values in elo_ratings.items()
    ]
