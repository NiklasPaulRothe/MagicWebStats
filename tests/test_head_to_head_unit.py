"""Unit tests for stats_service.get_head_to_head.

Covers the shared-games threshold boundary (9 excluded / 10 included),
win/loss/winrate aggregation, cEDH exclusion, sorting by shared games, the
custom ``min_games`` parameter, and the empty state.

Validates: Requirements covered by task 6.1 (head-to-head threshold,
win/loss counts, cEDH exclusion).
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
from app.services.stats_service import get_head_to_head


@pytest.fixture()
def seeded(app, db_session):
    """Seed deterministic head-to-head scenarios keyed by subject player 1.

    Subject = player 1 (deck 1). Opponents each own their own deck and share a
    controlled number of non-cEDH games with the subject:

        Opp9  (player 2, deck 2):  9 non-cEDH shared games  -> EXCLUDED @10
        Opp10 (player 3, deck 3): 10 non-cEDH shared games  -> INCLUDED @10
            of those 10 the subject wins 6 -> losses 4, winrate 60.0
        Opp12 (player 4, deck 4): 12 non-cEDH shared games  -> most shared
            plus 3 cEDH shared games that must NOT be counted; subject wins 3
            of the 12 non-cEDH -> winrate 25.0
        OppCedh (player 5, deck 5): only 5 cEDH shared games -> never counted

    Each game has a winner_id and the subject + one opponent as participants,
    so wins are attributable via Game.winner_id == subject.

    Player 6 (Lonely) has no games at all for the empty-state test.
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

        players = [
            (1, "Subject"),
            (2, "Opp9"),
            (3, "Opp10"),
            (4, "Opp12"),
            (5, "OppCedh"),
            (6, "Lonely"),
        ]
        for pid, name in players:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        # Each player gets their own deck (deck id == player id for clarity).
        for pid, _ in players:
            db_session.add(Deck(
                id=pid, name=f"Deck{pid}", commander=f"Cmd{pid}",
                player_id=pid, active=True, color_identity="TestColor",
            ))
        db_session.flush()

        gid = 1

        def add_shared_game(opponent_id, opponent_deck_id, subject_won, cedh=False):
            """Add a game shared by the subject (deck 1) and one opponent."""
            nonlocal gid
            winner = 1 if subject_won else opponent_id
            db_session.add(Game(
                id=gid, date=date(2025, 1, 1), cedh=cedh, winner_id=winner,
            ))
            db_session.add(Participant(game_id=gid, player_id=1, deck_id=1))
            db_session.add(Participant(
                game_id=gid, player_id=opponent_id, deck_id=opponent_deck_id,
            ))
            gid += 1

        # Opp9: exactly 9 non-cEDH shared games (subject wins some, irrelevant)
        for i in range(9):
            add_shared_game(2, 2, subject_won=(i < 4))

        # Opp10: exactly 10 non-cEDH shared games, subject wins 6
        for i in range(10):
            add_shared_game(3, 3, subject_won=(i < 6))

        # Opp12: 12 non-cEDH shared games, subject wins 3; plus 3 cEDH games
        # (subject "wins" all cEDH ones to prove they are ignored for wins too).
        for i in range(12):
            add_shared_game(4, 4, subject_won=(i < 3))
        for _ in range(3):
            add_shared_game(4, 4, subject_won=True, cedh=True)

        # OppCedh: only cEDH shared games -> never counted at all
        for _ in range(5):
            add_shared_game(5, 5, subject_won=True, cedh=True)

        db_session.flush()
        yield db_session


def test_threshold_boundary_nine_excluded_ten_included(app, seeded):
    with app.app_context():
        result = get_head_to_head(1)  # default min_games=10
        ids = {row["opponent_id"] for row in result}
        # Opp9 (9 shared) excluded; Opp10 (10 shared) and Opp12 (12) included.
        assert 2 not in ids
        assert 3 in ids
        assert 4 in ids
        by_id = {row["opponent_id"]: row for row in result}
        assert by_id[3]["games"] == 10


def test_win_loss_counts_and_winrate(app, seeded):
    with app.app_context():
        result = get_head_to_head(1)
        by_id = {row["opponent_id"]: row for row in result}

        opp10 = by_id[3]
        assert opp10["games"] == 10
        assert opp10["wins"] == 6
        assert opp10["losses"] == 4
        assert opp10["wins"] + opp10["losses"] == opp10["games"]
        assert opp10["winrate"] == round(6 / 10 * 100, 1)  # 60.0


def test_cedh_games_excluded_from_counts_and_wins(app, seeded):
    with app.app_context():
        result = get_head_to_head(1)
        by_id = {row["opponent_id"]: row for row in result}

        # Opp12 shares 12 non-cEDH + 3 cEDH games. cEDH must not be counted,
        # so games stays 12 (not 15) and wins stays 3 (cEDH "wins" ignored).
        opp12 = by_id[4]
        assert opp12["games"] == 12
        assert opp12["wins"] == 3
        assert opp12["losses"] == 9
        assert opp12["winrate"] == round(3 / 12 * 100, 1)  # 25.0

        # OppCedh (player 5) only ever shared cEDH games -> never appears.
        assert 5 not in by_id


def test_sorted_by_shared_games_descending(app, seeded):
    with app.app_context():
        result = get_head_to_head(1)
        games_sequence = [row["games"] for row in result]
        assert games_sequence == sorted(games_sequence, reverse=True)
        # Opp12 (12) comes before Opp10 (10).
        assert result[0]["opponent_id"] == 4
        assert result[1]["opponent_id"] == 3


def test_custom_min_games_includes_low_count_opponents(app, seeded):
    with app.app_context():
        result = get_head_to_head(1, min_games=1)
        ids = {row["opponent_id"] for row in result}
        # With a threshold of 1, the 9-game opponent now qualifies too.
        assert ids == {2, 3, 4}
        by_id = {row["opponent_id"]: row for row in result}
        assert by_id[2]["games"] == 9
        # cEDH-only opponent still never counts, even at min_games=1.
        assert 5 not in ids


def test_empty_when_subject_has_no_games(app, seeded):
    with app.app_context():
        # Player 6 has no games at all.
        assert get_head_to_head(6) == []


def test_empty_when_no_opponent_meets_threshold(app, seeded):
    with app.app_context():
        # Highest shared count is 12; a threshold above that yields nothing.
        assert get_head_to_head(1, min_games=13) == []


def test_empty_for_unknown_player(app, seeded):
    with app.app_context():
        assert get_head_to_head(999) == []
