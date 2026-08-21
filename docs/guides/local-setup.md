# Local Setup

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ (optional — SQLite works for development)
- Git

## Steps

### 1. Clone the repository

```bash
git clone <repo-url>
cd MagicWebStats
```

### 2. Create a virtual environment

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**Linux/macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements-dev.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:
- `SECRET_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`
- `DATABASE_URL` — PostgreSQL connection string (or leave empty to use SQLite)
- `DB_SCHEMA` — default `magic_stats_owner`

For quick local development with SQLite, set:
```
SQLALCHEMY_DATABASE_URI=sqlite:///dev.db
```

### 5. Set up the database

**Option A: PostgreSQL (recommended for production parity)**

```bash
createdb magicwebstats_dev
psql -d magicwebstats_dev -f scripts/schema.sql
```

**Option B: SQLite (tests use this automatically)**

The test suite uses SQLite in-memory. For manual dev with SQLite, tables are created from the ORM models.

### 6. Run the application

```bash
flask run --debug
```

Or use the Makefile:
```bash
make run
```

The app starts at `http://127.0.0.1:5000`.

### 7. Run tests

```bash
pytest
```

Or:
```bash
make test
```

With coverage:
```bash
make test-cov
```

### 8. Lint

```bash
make lint
```

Fix auto-fixable issues:
```bash
make lint-fix
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | Yes | Flask session signing key |
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string |
| `DB_SCHEMA` | No | Schema name (default: `magic_stats_owner`) |
| `LOCAL_DATABASE_URL` | No | Used by restore scripts for local dev |
| `PERSONAL_STATS_USERNAME` | No | Username for personal stats page |
