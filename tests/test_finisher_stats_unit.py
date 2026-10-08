"""Unit tests for stats_service.get_finisher_stats.

Covers most-common final-blow (mode), fastest win turn, average win turns,
cEDH exclusion, null-safety (NULL/empty final_blow and NULL turns ignored),
and the neutral empty state when the player has no qualifying wins.

Validates: Requirements 9.1, 9.2, 9.3, 9.4
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_finisher_stats


@pytest.fixture()
def seeded(app, db_session):
    """Seed finisher-stat scenarios keyed by subject player id.

    Subject (player 1) win rows (non-cEDH unless noted):
        turns=5,  final_blow='Combat'
        turns=3,  final_blow='Combat'    -> Combat is the mode (2x)
        turns=8,  final_blow='Commander'
        turns=10, final_blow=None        -> NULL final_blow ignored
        turns=None, final_blow='Combat'  -> NULL turns ignored for turn stats
        turns=1,  final_blow='Combat', cEDH -> excluded entirely (Req 9.3)
    Plus a loss for the subject (another player won) that must never count.

    So for the subject: final_blow mode = 'Combat', fastest = 3,
    avg over {5,3,8,10} = 6.5.

    Player 2 (NoFinishers): has wins but every final_blow/turns is NULL ->
    neutral empty state.

    Player 3 (NoWins): participates but never wins -> empty state.
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

        for pid, name in [(1, "Subject"), (2, "NoFinishers"), (3, "NoWins"), (4, "Other")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        db_session.add(Deck(
            id=1, name="Deck1", commander="Cmd1",
            player_id=1, active=True, color_identity="TestColor",
        ))
        db_session.flush()

        gid = 1

        def add_game(winner_id, turns, final_blow, cedh=False):
            nonlocal gid
            db_session.add(Game(
                id=gid, date=date(2025, 1, 1), cedh=cedh,
                winner_id=winner_id, turns=turns, final_blow=final_blow,
            ))
            db_session.add(Participant(game_id=gid, player_id=1, deck_id=1))
            gid += 1

        # Subject wins (non-cEDH)
        add_game(1, turns=5, final_blow="Combat")
        add_game(1, turns=3, final_blow="Combat")
        add_game(1, turns=8, final_blow="Commander")
        add_game(1, turns=10, final_blow=None)      # NULL final_blow ignored
        add_game(1, turns=None, final_blow="Combat")  # NULL turns ignored
        # Subject win but cEDH -> excluded
        add_game(1, turns=1, final_blow="Combat", cedh=True)
        # Subject loss (someone else won) -> never counted for the subject
        add_game(4, turns=2, final_blow="Combat")

        # Player 2 wins but all finisher fields NULL
        add_game(2, turns=None, final_blow=None)
        add_game(2, turns=None, final_blow="")  # empty string treated as absent

        db_session.flush()
        yield db_session


def test_most_common_final_blow_is_the_mode(app, seeded):
    with app.app_context():
        result = get_finisher_stats(1)
        assert result["most_common_final_blow"] == "Combat"


def test_fastest_win_turns_ignores_null_turns(app, seeded):
    with app.app_context():
        result = get_finisher_stats(1)
        assert result["fastest_win_turns"] == 3


def test_avg_win_turns_ignores_null_turns(app, seeded):
    with app.app_context():
        # Non-null win turns are {5, 3, 8, 10} -> mean 6.5
        result = get_finisher_stats(1)
        assert result["avg_win_turns"] == 6.5


def test_cedh_and_losses_excluded(app, seeded):
    with app.app_context():
        # The cEDH win (turns=1) and the loss (turns=2) must not lower the
        # fastest/avg or alter the mode.
        result = get_finisher_stats(1)
        assert result["fastest_win_turns"] == 3
        assert result["avg_win_turns"] == 6.5


def test_second_final_blow_and_slowest_win_turns(app, seeded):
    with app.app_context():
        # final_blow counts: Combat x3, Commander x1 -> second = 'Commander'.
        # Non-null win turns are {5, 3, 8, 10} -> fastest 3, slowest 10.
        result = get_finisher_stats(1)
        assert result["most_common_final_blow"] == "Combat"
        assert result["second_final_blow"] == "Commander"
        assert result["fastest_win_turns"] == 3
        assert result["slowest_win_turns"] == 10


def test_empty_state_when_all_fields_null(app, seeded):
    with app.app_context():
        result = get_finisher_stats(2)
        assert result == {
            "most_common_final_blow": None,
            "second_final_blow": None,
            "fastest_win_turns": None,
            "slowest_win_turns": None,
            "avg_win_turns": None,
        }


def test_empty_state_when_no_wins(app, seeded):
    with app.app_context():
        result = get_finisher_stats(3)
        assert result == {
            "most_common_final_blow": None,
            "second_final_blow": None,
            "fastest_win_turns": None,
            "slowest_win_turns": None,
            "avg_win_turns": None,
        }


def test_empty_state_for_unknown_player(app, seeded):
    with app.app_context():
        result = get_finisher_stats(999)
        assert result == {
            "most_common_final_blow": None,
            "second_final_blow": None,
            "fastest_win_turns": None,
            "slowest_win_turns": None,
            "avg_win_turns": None,
        }
