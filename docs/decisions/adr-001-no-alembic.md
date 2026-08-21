# ADR-001: Manual Schema Management via schema.sql

## Status

Accepted

## Context

Alembic (Flask-Migrate) was previously used for database migrations. It introduced complexity:

- Migration files accumulated and became hard to reason about
- The "current state" of the schema required reading through the full migration chain
- Merge conflicts in migration files were common and painful
- For a single-database project with one developer, the overhead wasn't justified

The project uses a single always-current build script approach: `scripts/schema.sql` represents the complete desired state of the database at any point in time.

## Decision

All schema changes go directly into `scripts/schema.sql`. This file is the single source of truth for database structure. Alembic and Flask-Migrate have been removed from the project.

## Consequences

### Positive

- Schema is always readable in one file
- No migration tracking tables or state
- No merge conflicts on migration files
- Simpler dependency tree (no Alembic)
- `schema.sql` can be run against a fresh database to set up everything

### Negative

- Requires manual discipline — no auto-generation of migration steps
- Destructive changes (column drops, renames) must be applied manually with care
- No automatic rollback mechanism
- Team scaling would require coordination around schema changes

### Mitigations

- All schema changes are reviewed in pull requests
- `scripts/backup_full_database.py` provides point-in-time recovery
- The project has a single maintainer, reducing coordination overhead
