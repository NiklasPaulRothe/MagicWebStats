# MagicWebStats

MagicWebStats tracks Commander (EDH) game statistics — player performance, deck stats, color identity analysis, and Elo ratings.

## Documentation

- [Architecture](architecture.md) — Blueprint layout, request flow, design patterns
- [Models](models.md) — Database tables and views
- [API](api.md) — JSON API endpoint reference
- [Local Setup](guides/local-setup.md) — Getting the project running locally
- [Database](guides/database.md) — Schema management, backups, views

## Decisions

- [ADR-001: No Alembic](decisions/adr-001-no-alembic.md) — Manual schema management
- [ADR-002: Flat API Responses](decisions/adr-002-flat-api-responses.md) — snake_case flat JSON

## Project Structure

```
app/                    Flask application
├── api/                JSON API (queries, formatters, routes, errors)
├── auth/               Authentication blueprint
├── cards/              Card browser blueprint
├── decks/              Deck management blueprint
├── main/               Landing pages
├── stats/              Stats display blueprint
├── third_party_data/   External data integration
├── services/           Service layer (audit, stats, color, elo, deck, game)
├── models.py           SQLAlchemy 2.0 ORM models
└── viewmodels.py       Read-only database views

scripts/                Database schema, data scripts, backup/restore
tests/                  pytest + Hypothesis property tests
config.py               Config (production) and TestingConfig classes
```

## Tech Stack

- **Backend:** Flask, SQLAlchemy 2.0, Flask-Login, Flask-WTF (CSRF)
- **Database:** PostgreSQL (production), SQLite (tests)
- **Testing:** pytest, Hypothesis (property-based tests)
- **Deployment:** Gunicorn via Procfile
