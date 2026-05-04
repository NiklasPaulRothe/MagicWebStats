# Feature: game-input-form-redesign
# Property tests for rendered HTML structure of the /game-add form.
#
# These tests use Flask test client with mocked authentication and DB calls
# to avoid PostgreSQL schema dependencies (models use schema='data_owner').

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from bs4 import BeautifulSoup
from datetime import date

from hypothesis import given, settings
from hypothesis import strategies as st


# ---------------------------------------------------------------------------
# Testing config — SQLite in-memory, CSRF disabled
# ---------------------------------------------------------------------------

class TestingConfig:
    TESTING = True
    SECRET_KEY = 'test-secret-key'
    WTF_CSRF_ENABLED = False
    WTF_CSRF_CHECK_DEFAULT = False
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    LOG_TO_STDOUT = False
    SERVER_NAME = 'localhost'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_user(username: str) -> MagicMock:
    """Return a mock Flask-Login user with the given username and admin role."""
    user = MagicMock()
    user.username = username
    user.role = 'admin'
    user.is_authenticated = True
    user.is_active = True
    user.is_anonymous = False
    user.get_id.return_value = '1'
    return user


def _get_game_add_html(app, username: str, game_condition_suggestions=None) -> str:
    """
    Perform a GET /game-add as *username* and return the response HTML.

    All DB-touching helpers in the route are patched to return empty/safe data
    so the test never needs a real database.
    """
    if game_condition_suggestions is None:
        game_condition_suggestions = []

    mock_user = _make_mock_user(username)

    with app.test_client() as client:
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('app.stats.routes.get_player', return_value=['Alice', 'Bob', 'Charlie']), \
             patch('app.stats.routes.get_decks', return_value=[]), \
             patch('app.stats.routes.db') as mock_db:

            # Mock the union query that builds game_condition_suggestions
            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.union.return_value = mock_query
            mock_query.all.return_value = [(v,) for v in game_condition_suggestions]
            mock_db.session.query.return_value = mock_query

            response = client.get('/game-add')
            assert response.status_code == 200, (
                f"Expected 200 but got {response.status_code}. "
                f"Body: {response.data[:500]}"
            )
            return response.data.decode('utf-8')


def _post_game_add_html(app, form_data: dict, username: str = 'Niklas') -> str:
    """
    POST to /game-add with *form_data* and return the re-rendered HTML.
    Expects a 200 (validation failure re-render), not a redirect.
    """
    mock_user = _make_mock_user(username)

    with app.test_client() as client:
        with patch('flask_login.utils._get_user', return_value=mock_user), \
             patch('app.stats.routes.get_player', return_value=['Alice', 'Bob', 'Charlie']), \
             patch('app.stats.routes.get_decks', return_value=[]), \
             patch('app.stats.routes.db') as mock_db:

            mock_query = MagicMock()
            mock_query.filter.return_value = mock_query
            mock_query.union.return_value = mock_query
            mock_query.all.return_value = []
            mock_db.session.query.return_value = mock_query

            response = client.post('/game-add', data=form_data,
                                   follow_redirects=False)
            # A validation failure re-renders the form (200); a success redirects (302)
            assert response.status_code == 200, (
                f"Expected 200 (validation failure) but got {response.status_code}. "
                "The form may have validated successfully — check form_data."
            )
            return response.data.decode('utf-8')


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope='module')
def app():
    from app import create_app
    application = create_app(TestingConfig)
    yield application


# ---------------------------------------------------------------------------
# 10.1  Property 1: All required fields have hint text
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

HINT_FIELDS = [
    'mulligan',
    'landdrops',
    'lands',
    'final_blow',
    'first_ko_by',
    'early_fast_mana',
]


@pytest.mark.parametrize('field_name', HINT_FIELDS)
def test_required_fields_have_hints(app, field_name):
    """
    Property 1: All required fields have hint text.
    For each field in the required set, a .field-hint element must be present
    adjacent to its input in the rendered HTML.
    Validates: Requirements 4.1
    """
    html = _get_game_add_html(app, username='Niklas')
    soup = BeautifulSoup(html, 'html.parser')

    # Find the input/select/textarea whose id contains the field name
    input_el = (
        soup.find(id=lambda i: i and field_name in i)
        or soup.find('input', attrs={'name': lambda n: n and field_name in n})
    )
    assert input_el is not None, (
        f"Could not find an input element for field '{field_name}' in rendered HTML"
    )

    # Walk up to the nearest .form-field ancestor
    parent = input_el.find_parent(class_='form-field')
    assert parent is not None, (
        f"Field '{field_name}' is not inside a .form-field wrapper"
    )

    hint = parent.find(class_='field-hint')
    assert hint is not None, (
        f"No .field-hint element found adjacent to field '{field_name}'"
    )
    assert hint.get_text(strip=True) != '', (
        f".field-hint for '{field_name}' is empty"
    )


# ---------------------------------------------------------------------------
# 10.2  Property 2: All boolean flags are grouped in the checklist container
# Validates: Requirements 5.1
# ---------------------------------------------------------------------------

BOOLEAN_FLAG_FIELDS = [
    'enough_mana',
    'enough_gas',
    'deckplan',
    'unanswered_threats',
    'loss_without_answer',
    'selfmade_win',
    'fun_moments',
]


@pytest.mark.parametrize('field_name', BOOLEAN_FLAG_FIELDS)
def test_boolean_flags_in_checklist(app, field_name):
    """
    Property 2: All boolean flags are grouped in the checklist container.
    For each boolean flag field, the input must be a descendant of .checklist-grid.
    Validates: Requirements 5.1
    """
    html = _get_game_add_html(app, username='Niklas')
    soup = BeautifulSoup(html, 'html.parser')

    # Find the checkbox input for this field
    input_el = (
        soup.find('input', id=lambda i: i and field_name in i)
        or soup.find('input', attrs={'name': lambda n: n and field_name in n})
    )
    assert input_el is not None, (
        f"Could not find checkbox input for field '{field_name}'"
    )

    # Assert it is a descendant of .checklist-grid
    checklist_ancestor = input_el.find_parent(class_='checklist-grid')
    assert checklist_ancestor is not None, (
        f"Field '{field_name}' is not a descendant of .checklist-grid"
    )


# ---------------------------------------------------------------------------
# 10.3  Property 6: Every input element has an associated label
# Validates: Requirements 8.1
# ---------------------------------------------------------------------------

def test_all_inputs_have_labels(app):
    """
    Property 6: Every input element has an associated label.
    For every <input>, <select>, and <textarea>, either a <label for="..."> with
    matching id exists, or the element is wrapped in a <label>.
    Validates: Requirements 8.1
    """
    html = _get_game_add_html(app, username='Niklas')
    soup = BeautifulSoup(html, 'html.parser')

    # Collect all label[for] targets
    label_for_ids = {
        label['for']
        for label in soup.find_all('label', attrs={'for': True})
    }

    # Hidden inputs and submit buttons don't need labels
    SKIP_TYPES = {'hidden', 'submit', 'button'}

    missing = []
    for tag_name in ('input', 'select', 'textarea'):
        for el in soup.find_all(tag_name):
            el_type = el.get('type', '').lower()
            if el_type in SKIP_TYPES:
                continue

            el_id = el.get('id', '')
            # Check: has a matching label[for], OR is wrapped in a <label>
            has_label_for = el_id and el_id in label_for_ids
            has_wrapping_label = el.find_parent('label') is not None

            if not has_label_for and not has_wrapping_label:
                missing.append(
                    f"<{tag_name} id='{el_id}' name='{el.get('name', '')}' "
                    f"type='{el_type}'>"
                )

    assert not missing, (
        f"The following inputs have no associated label:\n"
        + '\n'.join(f'  {m}' for m in missing)
    )


# ---------------------------------------------------------------------------
# 10.4  Property 7: Deck Tracking Section absent for non-Niklas users
# Validates: Requirements 10.3
# ---------------------------------------------------------------------------

DECK_TRACKING_FIELD_IDS = [
    'mulligan', 'landdrops', 'lands', 'comment',
    'enough_mana', 'enough_gas', 'deckplan',
    'unanswered_threats', 'loss_without_answer',
    'selfmade_win', 'fun_moments',
]


@given(
    st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll')),
    ).filter(lambda x: x != 'Niklas')
)
@settings(max_examples=20)
def test_deck_tracking_absent_for_non_niklas(username):
    """
    Property 7: Deck Tracking Section is absent for non-Niklas users.
    For any authenticated username that is not 'Niklas', the rendered form
    HTML must not contain #section-my-game or any deck tracking field ids.
    Validates: Requirements 10.3
    """
    # We need the app inside the test body because Hypothesis calls this
    # function directly (not as a pytest fixture-injected test).
    from app import create_app
    application = create_app(TestingConfig)

    html = _get_game_add_html(application, username=username)
    soup = BeautifulSoup(html, 'html.parser')

    # #section-my-game must be absent
    my_game_section = soup.find(id='section-my-game')
    assert my_game_section is None, (
        f"#section-my-game was found in the HTML for user '{username}'"
    )

    # None of the deck tracking field ids should appear
    for field_name in DECK_TRACKING_FIELD_IDS:
        el = (
            soup.find(id=lambda i: i and field_name in i)
            or soup.find(attrs={'name': lambda n: n and field_name in n})
        )
        assert el is None, (
            f"Deck tracking field '{field_name}' was found in the HTML "
            f"for non-Niklas user '{username}'"
        )


# ---------------------------------------------------------------------------
# 10.5  Property 9: Shared autocomplete datalist
# Validates: Requirements 11.2, 11.3
# ---------------------------------------------------------------------------

def test_shared_autocomplete_datalist(app):
    """
    Property 9: Shared autocomplete datalist contains union of all distinct DB values.
    The rendered form must contain exactly one <datalist id="game-condition-list">.
    Both final_blow and first_ko_by inputs must reference it via list attribute.
    Validates: Requirements 11.2, 11.3
    """
    suggestions = ['Thassa's Oracle', 'Thoracle Combo', 'Combat Damage']
    html = _get_game_add_html(app, username='Niklas',
                              game_condition_suggestions=suggestions)
    soup = BeautifulSoup(html, 'html.parser')

    # Exactly one datalist with id="game-condition-list"
    datalists = soup.find_all('datalist', id='game-condition-list')
    assert len(datalists) == 1, (
        f"Expected exactly 1 <datalist id='game-condition-list'>, "
        f"found {len(datalists)}"
    )

    # Both final_blow and first_ko_by inputs reference the datalist
    for field_name in ('final_blow', 'first_ko_by'):
        input_el = soup.find(
            lambda tag: tag.name in ('input', 'textarea')
            and tag.get('id', '').endswith(field_name)
        )
        if input_el is None:
            # Fall back to name-based search
            input_el = soup.find(
                attrs={'name': lambda n: n and n.endswith(field_name)}
            )
        assert input_el is not None, (
            f"Could not find input for field '{field_name}'"
        )
        assert input_el.get('list') == 'game-condition-list', (
            f"Input for '{field_name}' does not reference 'game-condition-list' "
            f"via list attribute (got: {input_el.get('list')!r})"
        )


# ---------------------------------------------------------------------------
# 10.3 (date)  Property 3: Date preserved after validation failure
# Validates: Requirements 6.2
# ---------------------------------------------------------------------------

@given(st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 31)))
@settings(max_examples=20)
def test_date_preserved_on_validation_error(valid_date):
    """
    Property 3: User-entered date is preserved after validation failure.
    When the form is submitted with a valid date but a missing required field
    (winner), the re-rendered HTML must contain the same date value.
    Validates: Requirements 6.2
    """
    from app import create_app
    application = create_app(TestingConfig)

    date_str = valid_date.strftime('%Y-%m-%d')

    # Submit with a valid date but omit 'winner' to trigger a validation error.
    # We also need the minimum player sub-form fields to avoid unrelated errors.
    form_data = {
        'date': date_str,
        # winner intentionally omitted to cause validation failure
        'first': 'Alice',
        # Provide the minimum 3 player entries (WTForms FieldList min_entries=3)
        'players-0-player': 'Alice',
        'players-0-deck': '',
        'players-1-player': 'Bob',
        'players-1-deck': '',
        'players-2-player': 'Charlie',
        'players-2-deck': '',
    }

    html = _post_game_add_html(application, form_data, username='Niklas')
    soup = BeautifulSoup(html, 'html.parser')

    date_input = soup.find('input', id='date-field')
    assert date_input is not None, (
        "Could not find <input id='date-field'> in re-rendered HTML"
    )
    assert date_input.get('value') == date_str, (
        f"Date input value '{date_input.get('value')}' does not match "
        f"submitted date '{date_str}'"
    )
