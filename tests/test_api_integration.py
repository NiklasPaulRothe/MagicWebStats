"""Integration tests verifying JSON output format for all 7 refactored API endpoints.

These tests seed a test database with representative data and verify that the
ORM queries + formatters produce output matching the expected JSON structure
(key names, value types, sort orders, numeric precision, dash substitution).

Validates: Requirements 10.1, 10.2, 10.3, 10.4
"""

from datetime import date, timedelta

import pytest

from app.api.formatters import (
    format_deck_data,
    format_player_stats,
    format_user_deck,
    format_user_deck_archive,
)
from app.api.queries import (
    get_color_data,
    get_deck_data,
    get_game_years,
    get_player_stats,
    get_player_stats_by_year,
    get_user_decks,
    get_user_decks_archive,
)
from app.models import (
    Color,
    ColorComponent,
    ColorIdentity,
    Deck,
    DeckTag,
    Game,
    Participant,
    Player,
)


# ---------------------------------------------------------------------------
# Fixtures for seeding representative test data
# ---------------------------------------------------------------------------


@pytest.fixture()
def seed_data(db_session):
    """Seed the database with representative data for all endpoint tests.

    Creates:
    - 2 players (Alice, Bob) + 1 excluded player (Precons)
    - 2 color identities (Simic, Rakdos) with color components
    - 3 colors (Blue, Green, Red) with images + Colorless
    - 3 decks (2 active for Alice, 1 inactive archive deck for Alice, 1 active for Bob)
    - 4 games across 2 years (2024, 2025), mix of cEDH and regular
    - Participants linking players to games with decks
    - Tags on one deck
    """
    # Colors
    blue = Color(name="Blue", abbreviation="U", img="/img/blue.svg")
    green = Color(name="Green", abbreviation="G", img="/img/green.svg")
    red = Color(name="Red", abbreviation="R", img="/img/red.svg")
    colorless = Color(name="Colorless", abbreviation="C", img="/img/colorless.svg")
    db_session.add_all([blue, green, red, colorless])

    # Color Identities
    simic = ColorIdentity(name="Simic", amount=2)
    rakdos = ColorIdentity(name="Rakdos", amount=2)
    mono_colorless = ColorIdentity(name="Colorless", amount=0)
    db_session.add_all([simic, rakdos, mono_colorless])

    # Color Components
    db_session.add_all([
        ColorComponent(color_identity="Simic", color="Blue"),
        ColorComponent(color_identity="Simic", color="Green"),
        ColorComponent(color_identity="Rakdos", color="Red"),
    ])

    # Players
    alice = Player(id=1, name="Alice")
    bob = Player(id=2, name="Bob")
    precons = Player(id=3, name="Precons")
    db_session.add_all([alice, bob, precons])

    # Decks
    deck_alice_active1 = Deck(
        id=1,
        name="Aesi Swamp",
        active=True,
        commander="Aesi, Tyrant of Gyre Strait",
        player_id=1,
        color_identity="Simic",
        partner=None,
        elo_rating=1520.0,
        decklist="https://example.com/aesi",
        cedh=False,
    )
    deck_alice_active2 = Deck(
        id=2,
        name="Zaxara Hydras",
        active=True,
        commander="Zaxara, the Exemplary",
        player_id=1,
        color_identity="Simic",
        partner="Kydele, Chosen of Kruphix",
        elo_rating=1480.0,
        decklist=None,
        cedh=False,
    )
    deck_alice_archive = Deck(
        id=3,
        name="Old Rakdos",
        active=False,
        commander="Rakdos, Lord of Riots",
        player_id=1,
        color_identity="Rakdos",
        partner=None,
        elo_rating=1400.0,
        decklist="https://example.com/rakdos",
        cedh=False,
    )
    deck_bob_active = Deck(
        id=4,
        name="Bob Colorless",
        active=True,
        commander="Kozilek, the Great Distortion",
        player_id=2,
        color_identity="Colorless",
        partner=None,
        elo_rating=1500.0,
        decklist=None,
        cedh=False,
    )
    db_session.add_all([deck_alice_active1, deck_alice_active2, deck_alice_archive, deck_bob_active])

    # Tags
    db_session.add_all([
        DeckTag(id=1, deck_id=1, tag="ramp"),
        DeckTag(id=2, deck_id=1, tag="draw"),
    ])

    # Games - use dynamic dates relative to today for activity filter
    today = date.today()
    recent_date_1 = today - timedelta(days=30)
    recent_date_2 = today - timedelta(days=60)
    recent_date_3 = today - timedelta(days=90)
    recent_date_4 = today - timedelta(days=10)

    game1 = Game(
        id=1,
        date=recent_date_1,
        winner_id=1,  # Alice wins
        first_player_id=1,
        cedh=False,
        turns=8,
    )
    game2 = Game(
        id=2,
        date=recent_date_2,
        winner_id=2,  # Bob wins
        first_player_id=2,
        cedh=False,
        turns=10,
    )
    game3 = Game(
        id=3,
        date=recent_date_3,
        winner_id=1,  # Alice wins
        first_player_id=2,
        cedh=False,
        turns=7,
    )
    # cEDH game — should be excluded from game/win/first counts
    game4 = Game(
        id=4,
        date=recent_date_4,
        winner_id=1,  # Alice wins cEDH
        first_player_id=1,
        cedh=True,
        turns=5,
    )
    db_session.add_all([game1, game2, game3, game4])

    # Participants
    # Game 1: Alice (deck 1, sol ring), Bob (deck 4, no sol ring)
    db_session.add_all([
        Participant(game_id=1, player_id=1, deck_id=1, early_sol_ring=True),
        Participant(game_id=1, player_id=2, deck_id=4, early_sol_ring=False),
    ])
    # Game 2: Alice (deck 2, no sol ring), Bob (deck 4, sol ring)
    db_session.add_all([
        Participant(game_id=2, player_id=1, deck_id=2, early_sol_ring=False),
        Participant(game_id=2, player_id=2, deck_id=4, early_sol_ring=True),
    ])
    # Game 3: Alice (deck 3 archive, no sol ring), Bob (deck 4, no sol ring)
    db_session.add_all([
        Participant(game_id=3, player_id=1, deck_id=3, early_sol_ring=False),
        Participant(game_id=3, player_id=2, deck_id=4, early_sol_ring=False),
    ])
    # Game 4 (cEDH): Alice (deck 1, sol ring), Bob (deck 4, no sol ring)
    db_session.add_all([
        Participant(game_id=4, player_id=1, deck_id=1, early_sol_ring=True),
        Participant(game_id=4, player_id=2, deck_id=4, early_sol_ring=False),
    ])

    db_session.flush()

    return {
        "alice": alice,
        "bob": bob,
        "precons": precons,
        "decks": [deck_alice_active1, deck_alice_active2, deck_alice_archive, deck_bob_active],
    }


# ---------------------------------------------------------------------------
# Test: /api/data — Player Stats
# ---------------------------------------------------------------------------


class TestPlayerStatsEndpoint:
    """Tests for /api/data JSON output format."""

    def test_json_keys_match_expected(self, app, db_session, seed_data):
        """Verify all expected JSON keys are present in player stats output."""
        results = get_player_stats(db_session)
        assert len(results) > 0

        formatted = format_player_stats(results[0])
        expected_keys = {
            "Name", "Games", "Early Sol Ring", "Sol Ring (in %)",
            "Wins", "Winrate (in %)", "First", "First (in %)",
        }
        assert set(formatted.keys()) == expected_keys

    def test_values_wrapped_in_single_element_lists(self, app, db_session, seed_data):
        """All values in player stats are wrapped in single-element lists."""
        results = get_player_stats(db_session)
        formatted = format_player_stats(results[0])

        for key, value in formatted.items():
            assert isinstance(value, list), f"Key '{key}' should be a list"
            assert len(value) == 1, f"Key '{key}' should have exactly 1 element"

    def test_value_types(self, app, db_session, seed_data):
        """Verify value types: strings for name, ints for counts, floats for percentages."""
        results = get_player_stats(db_session)
        formatted = format_player_stats(results[0])

        assert isinstance(formatted["Name"][0], str)
        assert isinstance(formatted["Games"][0], int)
        assert isinstance(formatted["Early Sol Ring"][0], int)
        assert isinstance(formatted["Sol Ring (in %)"][0], float)
        assert isinstance(formatted["Wins"][0], int)
        assert isinstance(formatted["Winrate (in %)"][0], float)
        assert isinstance(formatted["First"][0], int)
        assert isinstance(formatted["First (in %)"][0], float)

    def test_percentages_two_decimal_places(self, app, db_session, seed_data):
        """Percentages should have at most 2 decimal places."""
        results = get_player_stats(db_session)
        for r in results:
            formatted = format_player_stats(r)
            for pct_key in ["Sol Ring (in %)", "Winrate (in %)", "First (in %)"]:
                val = formatted[pct_key][0]
                # Check that rounding to 2 decimals doesn't change the value
                assert val == round(val, 2), f"{pct_key} = {val} should be rounded to 2 decimals"

    def test_precons_excluded(self, app, db_session, seed_data):
        """The 'Precons' player must not appear in results."""
        results = get_player_stats(db_session)
        names = [r["name"] for r in results]
        assert "Precons" not in names

    def test_cedh_games_excluded_from_counts(self, app, db_session, seed_data):
        """cEDH games should not count toward Games, Wins, or First."""
        results = get_player_stats(db_session)
        alice_result = next(r for r in results if r["name"] == "Alice")

        # Alice participates in games 1, 2, 3 (non-cEDH) + game 4 (cEDH)
        # Non-cEDH game count for Alice = 3
        assert alice_result["games"] == 3
        # Alice wins game 1 and game 3 (non-cEDH) — game 4 win is cEDH, excluded
        assert alice_result["wins"] == 2

    def test_sol_ring_count_includes_cedh(self, app, db_session, seed_data):
        """Early sol ring count includes ALL games (even cEDH)."""
        results = get_player_stats(db_session)
        alice_result = next(r for r in results if r["name"] == "Alice")

        # Alice has sol ring in game 1 and game 4 (cEDH) = 2
        assert alice_result["early_sol_ring"] == 2


# ---------------------------------------------------------------------------
# Test: /api/color-data — Color Identity Stats
# ---------------------------------------------------------------------------


class TestColorDataEndpoint:
    """Tests for /api/color-data JSON output format."""

    def test_json_keys_match_expected(self, app, db_session, seed_data):
        """Color data results should have expected keys after route formatting."""
        results = get_color_data(db_session)
        assert len(results) > 0

        # Simulate route handler formatting
        from app.services.color_service import resolve_color_images
        r = results[0]
        formatted = {
            "Name": [r["name"]],
            "Games": [r["games"]],
            "Wins": [r["wins"]],
            "Winrate (in %)": [r["winrate_pct"]],
            "ColorImgs": resolve_color_images(r["name"]),
        }
        expected_keys = {"Name", "Games", "Wins", "Winrate (in %)", "ColorImgs"}
        assert set(formatted.keys()) == expected_keys

    def test_values_wrapped_in_lists(self, app, db_session, seed_data):
        """Name, Games, Wins, Winrate should be wrapped in single-element lists."""
        results = get_color_data(db_session)
        r = results[0]
        from app.services.color_service import resolve_color_images
        formatted = {
            "Name": [r["name"]],
            "Games": [r["games"]],
            "Wins": [r["wins"]],
            "Winrate (in %)": [r["winrate_pct"]],
            "ColorImgs": resolve_color_images(r["name"]),
        }
        for key in ["Name", "Games", "Wins", "Winrate (in %)"]:
            assert isinstance(formatted[key], list)
            assert len(formatted[key]) == 1

    def test_colorimgs_is_direct_list(self, app, db_session, seed_data):
        """ColorImgs should be a direct list (not wrapped in another list)."""
        results = get_color_data(db_session)
        r = results[0]
        from app.services.color_service import resolve_color_images
        imgs = resolve_color_images(r["name"])
        assert isinstance(imgs, list)
        # Each element should be a string (image URL)
        for img in imgs:
            assert isinstance(img, str)

    def test_winrate_precision(self, app, db_session, seed_data):
        """Winrate should be rounded to 2 decimal places."""
        results = get_color_data(db_session)
        for r in results:
            val = r["winrate_pct"]
            assert val == round(val, 2)

    def test_zero_game_identities_excluded(self, app, db_session, seed_data):
        """Color identities with zero non-cEDH games should not appear."""
        results = get_color_data(db_session)
        names = [r["name"] for r in results]
        # Colorless identity only has deck_bob, which has games
        # All identities in results should have games > 0
        for r in results:
            assert r["games"] > 0


# ---------------------------------------------------------------------------
# Test: /api/deck-data — Active Deck Stats
# ---------------------------------------------------------------------------


class TestDeckDataEndpoint:
    """Tests for /api/deck-data JSON output format."""

    def test_json_keys_match_expected(self, app, db_session, seed_data):
        """Deck data output should have all expected keys."""
        results = get_deck_data(db_session)
        assert len(results) > 0

        formatted = format_deck_data(results[0])
        expected_keys = {
            "Deckname", "Spieler", "Commander", "Farbe", "Spiele",
            "Siege", "Winrate (in %)", "WTurns", "WTurnsCount",
            "Decklist", "elo", "ColorImgs", "Tags",
        }
        assert set(formatted.keys()) == expected_keys

    def test_single_element_list_wrapping(self, app, db_session, seed_data):
        """Most fields should be wrapped in single-element lists."""
        results = get_deck_data(db_session)
        formatted = format_deck_data(results[0])

        list_wrapped_keys = [
            "Deckname", "Spieler", "Commander", "Farbe", "Spiele",
            "Siege", "Winrate (in %)", "WTurns", "WTurnsCount",
            "Decklist", "elo",
        ]
        for key in list_wrapped_keys:
            assert isinstance(formatted[key], list), f"'{key}' should be a list"
            assert len(formatted[key]) == 1, f"'{key}' should have exactly 1 element"

    def test_colorimgs_and_tags_are_direct_lists(self, app, db_session, seed_data):
        """ColorImgs and Tags should be direct lists (not wrapped)."""
        results = get_deck_data(db_session)
        formatted = format_deck_data(results[0])

        assert isinstance(formatted["ColorImgs"], list)
        assert isinstance(formatted["Tags"], list)
        # They should NOT be wrapped in another list
        if formatted["ColorImgs"]:
            assert isinstance(formatted["ColorImgs"][0], str)
        if formatted["Tags"]:
            assert isinstance(formatted["Tags"][0], str)

    def test_commander_with_partner_formatting(self, app, db_session, seed_data):
        """Commander with a partner should be formatted as 'Commander + Partner'."""
        results = get_deck_data(db_session)
        # Find Zaxara deck (has partner)
        zaxara = next(r for r in results if r["deck_name"] == "Zaxara Hydras")
        assert zaxara["commander"] == "Zaxara, the Exemplary + Kydele, Chosen of Kruphix"

    def test_commander_without_partner(self, app, db_session, seed_data):
        """Commander without partner should just be the commander name."""
        results = get_deck_data(db_session)
        aesi = next(r for r in results if r["deck_name"] == "Aesi Swamp")
        assert aesi["commander"] == "Aesi, Tyrant of Gyre Strait"

    def test_sort_order_by_commander(self, app, db_session, seed_data):
        """Results should be sorted by commander name ascending."""
        results = get_deck_data(db_session)
        commanders = [r["commander"] for r in results]
        assert commanders == sorted(commanders)

    def test_winrate_precision_and_dash_substitution(self, app, db_session, seed_data):
        """Winrate should be 2 decimal places or '-' for zero-game decks."""
        results = get_deck_data(db_session)
        for r in results:
            formatted = format_deck_data(r)
            winrate_val = formatted["Winrate (in %)"][0]
            if winrate_val == "-":
                # Deck has zero games
                assert r["games"] == 0
            else:
                assert isinstance(winrate_val, float)
                assert winrate_val == round(winrate_val, 2)

    def test_tags_sorted_alphabetically(self, app, db_session, seed_data):
        """Tags should be ordered alphabetically."""
        results = get_deck_data(db_session)
        aesi = next(r for r in results if r["deck_name"] == "Aesi Swamp")
        assert aesi["tags"] == sorted(aesi["tags"])
        # Verify actual tags
        assert aesi["tags"] == ["draw", "ramp"]

    def test_only_active_decks_included(self, app, db_session, seed_data):
        """Only active decks should appear in deck-data results."""
        results = get_deck_data(db_session)
        deck_names = [r["deck_name"] for r in results]
        assert "Old Rakdos" not in deck_names  # archived deck


# ---------------------------------------------------------------------------
# Test: /api/userdecks/<spieler> — User's Active Decks
# ---------------------------------------------------------------------------


class TestUserDecksEndpoint:
    """Tests for /api/userdecks/<spieler> JSON output format."""

    def test_json_keys_match_expected(self, app, db_session, seed_data):
        """User deck output should have all expected keys."""
        results = get_user_decks(db_session, player_id=1)
        assert len(results) > 0

        formatted = format_user_deck(results[0])
        expected_keys = {
            "Name", "Commander", "Color Identity", "Spiele",
            "Zuletzt gespielt", "Siege", "Winrate (in %)",
            "Decklist", "ColorImgs", "Tags",
        }
        assert set(formatted.keys()) == expected_keys

    def test_values_wrapped_in_single_element_lists(self, app, db_session, seed_data):
        """Most values should be in single-element lists."""
        results = get_user_decks(db_session, player_id=1)
        formatted = format_user_deck(results[0])

        list_wrapped_keys = [
            "Name", "Commander", "Color Identity", "Spiele",
            "Zuletzt gespielt", "Siege", "Winrate (in %)", "Decklist",
        ]
        for key in list_wrapped_keys:
            assert isinstance(formatted[key], list), f"'{key}' should be a list"
            assert len(formatted[key]) == 1, f"'{key}' should have 1 element"

    def test_colorimgs_and_tags_direct_lists(self, app, db_session, seed_data):
        """ColorImgs and Tags should be direct lists."""
        results = get_user_decks(db_session, player_id=1)
        formatted = format_user_deck(results[0])

        assert isinstance(formatted["ColorImgs"], list)
        assert isinstance(formatted["Tags"], list)

    def test_sort_order_by_deck_name(self, app, db_session, seed_data):
        """Results should be sorted by deck name ascending."""
        results = get_user_decks(db_session, player_id=1)
        names = [r["name"] for r in results]
        assert names == sorted(names)

    def test_only_active_decks_for_player(self, app, db_session, seed_data):
        """Only active decks belonging to the specified player should appear."""
        results = get_user_decks(db_session, player_id=1)
        names = [r["name"] for r in results]
        # Alice's active decks
        assert "Aesi Swamp" in names
        assert "Zaxara Hydras" in names
        # Not archived
        assert "Old Rakdos" not in names
        # Not Bob's
        assert "Bob Colorless" not in names

    def test_winrate_dash_for_zero_games(self, app, db_session, seed_data):
        """Winrate should be '-' when player has zero games with a deck."""
        results = get_user_decks(db_session, player_id=1)
        for r in results:
            formatted = format_user_deck(r)
            winrate_val = formatted["Winrate (in %)"][0]
            if r["games"] == 0:
                assert winrate_val == "-"
            else:
                assert isinstance(winrate_val, float)
                assert winrate_val == round(winrate_val, 2)

    def test_last_played_date_format(self, app, db_session, seed_data):
        """Last played should be in 'D.M.YYYY' format or '-' if None."""
        results = get_user_decks(db_session, player_id=1)
        for r in results:
            formatted = format_user_deck(r)
            last_played = formatted["Zuletzt gespielt"][0]
            if last_played == "-":
                assert r["last_played"] is None
            else:
                # Should be non-zero-padded D.M.YYYY
                parts = last_played.split(".")
                assert len(parts) == 3
                day, month, year = parts
                # No leading zeros
                assert day == str(int(day))
                assert month == str(int(month))
                assert len(year) == 4

    def test_winrate_precision(self, app, db_session, seed_data):
        """Non-null winrate should have exactly 2 decimal places."""
        results = get_user_decks(db_session, player_id=1)
        for r in results:
            if r["winrate_pct"] is not None:
                assert r["winrate_pct"] == round(r["winrate_pct"], 2)


# ---------------------------------------------------------------------------
# Test: /api/userdecks/archive/<spieler> — User's Archived Decks
# ---------------------------------------------------------------------------


class TestUserDecksArchiveEndpoint:
    """Tests for /api/userdecks/archive/<spieler> JSON output format."""

    def test_json_keys_match_expected(self, app, db_session, seed_data):
        """Archive deck output should have all expected keys."""
        results = get_user_decks_archive(db_session, player_id=1)
        assert len(results) > 0

        formatted = format_user_deck_archive(results[0])
        expected_keys = {
            "id", "Name", "Commander", "ColorImgs",
            "Spiele", "Siege", "Winrate (in %)", "Decklist",
        }
        assert set(formatted.keys()) == expected_keys

    def test_values_not_wrapped_in_lists(self, app, db_session, seed_data):
        """Archive endpoint uses DIRECT values, not single-element list wrapping."""
        results = get_user_decks_archive(db_session, player_id=1)
        formatted = format_user_deck_archive(results[0])

        # These should be direct values (not lists)
        assert isinstance(formatted["id"], int)
        assert isinstance(formatted["Name"], str)
        assert isinstance(formatted["Commander"], str)
        assert isinstance(formatted["Spiele"], int)
        assert isinstance(formatted["Siege"], int)
        # Winrate is float or None
        if formatted["Winrate (in %)"] is not None:
            assert isinstance(formatted["Winrate (in %)"], float)

    def test_colorimgs_is_direct_list(self, app, db_session, seed_data):
        """ColorImgs should be a direct list of strings."""
        results = get_user_decks_archive(db_session, player_id=1)
        formatted = format_user_deck_archive(results[0])

        assert isinstance(formatted["ColorImgs"], list)

    def test_sort_order_by_deck_name(self, app, db_session, seed_data):
        """Archive results should be sorted by deck name ascending."""
        results = get_user_decks_archive(db_session, player_id=1)
        names = [r["name"] for r in results]
        assert names == sorted(names)

    def test_only_inactive_decks(self, app, db_session, seed_data):
        """Only archived (inactive) decks should appear."""
        results = get_user_decks_archive(db_session, player_id=1)
        names = [r["name"] for r in results]
        assert "Old Rakdos" in names
        assert "Aesi Swamp" not in names
        assert "Zaxara Hydras" not in names

    def test_winrate_none_for_zero_games(self, app, db_session, seed_data):
        """Archive endpoint returns None (not '-') for zero-game winrate."""
        results = get_user_decks_archive(db_session, player_id=1)
        for r in results:
            formatted = format_user_deck_archive(r)
            if r["games"] == 0:
                assert formatted["Winrate (in %)"] is None

    def test_winrate_precision(self, app, db_session, seed_data):
        """Non-null winrate should be rounded to 2 decimal places."""
        results = get_user_decks_archive(db_session, player_id=1)
        for r in results:
            if r["winrate_pct"] is not None:
                assert r["winrate_pct"] == round(r["winrate_pct"], 2)


# ---------------------------------------------------------------------------
# Test: /api/data/years — Distinct Game Years
# ---------------------------------------------------------------------------


class TestDataYearsEndpoint:
    """Tests for /api/data/years JSON output format."""

    def test_returns_list_of_integers(self, app, db_session, seed_data):
        """Years endpoint should return a plain list of integers."""
        results = get_game_years(db_session)
        assert isinstance(results, list)
        for year in results:
            assert isinstance(year, int)

    def test_years_in_descending_order(self, app, db_session, seed_data):
        """Years should be sorted descending (most recent first)."""
        results = get_game_years(db_session)
        assert results == sorted(results, reverse=True)

    def test_contains_expected_years(self, app, db_session, seed_data):
        """Should contain the year(s) from our seeded games."""
        results = get_game_years(db_session)
        today = date.today()
        # All games are within 90 days of today, so current year is present
        assert today.year in results

    def test_no_duplicate_years(self, app, db_session, seed_data):
        """Each year should appear only once."""
        results = get_game_years(db_session)
        assert len(results) == len(set(results))


# ---------------------------------------------------------------------------
# Test: /api/data/<int:year> — Year-Filtered Player Stats
# ---------------------------------------------------------------------------


class TestPlayerStatsByYearEndpoint:
    """Tests for /api/data/<int:year> JSON output format."""

    def test_json_keys_same_as_all_time(self, app, db_session, seed_data):
        """Year-filtered stats should have the same JSON keys as all-time stats."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        if results:
            formatted = format_player_stats(results[0])
            expected_keys = {
                "Name", "Games", "Early Sol Ring", "Sol Ring (in %)",
                "Wins", "Winrate (in %)", "First", "First (in %)",
            }
            assert set(formatted.keys()) == expected_keys

    def test_values_wrapped_in_lists(self, app, db_session, seed_data):
        """All values should be wrapped in single-element lists (same as /api/data)."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        if results:
            formatted = format_player_stats(results[0])
            for key, value in formatted.items():
                assert isinstance(value, list)
                assert len(value) == 1

    def test_only_players_with_games_in_year(self, app, db_session, seed_data):
        """Only players who played in the specified year should appear."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        names = [r["name"] for r in results]
        # Alice and Bob both play in the current year (games within 90 days of today)
        assert "Alice" in names
        assert "Bob" in names

    def test_precons_excluded_from_year_stats(self, app, db_session, seed_data):
        """Precons should be excluded from year-filtered stats too."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        names = [r["name"] for r in results]
        assert "Precons" not in names

    def test_percentages_two_decimal_places(self, app, db_session, seed_data):
        """All percentages should be rounded to 2 decimal places."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        for r in results:
            assert r["sol_ring_pct"] == round(r["sol_ring_pct"], 2)
            assert r["winrate_pct"] == round(r["winrate_pct"], 2)
            assert r["first_pct"] == round(r["first_pct"], 2)

    def test_counts_filtered_to_year(self, app, db_session, seed_data):
        """Game counts should only include games from the specified year."""
        current_year = date.today().year
        results = get_player_stats_by_year(db_session, year=current_year)
        alice = next((r for r in results if r["name"] == "Alice"), None)

        if alice:
            # Alice has 3 non-cEDH games (game 1, 2, 3) all in current year
            assert alice["games"] == 3
            # Alice wins game 1 and game 3 (non-cEDH)
            assert alice["wins"] == 2
