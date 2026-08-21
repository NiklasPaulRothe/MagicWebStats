# Feature: service-layer-security-refactor, Property 9: Atomic game creation
"""Property-based test for atomic game creation.

**Validates: Requirements 7.1, 7.2, 7.3, 7.6**

For any valid game data and list of N participant inputs, `create_game()` SHALL
persist exactly one Game row and exactly N Participant rows, all within a single
commit. If any participant insertion fails, no Game or Participant rows from that
call SHALL remain in the database.
"""

from datetime import date
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app import db
from app.models import Game, Participant, Player, Deck, ColorIdentity, User
from app.services.game_service import create_game, ParticipantInput


# --- Strategies ---

name_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N'), min_codepoint=65, max_codepoint=122),
    min_size=1,
    max_size=15,
)

# Date strategy: reasonable game dates
date_strategy = st.dates(
    min_value=date(2020, 1, 1),
    max_value=date(2030, 12, 31),
)


@st.composite
def game_creation_data(draw):
    """Generate valid game data with N participants.

    Ensures:
    - All player_ids are unique (composite PK constraint: game_id + player_id)
    - Each participant references a valid player and deck
    - first_player_id and winner_id reference valid players
    - FK constraints are satisfiable (Players, Decks, ColorIdentity exist)
    """
    # Generate 2-6 unique players (typical Commander pod sizes)
    num_players = draw(st.integers(min_value=2, max_value=6))
    player_names = draw(
        st.lists(
            name_strategy,
            min_size=num_players,
            max_size=num_players,
            unique=True,
        )
    )
    players = [{'id': i + 1, 'name': name} for i, name in enumerate(player_names)]
    player_ids = [p['id'] for p in players]

    # Generate one deck per player (simplest FK satisfaction)
    decks = []
    for i, player in enumerate(players):
        deck_name = draw(name_strategy)
        commander = draw(name_strategy)
        decks.append({
            'id': i + 1,
            'name': deck_name,
            'commander': commander,
            'player_id': player['id'],
            'active': True,
            'color_identity': 'TestCI',
        })

    # Select first_player and winner from participants
    first_player_id = draw(st.sampled_from(player_ids))
    winner_id = draw(st.sampled_from(player_ids))

    # Game metadata
    game_date = draw(date_strategy)
    turns = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=30)))
    cedh = draw(st.booleans())

    # Build participant inputs — all players participate, each with their deck
    participant_inputs = []
    for i, player in enumerate(players):
        participant_inputs.append({
            'player_id': player['id'],
            'deck_id': decks[i]['id'],
            'early_sol_ring': draw(st.booleans()),
            'mulligans': draw(st.one_of(st.none(), st.integers(min_value=0, max_value=5))),
        })

    return {
        'players': players,
        'decks': decks,
        'game_date': game_date,
        'first_player_id': first_player_id,
        'winner_id': winner_id,
        'participants': participant_inputs,
        'turns': turns,
        'cedh': cedh,
    }


@given(data=game_creation_data())
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_atomic_game_creation_success(app, data):
    """Property 9 (success path): For any valid game data and list of N participant
    inputs, create_game() SHALL persist exactly one Game row and exactly N Participant
    rows, all within a single commit.
    """
    with app.app_context():
        # Clean slate
        db.session.rollback()

        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).delete()
        db.session.query(Player).delete()
        db.session.query(ColorIdentity).delete()
        db.session.commit()

        # Set up FK prerequisites
        ci = ColorIdentity(name='TestCI', amount=1)
        db.session.add(ci)
        for player_data in data['players']:
            db.session.add(Player(id=player_data['id'], name=player_data['name']))
        db.session.flush()
        for deck_data in data['decks']:
            db.session.add(Deck(
                id=deck_data['id'],
                name=deck_data['name'],
                commander=deck_data['commander'],
                player_id=deck_data['player_id'],
                active=deck_data['active'],
                color_identity=deck_data['color_identity'],
            ))
        # Ensure test user exists for audit log FK
        existing_user = db.session.get(User, 99)
        if existing_user is None:
            user = User(id=99, username="testuser", email="test@example.com",
                        player_id=1, active=True, role="admin")
            user.set_password("testpassword")
            db.session.add(user)
        db.session.commit()

        # Mock current_user for audit log
        mock_user = MagicMock()
        mock_user.id = 99
        mock_user.username = "testuser"

        participant_inputs = [
            ParticipantInput(
                player_id=p['player_id'],
                deck_id=p['deck_id'],
                early_sol_ring=p['early_sol_ring'],
                mulligans=p['mulligans'],
            )
            for p in data['participants']
        ]

        num_participants = len(participant_inputs)

        with patch("app.services.audit.current_user", mock_user):
            game = create_game(
                date=data['game_date'],
                first_player_id=data['first_player_id'],
                winner_id=data['winner_id'],
                participants=participant_inputs,
                turns=data['turns'],
                cedh=data['cedh'],
            )

        # Verify exactly 1 Game row was created
        game_count = db.session.query(Game).filter_by(id=game.id).count()
        assert game_count == 1, f"Expected 1 Game row, got {game_count}"

        # Verify exactly N Participant rows were created
        participant_count = db.session.query(Participant).filter_by(game_id=game.id).count()
        assert participant_count == num_participants, (
            f"Expected {num_participants} Participant rows, got {participant_count}"
        )

        # Verify game fields match inputs
        assert game.date == data['game_date']
        assert game.first_player_id == data['first_player_id']
        assert game.winner_id == data['winner_id']
        assert game.turns == data['turns']
        assert game.cedh == data['cedh']

        # Verify participant field values match inputs
        for p_input in data['participants']:
            participant = db.session.query(Participant).filter_by(
                game_id=game.id,
                player_id=p_input['player_id'],
            ).first()
            assert participant is not None, (
                f"Participant with player_id={p_input['player_id']} not found"
            )
            assert participant.deck_id == p_input['deck_id']
            assert participant.early_sol_ring == p_input['early_sol_ring']
            assert participant.mulligans == p_input['mulligans']

        # Cleanup for next hypothesis example
        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).delete()
        db.session.query(Player).delete()
        db.session.query(ColorIdentity).delete()
        db.session.commit()


@given(data=game_creation_data(), fail_at_index=st.integers(min_value=0, max_value=5))
@settings(max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_atomic_game_creation_rollback_on_failure(app, data, fail_at_index):
    """Property 9 (failure path): If any participant insertion fails, no Game or
    Participant rows from that call SHALL remain in the database.

    Simulates a failure during participant insertion by patching the Participant
    constructor to raise after a certain number of successful insertions. Verifies
    that the full rollback leaves no partial Game or Participant rows.
    """
    num_participants = len(data['participants'])
    # Ensure the failure index is within range to actually trigger mid-insertion
    fail_at = fail_at_index % num_participants

    with app.app_context():
        # Clean slate — rollback any pending state first
        db.session.rollback()

        # Set up FK prerequisites
        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).delete()
        db.session.query(Player).delete()
        db.session.query(ColorIdentity).delete()
        db.session.commit()

        ci = ColorIdentity(name='TestCI', amount=1)
        db.session.add(ci)
        for player_data in data['players']:
            db.session.add(Player(id=player_data['id'], name=player_data['name']))
        db.session.flush()
        for deck_data in data['decks']:
            db.session.add(Deck(
                id=deck_data['id'],
                name=deck_data['name'],
                commander=deck_data['commander'],
                player_id=deck_data['player_id'],
                active=deck_data['active'],
                color_identity=deck_data['color_identity'],
            ))
        # Also ensure the test user exists for audit log FK
        existing_user = db.session.get(User, 99)
        if existing_user is None:
            user = User(id=99, username="testuser", email="test@example.com",
                        player_id=1, active=True, role="admin")
            user.set_password("testpassword")
            db.session.add(user)
        db.session.commit()

        # Count rows before the attempted creation
        games_before = db.session.query(Game).count()
        participants_before = db.session.query(Participant).count()

        mock_user = MagicMock()
        mock_user.id = 99
        mock_user.username = "testuser"

        participant_inputs = [
            ParticipantInput(
                player_id=p['player_id'],
                deck_id=p['deck_id'],
                early_sol_ring=p['early_sol_ring'],
                mulligans=p['mulligans'],
            )
            for p in data['participants']
        ]

        # Track how many Participant() calls have been made and raise on the target one
        call_count = {'n': 0}
        original_participant_init = Participant.__init__

        def failing_participant_init(self, *args, **kwargs):
            if call_count['n'] == fail_at:
                call_count['n'] += 1
                raise ValueError("Simulated participant insertion failure")
            call_count['n'] += 1
            original_participant_init(self, *args, **kwargs)

        with patch("app.services.audit.current_user", mock_user):
            with patch.object(Participant, '__init__', failing_participant_init):
                with pytest.raises(ValueError, match="Simulated participant insertion failure"):
                    create_game(
                        date=data['game_date'],
                        first_player_id=data['first_player_id'],
                        winner_id=data['winner_id'],
                        participants=participant_inputs,
                    )

        # After rollback, no new Game or Participant rows should exist
        games_after = db.session.query(Game).count()
        participants_after = db.session.query(Participant).count()

        assert games_after == games_before, (
            f"Game rows changed: before={games_before}, after={games_after}. "
            f"Rollback did not clean up the Game row."
        )
        assert participants_after == participants_before, (
            f"Participant rows changed: before={participants_before}, after={participants_after}. "
            f"Rollback did not clean up Participant rows."
        )

        # Cleanup
        db.session.query(Participant).delete()
        db.session.query(Game).delete()
        db.session.query(Deck).delete()
        db.session.query(Player).delete()
        db.session.query(ColorIdentity).delete()
        db.session.commit()
