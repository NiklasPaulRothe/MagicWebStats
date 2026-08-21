# Architecture

## Blueprint Layout

| Blueprint | URL Prefix | Responsibility |
|-----------|-----------|----------------|
| `main` | `/` | Landing pages, dashboard |
| `auth` | `/auth` | Login, logout, user management |
| `stats` | `/` | Stats display pages |
| `api` | `/api` | JSON API for frontend consumption |
| `decks` | `/decks` | Deck CRUD, versioning, archiving |
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
- `stats_service.py` — Complex stat aggregations

### Role-Based Access

Admin endpoints use the `@role_required('admin')` decorator stacked with `@login_required`. All API endpoints require authentication.

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
