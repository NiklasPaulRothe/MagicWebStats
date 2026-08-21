# Feature: raw-sql-to-orm, Property 2: Excluded Player Filtering
"""
Property test verifying that the player stats query functions never include
a player named "Precons" in the result set, regardless of what data exists.

**Validates: Requirements 1.3, 6.4**
"""
from datetime import date, timedelta

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.models import Player, Game, Participant, Deck, ColorIdentity
from app.api.queries import get_player_stats


# --- Strategies ---

# Short non-empty strings for player names (excluding "Precons")
name_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N"), min_codepoint=65, max_codepoint=122
    ),
    min_size=1,
    max_size=15,
).filter(lambda n: n != "Precons")


@st.composite
def players_with_precons(draw):
    """Generate a set of players that always includes one named 'Precons' plus 1-4 other players.

    Creates recent games (within 365 days) with participants for all players,
    ensuring every player has activity so the activity filter doesn't interfere.
    """
    # Generate 1-4 other players with unique names
    num_others = draw(st.integers(min_value=1, max_value=4))
    other_names = draw(
        st.lists(
            name_strategy,
            min_size=num_others,
            max_size=num_others,
            unique=True,
        )
    )

    # Build player list: "Precons" always at index 0, others after
    players = [{"id": 1, "name": "Precons"}]
    for i, name in enumerate(other_names):
        players.append({"id": i + 2, "name": name})

    # Generate one game per player (recent, non-cEDH) so all players have activity
    recent_date = date.today() - timedelta(days=draw(st.integers(min_value=0, max_value=300)))
    games = []
    participants = []
    for idx, player in enumerate(players):
        game_id = idx + 1
        games.append(
            {
                "id": game_id,
                "date": recent_date,
                "cedh": False,
                "winner_id": player["id"],
                "first_player_id": player["id"],
            }
        )
        participants.append(
            {
                "game_id": game_id,
                "player_id": player["id"],
                "deck_id": player["id"],  # Each player gets their own deck
                "early_sol_ring": False,
            }
        )

    return {"players": players, "games": games, "participants": participants}


@given(data=players_with_precons())
@settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_precons_excluded_from_player_stats(app, db_session, data):
    """Property 2: For any dataset that includes a player named 'Precons',
    get_player_stats SHALL never include 'Precons' in the result set.
    Other players with recent activity SHOULD appear.
    """
    with app.app_context():
        # Clear existing data (order matters for FK constraints)
        db_session.query(Participant).delete()
        db_session.query(Game).delete()
        db_session.query(Deck).delete()
        db_session.query(Player).delete()
        db_session.query(ColorIdentity).delete()
        db_session.flush()

        # Insert fixed ColorIdentity to satisfy FK
        ci = ColorIdentity(name="TestColor", amount=1)
        db_session.add(ci)
        db_session.flush()

        # Insert players
        for player_data in data["players"]:
            player = Player(id=player_data["id"], name=player_data["name"])
            db_session.add(player)
        db_session.flush()

        # Insert decks (one per player, needed for Participant FK)
        for player_data in data["players"]:
            deck = Deck(
                id=player_data["id"],
                name=f"Deck_{player_data['name']}",
                commander=f"Commander_{player_data['name']}",
                player_id=player_data["id"],
                active=True,
                color_identity="TestColor",
            )
            db_session.add(deck)
        db_session.flush()

        # Insert games
        for game_data in data["games"]:
            game = Game(
                id=game_data["id"],
                date=game_data["date"],
                cedh=game_data["cedh"],
                winner_id=game_data["winner_id"],
                first_player_id=game_data["first_player_id"],
            )
            db_session.add(game)
        db_session.flush()

        # Insert participants
        for part_data in data["participants"]:
            participant = Participant(
                game_id=part_data["game_id"],
                player_id=part_data["player_id"],
                deck_id=part_data["deck_id"],
                early_sol_ring=part_data["early_sol_ring"],
            )
            db_session.add(participant)
        db_session.flush()

        # Execute query under test
        results = get_player_stats(db_session)
        result_names = [r["name"] for r in results]

        # Property assertion: "Precons" must never appear
        assert "Precons" not in result_names, (
            f"'Precons' found in player stats results: {result_names}"
        )

        # Verify other players DO appear (confirms the query works)
        other_player_names = [
            p["name"] for p in data["players"] if p["name"] != "Precons"
        ]
        for name in other_player_names:
            assert name in result_names, (
                f"Expected player '{name}' not found in results: {result_names}"
            )
