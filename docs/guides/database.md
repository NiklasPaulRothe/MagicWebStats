# Database Management

## Schema Source of Truth

The database schema is managed in a single file:

```
scripts/schema.sql
```

This file contains all `CREATE TABLE`, `CREATE VIEW`, constraint definitions, and indexes. It is the authoritative source of database structure.

## Making Schema Changes

1. Edit `scripts/schema.sql` directly
2. Review the change (all statements should be idempotent where possible — use `IF NOT EXISTS`)
3. Apply to your local database:
   ```bash
   psql -d magicwebstats_dev -f scripts/schema.sql
   ```
4. Update `app/models.py` to reflect the new schema
5. Commit both files together

There is no Alembic or Flask-Migrate. See [ADR-001](../decisions/adr-001-no-alembic.md) for reasoning.

## Views

Two database views are defined in `schema.sql` and mapped as read-only models in `app/viewmodels.py`:

- **`v_color_usage`** — color usage statistics across all active decks (likelihood, average, deck_percentage)
- **`v_color_usage_player`** — per-player color breakdown (white, blue, black, red, green percentages)

These views are recreated via `CREATE OR REPLACE VIEW` in `schema.sql`.

## Backup & Restore

### Full backup

```bash
python scripts/backup_full_database.py
```

Creates a timestamped dump file using `pg_dump`.

### Restore

```bash
python scripts/restore_full_database.py
```

Restores from a backup to the `LOCAL_DATABASE_URL` target (never directly to production `DATABASE_URL`).

## Test Database

Tests use SQLite in-memory (`TestingConfig`):

```python
SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
```

Tables are created from ORM model metadata at the start of each test session. No schema.sql is executed for tests.

## Production Database

- PostgreSQL with a dedicated schema (configurable via `DB_SCHEMA`)
- Connection pooling: `pool_size=5`, `pool_recycle=300`, `pool_pre_ping=True`
- Deployed behind Gunicorn (`Procfile: web: gunicorn webstats:app`)
