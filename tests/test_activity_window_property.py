# Feature: raw-sql-to-orm, Property 3: Activity Window Filtering
"""
Property test verifying that `get_player_stats()` returns only players with
at least one game within the last 365 days (activity window filtering).

Players whose games are ALL older than 365 days should be excluded from results.
Players with at least one recent game should appear.

**Validates: Requirements 1.4**
"""
from datetime import date, timedelta

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Game, Participant, Deck, ColorIdentity
from app.api.queries import get_player_stats


# --- Strategies ---

player_name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), min_codepoint=65, max_codepoint=122),
    min_size=2,
    max_size=12,
).filter(lambda n: n != "Precons")


@st.composite
def activity_window_data(draw):
    """Generate a dataset with a mix of active and inactive players.

    - Active players have at least one game within 365 days of today.
    - Inactive players have ALL games older than 365 days.
    - All games are non-cEDH to avoid zero game count edge cases.
    """
    today = date.today()
    cutoff = today - timedelta(days=365)

    # Generate unique player names (at least 2 players)
    num_players = draw(st.integers(min_value=2, max_value=5))
    names = draw(
        st.lists(
            player_name_strategy,
            min_size=num_players,
            max_size=num_players,
            unique=True,
        )
    )

    # Decide which players are active vs inactive (at least 1 of each)
    # We pick a split point ensuring at least 1 active and 1 inactive
    split = draw(st.integers(min_value=1, max_value=num_players - 1))
    active_names = names[:split]
    inactive_names = names[split:]

    # Generate game dates for active players (at least one recent game each)
    active_games = {}
    for name in active_names:
        # At least 1 recent game (within the last 365 days)
        num_recent = draw(st.integers(min_value=1, max_value=3))
        recent_dates = draw(
            st.lists(
                st.dates(min_value=cutoff, max_value=today),
                min_size=num_recent,
                max_size=num_recent,
            )
        )
        # Optionally some old games too
        num_old = draw(st.integers(min_value=0, max_value=2))
        old_dates = draw(
            st.lists(
                st.dates(
                    min_value=today - timedelta(days=800),
                    max_value=cutoff - timedelta(days=1),
                ),
                min_size=num_old,
                max_size=num_old,
            )
        )
        active_games[name] = recent_dates + old_dates

    # Generate game dates for inactive players (ALL older than 365 days)
    inactive_games = {}
    for name in inactive_names:
        num_old = draw(st.integers(min_value=1, max_value=3))
        old_dates = draw(
            st.lists(
                st.dates(
                    min_value=today - timedelta(days=800),
                    max_value=cutoff - timedelta(days=1),
                ),
                min_size=num_old,
                max_size=num_old,
            )
        )
        inactive_games[name] = old_dates

    return {
        "active_names": active_names,
        "inactive_names": inactive_names,
        "active_games": active_games,
        "inactive_games": inactive_games,
    }


@given(data=activity_window_data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_activity_window_filtering(app, db_session, data):
    """Property 3: For any set of players where some have games only older than
    365 days and others have at least one game within 365 days of the current date,
    the all-time player stats query SHALL return only players with recent activity.
    """
    with app.app_context():
        # Clean relevant tables (order matters for FK constraints)
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Create a color identity for the decks
        ci = ColorIdentity(name="TestCI", amount=1)
        db_session.add(ci)
        db_session.flush()

        # Create players and their games
        all_names = data["active_names"] + data["inactive_names"]
        all_games_map = {**data["active_games"], **data["inactive_games"]}

        player_id_counter = 1
        game_id_counter = 1
        deck_id_counter = 1

        for name in all_names:
            player = Player(id=player_id_counter, name=name)
            db_session.add(player)

            # Create a deck for this player
            deck = Deck(
                id=deck_id_counter,
                name=f"Deck_{name}",
                active=True,
                commander="TestCommander",
                player_id=player_id_counter,
                color_identity="TestCI",
                cedh=False,
            )
            db_session.add(deck)
            db_session.flush()

            # Create games for this player
            for game_date in all_games_map[name]:
                game = Game(
                    id=game_id_counter,
                    date=game_date,
                    cedh=False,
                )
                db_session.add(game)
                db_session.flush()

                participant = Participant(
                    game_id=game_id_counter,
                    player_id=player_id_counter,
                    deck_id=deck_id_counter,
                    early_sol_ring=False,
                )
                db_session.add(participant)
                game_id_counter += 1

            player_id_counter += 1
            deck_id_counter += 1

        db_session.flush()

        # Call the query function
        results = get_player_stats(db_session)
        result_names = {r["name"] for r in results}

        # Active players MUST appear in results
        for name in data["active_names"]:
            assert name in result_names, (
                f"Active player '{name}' should appear in results but didn't. "
                f"Got: {result_names}"
            )

        # Inactive players MUST NOT appear in results
        for name in data["inactive_names"]:
            assert name not in result_names, (
                f"Inactive player '{name}' should NOT appear in results but did. "
                f"Got: {result_names}"
            )
