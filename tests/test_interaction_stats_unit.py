"""Unit tests for stats_service.get_interaction_stats.

Covers averaging the two retained playstyle fields (``removal_played`` and
``targeted_by_removal``) over the subject player's OWN non-cEDH participations,
NULL-ignoring averages with non-null sample counts, cEDH exclusion, isolation
from other players' rows, and the neutral empty state.

Validates: Requirements 11b.1, 11b.2, 11b.3, 11b.4
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_interaction_stats


@pytest.fixture()
def seeded(app, db_session):
    """Seed interaction-stat scenarios keyed by subject player id.

    Subject (player 1) non-cEDH participations:
        removal_played=2, targeted_by_removal=1
        removal_played=4, targeted_by_removal=3
        removal_played=None, targeted_by_removal=5   -> NULL removal ignored
        removal_played=6, targeted_by_removal=None    -> NULL targeted ignored
    Plus a cEDH participation (removal=100, targeted=100) that must be excluded.

    So for the subject:
        removal_played: non-null {2, 4, 6} -> avg 4.0, n 3
        targeted_by_removal: non-null {1, 3, 5} -> avg 3.0, n 3

    An opponent (player 2) sits in each game with large interaction values to
    prove the subject's averages only use the subject's own rows.

    Player 3 (AllNull): has non-cEDH participations where both fields are NULL
    -> neutral empty state.
    """
    with app.app_context():
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        db_session.add(ColorIdentity(name="TestColor", amount=1))
        db_session.flush()

        for pid, name in [(1, "Subject"), (2, "Opp2"), (3, "AllNull")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        for did, pid in [(1, 1), (2, 2), (3, 3)]:
            db_session.add(Deck(
                id=did, name=f"Deck{did}", commander=f"Cmd{did}",
                player_id=pid, active=True, color_identity="TestColor",
            ))
        db_session.flush()

        gid = 1

        def add_participation(player_id, deck_id, removal, targeted, cedh=False):
            """Add a game + the given player's participation row.

            removal_played / targeted_by_removal have no ORM default, so passing
            None persists a genuine NULL. We still flush then explicitly null
            the attributes and flush again to be robust against any default that
            could overwrite None on flush (mirrors the aggregate-elo test).
            """
            nonlocal gid
            db_session.add(Game(id=gid, date=date(2025, 1, 1), cedh=cedh, winner_id=player_id))
            part = Participant(
                game_id=gid, player_id=player_id, deck_id=deck_id,
                removal_played=removal, targeted_by_removal=targeted,
            )
            db_session.add(part)
            db_session.flush()
            if removal is None:
                part.removal_played = None
            if targeted is None:
                part.targeted_by_removal = None
            db_session.flush()
            gid += 1
            return gid - 1

        # Subject (player 1) non-cEDH rows; opponent (player 2) sits in each.
        def add_subject_game(removal, targeted, cedh=False):
            g = add_participation(1, 1, removal, targeted, cedh=cedh)
            # Opponent with large values to prove isolation.
            opp = Participant(
                game_id=g, player_id=2, deck_id=2,
                removal_played=999, targeted_by_removal=999,
            )
            db_session.add(opp)
            db_session.flush()

        add_subject_game(2, 1)
        add_subject_game(4, 3)
        add_subject_game(None, 5)   # NULL removal ignored
        add_subject_game(6, None)   # NULL targeted ignored
        add_subject_game(100, 100, cedh=True)  # cEDH excluded entirely

        # Player 3: non-cEDH participations where both fields are NULL.
        add_participation(3, 3, None, None)
        add_participation(3, 3, None, None)

        db_session.flush()
        yield db_session


def test_removal_played_average_ignores_nulls(app, seeded):
    with app.app_context():
        result = get_interaction_stats(1)
        # Non-null removal_played {2, 4, 6} -> mean 4.0 over 3 samples.
        assert result["removal_played"]["avg"] == 4.0
        assert result["removal_played"]["n"] == 3


def test_targeted_by_removal_average_ignores_nulls(app, seeded):
    with app.app_context():
        result = get_interaction_stats(1)
        # Non-null targeted_by_removal {1, 3, 5} -> mean 3.0 over 3 samples.
        assert result["targeted_by_removal"]["avg"] == 3.0
        assert result["targeted_by_removal"]["n"] == 3


def test_cedh_games_excluded(app, seeded):
    with app.app_context():
        # The cEDH row (100/100) must not inflate the averages or sample counts.
        result = get_interaction_stats(1)
        assert result["removal_played"]["avg"] == 4.0
        assert result["removal_played"]["n"] == 3
        assert result["targeted_by_removal"]["avg"] == 3.0
        assert result["targeted_by_removal"]["n"] == 3


def test_only_subject_own_rows_counted(app, seeded):
    with app.app_context():
        # Opponent rows carry 999s; if those leaked in, averages would spike.
        result = get_interaction_stats(1)
        assert result["removal_played"]["avg"] == 4.0
        assert result["targeted_by_removal"]["avg"] == 3.0


def test_only_four_fields_returned(app, seeded):
    with app.app_context():
        result = get_interaction_stats(1)
        assert set(result.keys()) == {
            "removal_played",
            "targeted_by_removal",
            "removal_played_wins",
            "targeted_by_removal_wins",
        }
        assert set(result["removal_played"].keys()) == {"avg", "n"}
        assert set(result["targeted_by_removal"].keys()) == {"avg", "n"}
        assert set(result["removal_played_wins"].keys()) == {"avg", "n"}
        assert set(result["targeted_by_removal_wins"].keys()) == {"avg", "n"}


def test_empty_state_when_all_values_null(app, seeded):
    with app.app_context():
        # Player 3 has participations but every retained field is NULL.
        result = get_interaction_stats(3)
        assert result == {
            "removal_played": {"avg": None, "n": 0},
            "targeted_by_removal": {"avg": None, "n": 0},
            "removal_played_wins": {"avg": None, "n": 0},
            "targeted_by_removal_wins": {"avg": None, "n": 0},
        }


def test_empty_state_for_player_with_no_games(app, seeded):
    with app.app_context():
        result = get_interaction_stats(999)
        assert result == {
            "removal_played": {"avg": None, "n": 0},
            "targeted_by_removal": {"avg": None, "n": 0},
            "removal_played_wins": {"avg": None, "n": 0},
            "targeted_by_removal_wins": {"avg": None, "n": 0},
        }


def test_wins_only_averages_computed_over_won_games(app, db_session):
    """Wins-only variants average only the subject's won non-cEDH rows.

    Seeds the subject with a mix of won and lost non-cEDH games carrying
    removal_played / targeted_by_removal values, and asserts the wins-only
    averages reflect ONLY the won rows (and differ from the all-games averages).

    Validates: Requirements 11b.1, 11b.2
    """
    with app.app_context():
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        db_session.add(ColorIdentity(name="TestColor", amount=1))
        db_session.flush()

        # Subject = player 1, opponent = player 2 (so losses have a winner).
        db_session.add(Player(id=1, name="Subject"))
        db_session.add(Player(id=2, name="Opp2"))
        db_session.flush()
        db_session.add(Deck(
            id=1, name="Deck1", commander="Cmd1",
            player_id=1, active=True, color_identity="TestColor",
        ))
        db_session.flush()

        gid = 1

        def add_game(winner_id, removal, targeted):
            nonlocal gid
            db_session.add(Game(id=gid, date=date(2025, 1, 1), cedh=False, winner_id=winner_id))
            db_session.add(Participant(
                game_id=gid, player_id=1, deck_id=1,
                removal_played=removal, targeted_by_removal=targeted,
            ))
            db_session.flush()
            gid += 1

        # Won games (winner_id == 1): removal {4, 6} -> avg 5.0; targeted {2, 4} -> avg 3.0
        add_game(1, 4, 2)
        add_game(1, 6, 4)
        # Lost games (winner_id == 2): low removal values that would drag the
        # all-games average down below the wins-only average.
        add_game(2, 0, 0)
        add_game(2, 2, 2)
        db_session.flush()

        result = get_interaction_stats(1)

        # Wins-only: only the two won rows.
        assert result["removal_played_wins"]["avg"] == 5.0
        assert result["removal_played_wins"]["n"] == 2
        assert result["targeted_by_removal_wins"]["avg"] == 3.0
        assert result["targeted_by_removal_wins"]["n"] == 2

        # All-games averages include the lost rows and so differ.
        assert result["removal_played"]["avg"] == 3.0  # {4,6,0,2} mean
        assert result["removal_played"]["n"] == 4
        assert result["removal_played_wins"]["avg"] != result["removal_played"]["avg"]
