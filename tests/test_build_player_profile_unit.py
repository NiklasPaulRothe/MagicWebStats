"""Unit tests for stats_service.build_player_profile.

Covers the orchestrator that merges compute_player_overview plus the per-
section aggregates into a single profile context dict:
  - a happy-path test seeding a small dataset and asserting every expected
    section key is present with sane values; and
  - a defensiveness test that monkeypatches one sub-function to raise and
    asserts the profile still builds, with the failed section falling back to
    its neutral default while the other sections stay populated.

Validates: Requirements 3.1, 3.2, 3.3, 13.1, 13.3
"""

from datetime import date

import pytest

from app.models import Player, Deck, Game, Participant, ColorIdentity
import app.services.stats_service as stats_service
from app.services.stats_service import build_player_profile


@pytest.fixture()
def seeded(app, db_session):
    """Seed a small, deterministic dataset exercising every profile section.

    Players:
        1 = subject, 2 = frequent opponent, 3/4 = fillers.

    Decks (subject owns two so deck-highlights has something to pick):
        d1  player 1  active  elo 1500
        d2  player 1  active  elo 1700   -> aggregate elo = round((1500+1700)/2) = 1600
        d2.. opponents own their own decks

    Games (all non-cEDH unless noted) — the subject (player 1) is in each:
        g1  2025-01-01  winner=1  turns=5  final_blow='Combat'   pod {1,2,3}
        g2  2025-02-01  winner=2  turns=7  final_blow='Combat'   pod {1,2,3}
        g3  2025-03-01  winner=1  turns=3  final_blow='Commander' pod {1,2}
        g4  2025-04-01  cEDH      winner=1 turns=1  final_blow='Combat' pod {1,2}  -> excluded

    Subject participations carry removal_played / targeted_by_removal so the
    interaction section has data. Player 2 shares 3 non-cEDH games with the
    subject (g1, g2, g3) so head-to-head at the default min_games=10 yields an
    empty list — that is still a valid, sane section value.
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

        for pid, name in [(1, "Subject"), (2, "Opp2"), (3, "Opp3"), (4, "Opp4")]:
            db_session.add(Player(id=pid, name=name))
        db_session.flush()

        # Subject's two decks (rated) + one deck per opponent.
        db_session.add(Deck(
            id=1, name="Deck_1a", commander="Cmd_1a",
            player_id=1, active=True, color_identity="TestColor", elo_rating=1500,
        ))
        db_session.add(Deck(
            id=2, name="Deck_1b", commander="Cmd_1b",
            player_id=1, active=True, color_identity="TestColor", elo_rating=1700,
        ))
        for did, pid in [(3, 2), (4, 3), (5, 4)]:
            db_session.add(Deck(
                id=did, name=f"Deck_{did}", commander=f"Cmd_{did}",
                player_id=pid, active=True, color_identity="TestColor",
            ))
        db_session.flush()

        games = [
            dict(id=1, date=date(2025, 1, 1), cedh=False, winner_id=1, turns=5, final_blow="Combat"),
            dict(id=2, date=date(2025, 2, 1), cedh=False, winner_id=2, turns=7, final_blow="Combat"),
            dict(id=3, date=date(2025, 3, 1), cedh=False, winner_id=1, turns=3, final_blow="Commander"),
            dict(id=4, date=date(2025, 4, 1), cedh=True, winner_id=1, turns=1, final_blow="Combat"),
        ]
        for g in games:
            db_session.add(Game(**g))
        db_session.flush()

        # pods and the deck the subject piloted in each game (deck 1).
        pods = {1: [1, 2, 3], 2: [1, 2, 3], 3: [1, 2], 4: [1, 2]}
        for gid, pids in pods.items():
            for pid in pids:
                deck_id = 1 if pid == 1 else (pid + 1)  # subject -> deck 1
                part = Participant(
                    game_id=gid, player_id=pid, deck_id=deck_id,
                )
                if pid == 1:
                    part.removal_played = 2
                    part.targeted_by_removal = 1
                db_session.add(part)
        db_session.flush()
        yield db_session


EXPECTED_SECTION_KEYS = {
    "overview",
    "recent_games",
    "highlights",
    "head_to_head",
    "win_trend",
    "aggregate_elo",
    "finishers",
    "interaction",
    "color_usage",
}


def test_merged_dict_contains_all_sections_with_sane_values(app, seeded):
    with app.app_context():
        profile = build_player_profile(1)

        # All design-named sections present.
        assert set(profile.keys()) == EXPECTED_SECTION_KEYS

        # Overview: subject played 3 non-cEDH games, won 2 (g1, g3).
        assert profile["overview"]["games"] == 3
        assert profile["overview"]["wins"] == 2

        # Recent games: 3 non-cEDH entries, newest first, cEDH excluded.
        recent = profile["recent_games"]
        assert len(recent) == 3
        assert [r["date"] for r in recent] == [
            date(2025, 3, 1), date(2025, 2, 1), date(2025, 1, 1)
        ]

        # Deck highlights: subject's most-played deck is Deck_1 (3 games).
        assert profile["highlights"]["most_played"] is not None
        assert profile["highlights"]["most_played"]["name"] == "Deck_1a"

        # Head-to-head at default min_games=10 -> empty (only 3 shared games).
        assert profile["head_to_head"] == []

        # Win trend: one bucket per month that has a game (Jan, Feb, Mar).
        periods = [b["period"] for b in profile["win_trend"]]
        assert periods == ["2025-01", "2025-02", "2025-03"]

        # Aggregate elo: round((1500 + 1700) / 2) = 1600.
        assert profile["aggregate_elo"] == 1600

        # Finishers: mode of wins' final_blow is 'Combat' (g1); fastest = 3 (g3).
        assert profile["finishers"]["most_common_final_blow"] == "Combat"
        assert profile["finishers"]["fastest_win_turns"] == 3

        # Interaction: subject's own removal/targeted averages.
        assert profile["interaction"]["removal_played"]["avg"] == 2.0
        assert profile["interaction"]["targeted_by_removal"]["avg"] == 1.0

        # color_usage mirrors the overview section exactly.
        assert profile["color_usage"] == profile["overview"]["color_usage"]


def test_one_failing_section_does_not_blank_the_profile(app, seeded, monkeypatch):
    """If a sub-function raises, that section gets its neutral default and the
    rest of the profile still builds."""
    with app.app_context():
        def boom(*args, **kwargs):
            raise RuntimeError("simulated section failure")

        # Patch on the module so the orchestrator's internal call is affected.
        monkeypatch.setattr(stats_service, "get_recent_games", boom)

        # The orchestrator calls db.session.rollback() when a section fails
        # (matching the index route's pattern so a poisoned query can't leak
        # into later sections). Under the test fixture the seed data lives in a
        # nested transaction/savepoint, so a real rollback would also discard
        # the seed rows and starve the remaining sections — an artifact of the
        # fixture, not production (where seed data is committed). Neutralize the
        # rollback here so the test isolates the orchestrator's control flow:
        # one section fails -> its default; every other section still runs
        # against the seeded data.
        from app import db as _db
        monkeypatch.setattr(_db.session, "rollback", lambda: None)

        profile = build_player_profile(1)

        # Still a complete dict with every section key present.
        assert set(profile.keys()) == EXPECTED_SECTION_KEYS

        # The failed section fell back to its neutral default (empty list).
        assert profile["recent_games"] == []

        # Other sections remain populated with real data.
        assert profile["overview"]["games"] == 3
        assert profile["overview"]["wins"] == 2
        assert profile["aggregate_elo"] == 1600
        assert profile["finishers"]["most_common_final_blow"] == "Combat"
        assert profile["interaction"]["removal_played"]["avg"] == 2.0
        assert profile["win_trend"] != []
        assert profile["highlights"]["most_played"] is not None
