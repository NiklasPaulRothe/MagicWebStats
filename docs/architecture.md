# Architecture

## Blueprint Layout

| Blueprint | URL Prefix | Responsibility |
|-----------|-----------|----------------|
| `main` | `/` | Landing pages, dashboard |
| `auth` | `/auth` | Login, logout, user management |
| `stats` | `/` | Stats display pages |
| `api` | `/api` | JSON API for frontend consumption |
| `decks` | `/decks` | Deck CRUD, versioning, archiving, My Decks folders |
| `collection` | `/` | Collection page: import, add card, remove, card popup |
| `cards` | `/` | Card browser and detail pages |
| `third_party_data` | `/` | External data integration (Scryfall, etc.) |
| `errors` | — | Error handlers (404, 500) |

## Request Flow

```
Route Handler → Service Layer → ORM Model/Query → Database
      ↓
  Formatter → JSON Response
```

1. **Route** (`app/api/routes.py`) — receives request, validates auth
2. **Query** (`app/api/queries.py`) — encapsulates all database logic, returns TypedDicts
3. **Formatter** (`app/api/formatters.py`) — transforms query results into API response shape
4. **Service** (`app/services/`) — domain logic that spans multiple models (Elo calculation, audit logging, color resolution)

## Key Design Patterns

### Query/Formatter Separation

API queries live in `app/api/queries.py` with typed results (`TypedDict`). Formatters in `app/api/formatters.py` handle the JSON shape. This keeps database logic isolated from presentation.

```python
# queries.py — returns typed data
def get_player_stats(session: Session) -> list[PlayerStatsResult]: ...

# formatters.py — shapes for API response
def format_player_stats(result: PlayerStatsResult) -> dict: ...

# routes.py — glues them together
results = queries.get_player_stats(db.session)
return jsonify([format_player_stats(r) for r in results])
```

### Service Layer

Services in `app/services/` encapsulate cross-cutting logic:

- `audit.py` — `write_audit_log()` for all state-changing operations
- `color_service.py` — `resolve_color_images()` for color identity → image URL mapping
- `elo_service.py` — Elo rating calculations
- `deck_service.py` — Deck versioning logic
- `game_service.py` — Game creation and participant handling
- `stats_service.py` — Complex stat aggregations, incl. `compute_playgroup_dashboard()` (playgroup-wide, non-cEDH aggregates for the Playgroup page: every game metric filters `games.cedh = false`, active decks exclude cEDH decks)
- `collection_service.py` — Collection import (standard/Archidekt + ManaBox formats, replace/add modes), single-card add, remove, availability statuses

### Role-Based Access

Users have one of three role tiers (`app/auth/__init__.py`), compared by
level so a higher tier inherits everything below it:

| Role | Level | Can additionally… |
|------|-------|-------------------|
| `user` | 0 | use the site (stats, own decks, own collection) |
| `maintainer` | 10 | add/edit/delete games, add players and decks, quick-add, load decks, reactivate anyone's archived deck, see private deck averages |
| `admin` | 20 | audit log, Elo recalculation, role management (`/auth/manage/roles`) |

Gate routes with `@min_role_required(ROLE_MAINTAINER)` / `@min_role_required(ROLE_ADMIN)`
stacked with `@login_required`; in code use `has_min_role()`, `is_maintainer()`
and `is_admin()` (the last two are also injected into every template by a
context processor to show/hide the MANAGE and ADMIN nav groups).
`role_required(*roles)` is a legacy exact-match gate kept for compatibility —
prefer the level-based helpers. An unknown role string resolves to level -1
and is denied everywhere (fail-closed); production additionally enforces the
allowed set with the `ck_users_role` CHECK constraint. All API endpoints
require authentication.

## Frontend Structure

The UI uses one app shell (`app/templates/base.html`): a dark/gold sidebar
(collapsible on desktop, off-canvas drawer below 1024px, `static/js/sidebar.js`)
with nav groups MAIN (Playgroup, Players, Colors, Decks), YOURS (Profile,
My Deck Stats, My Decks, Collection), MANAGE (maintainer+) and ADMIN (admin).

**Stylesheets** (load order in `base.html`):

| File | Role |
|------|------|
| `css/theme.css` | Design tokens only (colors, type scale, spacing, radii, shadows, layout sizes). Reference these custom properties instead of hard-coding values. |
| `css/layout.css` | Shell layout: sidebar, top bar, content area, flash messages, `.sr-only`. |
| `css/basic.css` | Legacy global element styles (buttons, forms, tables, links). Page CSS often overrides them explicitly. |
| page CSS | Loaded via `{% block head %}`. |

**Content width.** `.app-main__inner` caps content at `--content-max` (1200px).
Pages can opt out via `{% block main_inner_class %}`:
`app-main__inner--wide` (1760px, e.g. My Deck Stats) or `app-main__inner--full`
(no cap, e.g. Collection).

**Page → assets:**

| Page | Template | CSS | JS |
|------|----------|-----|----|
| Playgroup dashboard | `index.html` | `dashboard.css` | — |
| Players / Colors | `stats/playerstats.html`, `stats/colorstats.html` | `playertable.css` | inline |
| Decks table | `stats/deckstats.html` | `playertable.css`, `deckstats.css` | `deckstats.js` |
| Deck detail | `decks/show.html` | `playertable.css`, `deckdetail.css` | `deckdetail.js` |
| My Deck Stats | `decks.html` (route `main.user`) | `playertable.css`, `mydeckstats.css` | `mydeckstats.js` |
| My Decks (folders) | `decks/my_decks.html` | `my_decks.css` | `deck_folders.js` |
| Collection | `collection/collection.html` | `collection.css`, `autocomplete.css` | inline, `collection_modal.js`, `collection_add.js`, `autocomplete.js` |
| Role management | `auth/manage_roles.html` | — | — |

`playertable.css` holds the shared data-page pieces (`.panel`, `.dash-head`,
`.seg` segmented control, `.ptable` tables, `.ptable-pager`, `.btn--ghost`).

**Conventions used across the redesigned pages**

- *Neutral data.* Stats pages present plain numbers — no rankings, top lists
  or good/bad colouring (the group is a social playgroup, not a ladder).
- *Empty values sort last* in every sortable table/grid, regardless of direction.
- *Client-side paging* after sort/filter over the full dataset (Decks table
  25/50/100, deck game history 10, Collection 50/100/150).
- *JSON + CSRF.* Interactive POSTs send JSON with the `X-CSRFToken` header;
  see the page-level endpoints in [API](api.md).
- *Global-style overrides.* `basic.css` styles every `button`, `form`, `form
  label` and `.app-main a:link`; new components set their button properties
  explicitly, and link-buttons (`.btn`, `.dd-btn`) are excluded from the global
  link colour.

**Shared JS components**

- `autocomplete.js` — `initAutocomplete(input, {apiUrl, minChars, debounceMs, onSelect})`
  for card-name inputs (backed by `/api/cards/autocomplete`). `onSelect(name)`
  fires after a suggestion is picked.

## Database

- **Production:** PostgreSQL with a configurable schema (`DB_SCHEMA` env var, default `magic_stats_owner`)
- **Tests:** SQLite in-memory via `TestingConfig`
- **Schema management:** Single `scripts/schema.sql` file (see [ADR-001](decisions/adr-001-no-alembic.md))
- **No Alembic** — schema changes are applied manually

## Extensions

| Extension | Purpose |
|-----------|---------|
| Flask-SQLAlchemy | ORM integration |
| Flask-Login | Session-based authentication |
| Flask-WTF / CSRFProtect | CSRF protection for all POST endpoints |
| Flask-Limiter | Rate limiting |
