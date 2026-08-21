# MagicWebStats — Refactoring & Test Suite Plan

## Overview

This plan outlines a phased approach to streamline the codebase, eliminate technical debt, and establish a comprehensive test suite. Each phase builds on the previous one, so order matters.

---

## Phase 1: Service Layer Extraction

**Goal:** Separate business logic from route handlers into testable, reusable service modules.

### Tasks

- [ ] Create `app/services/` package
- [ ] Extract `audit.py` — single `write_audit_log()` function replacing the 3 duplicated `_audit()` helpers
- [ ] Extract `stats_service.py` — participant averages, deck performance, turn/win statistics
  - **While extracting, fix the N+1 queries, don't just relocate them:** `get_player()`, `get_decks()`, and `get_ci()` in `app/stats/routes.py` each run a per-row query in a loop; `get_ci()` is doubly nested (color identity → color component per identity). Rewrite as single queries with joins/`selectinload` before moving into the service.
- [ ] Extract `elo_service.py` — Elo rating calculation logic (currently in `decks/routes.py`)
- [ ] Extract `color_service.py` — color identity image resolution (duplicated 4-5 times)
- [ ] Extract `deck_service.py` — deck versioning, archiving, card loading orchestration
- [ ] Extract `game_service.py` — game creation, participant handling, game deletion
  - **Fix commit-per-participant bug:** `game_add` currently calls `db.session.commit()` once per participant inside the loop instead of once per game. Batch all participant inserts and commit once (or wrap in a single transaction) when moved into the service.
- [ ] Rewrite `app/cards/routes.py` `card_meta()` to use a grouped SQL query instead of the current O(n×m) nested Python loop over all `DeckComponent` rows
- [ ] Update all route handlers to call service functions instead of inlining logic

### Success Criteria

- Route handlers are thin (< 30 lines) — validate input, call service, return response
- No business logic in route files
- All service functions have docstrings and type hints
- No per-row query loops (N+1) remain in extracted service functions

---

## Phase 2: Security Fixes

**Goal:** Close security holes and remove hardcoded identity checks.

### Tasks

- [ ] **Wire up CSRF protection.** No `CSRFProtect(app)` call exists anywhere in `app/__init__.py`. `Flask-WTF` is installed and forms likely render `{{ form.csrf_token }}`, but without `CSRFProtect` initialized, that token isn't being validated on submit. This is a one-line fix (`CSRFProtect().init_app(app)`) and should land before the broader CSRF audit below.
- [ ] Add CSRF tokens to the AJAX calls in `/api/quick-add-player` and `/api/quick-add-deck` (and any other JS-driven POSTs) once CSRF protection is enabled — currently sent with no token header
- [ ] Remove broken `identity_loaded` handler in `webstats.py` that grants admin/maintainer to all users (this is also where `Flask-Principal` gets removed — see Phase 8's dependency cleanup task for the full removal checklist, done together with this fix rather than as a separate pass)
- [ ] Replace all `if current_user.id != 1` / `if player == 1` with proper role checks
- [ ] Replace `if current_user.username == 'Niklas'` with a feature flag or role-based check
- [ ] Remove hardcoded fallback secret key in `config.py` — fail fast if `SECRET_KEY` is unset
- [ ] Audit all remaining POST endpoints for CSRF protection (after `CSRFProtect` is wired up)
- [ ] Replace `deck.Player != 24` magic number with a named constant or config value
- [ ] Add rate limiting to `/auth/login` (e.g. `Flask-Limiter`) — currently unthrottled and open to brute-force
- [ ] Add a `/healthz` endpoint for deployment health checks (relevant given the Procfile/gunicorn setup in Phase 10)

### Success Criteria

- No hardcoded user IDs or usernames in application logic
- App refuses to start without a proper secret key
- Role-based access control works as intended
- CSRF protection is actually enforced (verified with a test that a POST without a valid token is rejected)
- Login endpoint is rate-limited

---

## Phase 3: Model & ORM Cleanup

**Goal:** Consistent model definitions with proper relationships to simplify query logic.

### Tasks

- [ ] Migrate all models to modern SQLAlchemy 2.0 `Mapped[]` style (match the `User` model pattern)
- [ ] Normalize column naming to snake_case (built directly into `scripts/schema.sql`, not Alembic — see below)
- [ ] Add `relationship()` declarations:
  - `Deck.player` ↔ `Player.decks`
  - `Game.participants` ↔ `Participant.game`
  - `Participant.deck` ↔ `Deck.participations`
  - `Participant.player` ↔ `Player.participations`
  - `Deck.version_history` ↔ `DeckVersionHistory.deck`
  - `Deck.achievements` ↔ `Achievement.deck_ref`
  - `Deck.tags` ↔ `DeckTag.deck_ref`
- [ ] Decide on English-only column names (rename `spieler`, `titel`, `beschreibung`, `anzahl`)
- [x] Remove unused models entirely rather than just their dead imports: `Role` and `UserRoles` (in `app/models.py`) were never queried anywhere in the codebase — `role_required` checks the plain `User.role` string column instead. Both model classes and the `flask_security.RoleMixin` import (in both `app/models.py` and `viewmodels.py`) have been deleted. Treat this as a standing rule for the rest of Phase 3/5: if a model class has no query, no relationship reference, and no route/template usage anywhere in `app/`, delete the class rather than migrating its table.
- [ ] **Enumerate the complete live schema before writing the full-build script.** Two specs landed new tables/columns after this plan was first drafted: `card-data-restructure` replaced `card_data` with `cards`/`card_faces`/`card_colors`/`card_color_identity`/`card_keywords`/`card_legalities`/`oracle_tags`. Run `\dt data_owner.*` (or query `information_schema.tables`) against the actual database and diff it against `app/models.py` before drafting the schema script below, so nothing merged out-of-band is missed.
- [ ] Add missing foreign keys: `Game.Winner` and `Game.First_Player` are plain `Integer` columns with no FK to `Player.id`; `Achievement.deck` is a raw int with no FK to `Decks.id`
- [ ] Add a FK for `Game.added_by` — note it references `User.id`, not `Player.id` (confirmed via `_assert_game_owner()`'s comparison against `current_user.id`), which is a different entity than `Winner`/`First_Player`. Rename or document clearly so "references User" vs "references Player" isn't ambiguous from the column name alone.
- [ ] Add DB-level `unique` constraints on `Player.Name` and `Deck.Name` — the app assumes uniqueness (e.g. `/api/quick-add-player`, `/api/quick-add-deck` do a check-then-insert) but nothing enforces it at the DB level, so concurrent requests can create duplicates
- [ ] Add indexes on `Participant.player_id` and `Participant.deck_id` individually (currently only covered by the composite PK with `game_id`), since both columns are queried independently and frequently in stats/decks routes
- [ ] Decide and apply explicit `ondelete` policy on FKs that currently have none: `DeckComponent.deck_id`, `DeckTag.deck_id`, `DeckVersionHistory.deck_id`, `Achievement.deck` → `CASCADE` (meaningless without the parent deck); `Participant.deck_id`/`game_id`/`player_id` → `RESTRICT` (don't want game/deck/player deletion to silently wipe participation history). Without this, deleting a `Deck` or `Game` today either hits a FK violation or orphans rows depending on how the constraint resolved at creation time.
- [ ] Add `CHECK` constraints for values that are only ever valid in a range: `Deck.elo_rating >= 0`, `Participant.mulligans >= 0`, `Game.turns >= 0`, `Deck.Version`/`patch`/`change >= 0`
- [ ] Add `created_at`/`updated_at` timestamp columns to `Deck`, `Game`, `Participant`, and `Player` — currently only `AuditLog` and `DeckVersionHistory` capture *when* something changed, and only for changes that go through those code paths. Direct SQL, migrations, or bugs leave no trace otherwise.
- [ ] Standardize string column lengths while renaming columns to snake_case — `User.username` is `String(64)` but most other string columns (`Deck.Name`, `Player.Name`, `Card.name`, etc.) are unbounded `db.String`
- [ ] Document the deck versioning scheme (`Version`/`patch`/`change` counters plus `Last_Rework`/`Last_Change`/`last_patch` dates) — what qualifies as a "rework" vs "patch" vs "change" is not evident from the schema and should be captured in `docs/models.md` (Phase 11), not left as tribal knowledge
- [ ] Flag `Card.oracle_tags` as a query-in-a-property, not a mapped relationship: it runs a fresh query on every access rather than participating in eager-loading. This is intentional (an `oracle_id` isn't unique per `Card`, since multiple printings share one, so a normal FK relationship doesn't fit), but the resulting N+1 risk if it's accessed in a loop over multiple cards should be documented next to `card_meta()`'s fix in Phase 5.
- [ ] Add a `seat` column to `Participant` (nullable integer). See "Seat Column" subsection below for constraint design.
- [ ] Stop hardcoding the schema name (`'data_owner'` today, `magic_stats_owner` after the migration) separately in every model's `__table_args__` and in every raw SQL string. Add a `DB_SCHEMA` value to `config.py` and reference it via a single constant (e.g. a shared `SCHEMA = current_app.config['DB_SCHEMA']` used in `__table_args__`, or a module-level constant imported everywhere raw SQL is built). This is what actually causes the "update everything to point at the new owner" problem below — fixing it now means the *next* schema/owner change is a one-line config edit instead of a repo-wide sweep.
- [ ] Delete `scripts/skill_calculator.py` — it queries `data_owner.skill_level`, a table that has no corresponding model in `app/models.py` and is no longer needed. Remove it before the cutover so it isn't carried forward or mistaken for something that needs migrating.
- [ ] **Remove Alembic/Flask-Migrate entirely.** Database administration and schema changes are handled manually via `scripts/schema.sql` (see below) — there's no need for a second, parallel migration-tracking system. Remove `alembic` and `Flask-Migrate` from `requirements.txt`, remove `migrate = Migrate()` / `migrate.init_app(app, db)` from `app/__init__.py`. The old `migrations/` directory and its one-off incremental `.sql` files (`card_data_restructure.sql`, `card_data_restructure_phase2.sql`, `deck_primer_generator.sql`) have already been deleted — their contents were folded into the initial draft of `scripts/schema.sql` instead of being relocated as-is, since the new approach is a single always-current build script, not a stack of dated files.

### Schema & Ownership Migration: `data_owner` → `magic_stats_owner`

**Goal:** Rather than incrementally `ALTER`-ing the existing `data_owner` schema in place, build the entire cleaned-up schema fresh under a new database role/schema (`magic_stats_owner`), then migrate all data across. The old `data_owner` schema is left untouched as a rollback safety net until the new schema is verified in production, then dropped.

This is a deliberate change from a pure in-place rename strategy to a **parallel-schema cutover**:
- All of Phase 3's structural decisions (snake_case naming, English column names, proper FKs, `ondelete` policies, `CHECK` constraints, `created_at`/`updated_at`, unique constraints, indexes, the new `seat` column) get built directly into the new schema's `CREATE TABLE` statements — there's no need to layer incremental `ALTER` scripts on top of the old structure.
- The old schema keeps working undisturbed while the new one is built and validated, so there's a clean, low-risk rollback path (just don't cut the app over) if something doesn't match.
- The application only needs to change which schema it points at once the new one is verified — see the `DB_SCHEMA` config task above.
- **The app's DB connection user changes to `magic_stats_owner`.** This isn't only a schema/table rename — the application should connect and operate as the `magic_stats_owner` role going forward, not as whatever role it uses today against `data_owner`. That means `DATABASE_URL` (in `.env` locally and in the Heroku/production config vars) needs its credentials updated as part of the cutover, not just the code's `DB_SCHEMA` value. Until the old schema is dropped, the `magic_stats_owner` role needs at least read access to `data_owner` (for the data-copy step) — grant that explicitly rather than relying on a shared superuser during migration.
- **No concurrent schema changes during the migration window.** The project owner has committed to freezing `data_owner` schema changes (no new tables/columns landing from other specs) for the duration of Phase 3's build-and-verify work, so the enumeration step above only needs to happen once, not repeatedly re-checked against a moving target.

#### Migration strategy: one always-current full-build script, not versioned migration files

Unlike the earlier, now-deleted incremental migration files (`migrations/card_data_restructure.sql`, `migrations/card_data_restructure_phase2.sql`, `migrations/deck_primer_generator.sql`), schema management going forward uses a **single script that is always a complete, fresh build of the database**:

- **`scripts/schema.sql`** — the single source of truth. Running it against an empty Postgres instance creates the `magic_stats_owner` role, schema, every table, constraint, index, and trigger the application needs, in its current, final form.
- When the schema needs to change, **this file is edited in place** to keep describing the desired end state — it is not a growing stack of dated `ALTER` files. There is no `001_/002_/003_` numbered-folder convention and no separate "migrations" directory; `scripts/schema.sql` is it.
- The script is idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE` guards throughout), so re-running it against an already-built database is always safe and produces no errors or data loss.
- **The one-time data copy from `data_owner` to `magic_stats_owner`, and the eventual drop of `data_owner`, are not part of `scripts/schema.sql`.** Those are non-repeatable, one-off operational steps (they only make sense to run once, against real production data) and live in separate scripts (e.g. `scripts/migrate_data_owner_to_magic_stats_owner.sql`, run by hand during the actual cutover) rather than in the file that represents "build the schema from scratch."
- A first draft of `scripts/schema.sql` has been written, covering every table currently in `data_owner` (including the `cards`/`card_faces`/`card_colors`/`card_color_identity`/`card_keywords`/`card_legalities`/`oracle_tags` tables added by `card-data-restructure`) with Phase 3's naming, FK, `ondelete`, `CHECK`, and `created_at`/`updated_at` decisions applied. It still needs the `v_color_usage`/`v_color_usage_player` view definitions pulled from the live database (see the `TODO` left in the file) before it's complete.

#### Required pattern for data migration (one-off, not part of `scripts/schema.sql`)

```sql
-- Preserve old primary key values so FK references still line up across the copy
INSERT INTO magic_stats_owner.players (id, name)
SELECT id, "Name" FROM data_owner."Player";

INSERT INTO magic_stats_owner.decks (id, name, active, commander, player_id, ...)
SELECT id, "Name", "Active", "Commander", "Player", ... FROM data_owner."Decks";

INSERT INTO magic_stats_owner.games (id, date, first_player_id, winner_id, ...)
SELECT id, "Date", "First_Player", "Winner", ... FROM data_owner."Games";

INSERT INTO magic_stats_owner.participants (game_id, player_id, deck_id, seat, ...)
SELECT game_id, player_id, deck_id, NULL, ...  -- seat is new; existing rows get NULL, never backfilled
FROM data_owner."Participants";

-- Reset SERIAL sequences to continue after the highest migrated id
SELECT setval('magic_stats_owner.players_id_seq', (SELECT max(id) FROM magic_stats_owner.players));
SELECT setval('magic_stats_owner.decks_id_seq', (SELECT max(id) FROM magic_stats_owner.decks));
SELECT setval('magic_stats_owner.games_id_seq', (SELECT max(id) FROM magic_stats_owner.games));
```

Existing `Participant` rows have no way to know what seat a player sat in historically, so the migration leaves `seat` as `NULL` for all pre-existing rows rather than guessing — `NULL` is an explicitly valid value per the requirement, and this correctly represents "unknown" rather than fabricating data.

#### Validation checklist

- [ ] `scripts/schema.sql` runs cleanly on a fresh, empty database
- [ ] `scripts/schema.sql` re-runs cleanly against an already-built database (idempotency check)
- [ ] The one-off data-copy script runs cleanly against a copy of production data
- [ ] Row counts match between every `data_owner.*` table and its `magic_stats_owner.*` counterpart after migration
- [ ] All foreign key relationships resolve correctly in the new schema (spot-check a few decks/games/participants against known-good production records)
- [ ] All views (`v_color_usage`, `v_color_usage_player`) are recreated against `magic_stats_owner` with matching definitions
- [ ] Sequences are reset correctly so new inserts don't collide with migrated IDs
- [ ] Application code (`DB_SCHEMA` config value) updated to point at `magic_stats_owner` before deployment
- [ ] `data_owner` schema is left intact and untouched until the cutover has been verified in production for a reasonable burn-in period
- [x] **Rehearse a full restore before dropping `data_owner`.** `scripts/backup_full_database.py` and `scripts/restore_full_database.py` now exist — they wrap `pg_dump`/`pg_restore` in custom format to capture and restore the entire database (schema + data, all tables/views/sequences/constraints), rather than the row-level JSON export `backup_database.py` produces. `restore_full_database.py` refuses to restore over `DATABASE_URL` (checked before any destructive operation runs) and defaults to `LOCAL_DATABASE_URL` as its target, specifically so this can be used both for the pre-drop restore rehearsal and for pointing local dev at a real data snapshot instead of the production database. Still to do: actually run a full backup → restore cycle against a scratch database and confirm row counts match before `data_owner` is ever dropped — writing the scripts satisfies the tooling gap, not the rehearsal itself.
- [ ] Dropping `data_owner` is done manually and only after a full backup **and a successful rehearsed restore**, never as part of an automated script run

### Seat Column

**Requirement:** `Participant.seat` — nullable integer; if set, must be `>= 1` and can never exceed the number of players in that specific game.

The lower bound and nullability are enforceable with a plain per-row `CHECK` constraint. The upper bound is **not** — "never higher than the number of players in this game" is a cross-row aggregate condition (it depends on how many `Participant` rows exist for that `game_id`), and Postgres `CHECK` constraints can only see the row being written. This needs a trigger.

It also needs to be a **deferred constraint trigger** (evaluated at `COMMIT`, not immediately after each row): the current `game_add` flow inserts participants one at a time in a loop within a single transaction, so checking "seat <= player count" immediately after inserting the *first* participant would fail even for a perfectly valid 4-player game, since only 1 row exists at that point.

```sql
ALTER TABLE magic_stats_owner.participants
    ADD CONSTRAINT chk_participant_seat_min CHECK (seat IS NULL OR seat >= 1);

CREATE OR REPLACE FUNCTION magic_stats_owner.check_participant_seat()
RETURNS TRIGGER AS $$
DECLARE
    player_count INTEGER;
BEGIN
    IF NEW.seat IS NOT NULL THEN
        SELECT count(*) INTO player_count
        FROM magic_stats_owner.participants
        WHERE game_id = NEW.game_id;

        IF NEW.seat > player_count THEN
            RAISE EXCEPTION 'seat % exceeds number of players (%) in game %',
                NEW.seat, player_count, NEW.game_id;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER trg_check_participant_seat
    AFTER INSERT OR UPDATE ON magic_stats_owner.participants
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION magic_stats_owner.check_participant_seat();
```

**Tasks:**

- [x] Add the `chk_participant_seat_min` check constraint and the deferred `trg_check_participant_seat` trigger to `scripts/schema.sql` (draft already included)
- [ ] Add `seat: so.Mapped[Optional[int]]` to the `Participant` model
- [ ] Add a `seat` field to `PlayerForm` in `app/stats/forms.py` (rendered per-participant in `GameAddForm`) and to `ParticipantEditSubForm` (for `GameEditForm`)
- [ ] Validate seat values in the route/service **before** hitting the DB trigger, so the user gets a form validation error instead of a raw database exception: reject if any submitted seat exceeds the number of participants in the same submission
- [ ] **Confirm with product intent:** should two participants in the same game be allowed to share a seat number? The requirement as stated doesn't say, but "seat" conventionally implies a unique physical position at the table. Recommend adding a uniqueness check (per-game) unless there's a reason two players could share a seat.
- [ ] Update `game_add` and `game_edit` routes/services to persist the submitted `seat` value into `Participant.seat`

### Success Criteria

- All models use the same ORM style
- Related objects are accessible via relationships (no manual joins for basic lookups)
- The full schema exists under `magic_stats_owner`, structurally complete (constraints, FKs, indexes, triggers) from creation — no follow-up `ALTER` scripts needed post-cutover
- All data from `data_owner` is present in `magic_stats_owner` with matching row counts and resolvable FK relationships
- `data_owner` remains untouched and available as a rollback path until the new schema is verified in production
- Every FK has an explicit, deliberate `ondelete` policy — none left as unspecified/implicit defaults
- Core tables (`Deck`, `Game`, `Participant`, `Player`) have `created_at`/`updated_at` for auditability independent of the app-level audit log
- `Participant.seat` is nullable, never below 1, and never exceeds the actual number of players in its game (enforced by trigger, backed by route/service-level validation)
- The schema name is a single config value (`DB_SCHEMA`), not hardcoded per-file, so the next schema change doesn't require another repo-wide sweep
- The app connects to Postgres as `magic_stats_owner` in production, with `DATABASE_URL` updated accordingly
- Alembic and Flask-Migrate are fully removed from dependencies and app initialization — all schema changes going forward are made directly in `scripts/schema.sql`, reviewed and run manually
- A full restore from `scripts/backup_full_database.py`'s dump has been rehearsed and verified before `data_owner` is ever dropped
- Dead code referencing tables with no corresponding model (`scripts/skill_calculator.py` → `skill_level`) is removed rather than migrated

---

## Phase 4: Replace Raw SQL with ORM Queries

**Goal:** Eliminate fragile raw SQL strings in `api/routes.py`.

### Tasks

- [ ] **Update every remaining raw SQL reference to `magic_stats_owner` before or during rewriting.** The `data_owner` schema name (and quoted PascalCase table/column names like `"Games"`, `"Player".id`, `"Winner"`) is hardcoded directly into `text('''...''')` blocks throughout `app/api/routes.py`, plus in standalone scripts (`scripts/fetch_card_data.py`, `scripts/backup_database.py`). Since these are being rewritten to ORM anyway, target `magic_stats_owner` and the new snake_case names directly rather than rewriting twice. For any raw SQL that survives the ORM rewrite (e.g. in the standalone scripts), update the schema/table/column references explicitly — grep for `data_owner` across the repo as a final check that nothing was missed. (`scripts/skill_calculator.py` is deleted in Phase 3 and no longer relevant here.)
- [ ] Rewrite `/api/data` endpoint using SQLAlchemy ORM or hybrid expressions
- [ ] Rewrite `/api/color-data` endpoint
- [ ] Rewrite `/api/deck-data` endpoint
- [ ] Rewrite `/api/userdecks/<spieler>` endpoint
- [ ] Rewrite `/api/userdecks/archive/<spieler>` endpoint
- [ ] Rewrite `/api/data/<int:year>` endpoint
- [ ] Consider creating database views for complex aggregations (like the existing `v_color_usage`) — recreate these views under `magic_stats_owner`
- [ ] Update `scripts/fetch_card_data.py` and `scripts/backup_database.py` (both contain raw `data_owner.*` SQL) to reference `magic_stats_owner` and the new column names. (`scripts/skill_calculator.py` is deleted in Phase 3, not updated — see below.)

### Success Criteria

- No `text('''...''')` blocks longer than 5 lines in route handlers
- No references to `data_owner` remain anywhere in application code or scripts (verified by a repo-wide search) once the cutover is complete
- All queries use parameterized inputs (already true with `text()`, but ORM is more maintainable)
- Query results map to dataclasses or typed dicts, not raw tuples

---

## Phase 5: Dead Code & Cleanup

**Goal:** Remove unused code, fix style issues, establish conventions.

### Tasks

- [ ] **Set up logging infrastructure first** — there is currently no `logging.basicConfig()` or handler configuration anywhere in the app. Configure a logger (level, format, stream/file handler) in `create_app()` before migrating any `print()` calls to it.
- [ ] Delete or rewrite `app/third_party_data/scryfall.py` (references non-existent model fields)
- [ ] Fix concrete bugs in `app/third_party_data/deckbuilder.py`:
  - `load_cards_from_archidekt()`: if `pyrchidekt.api.getDeckById()` raises, the exception is only printed and execution falls through to use the now-unassigned `deck` variable, causing an `UnboundLocalError` (currently masked by a later bare `except`). Return/raise early on failure instead.
  - `db.session.commit;` (missing parentheses) is dead code that never actually commits — fix or remove.
- [ ] Fix `app/third_party_data/scryfall.py` `get_card_data()`: the outer `except Exception: pass` swallows all errors with no `db.session.rollback()`, and `chunk_size=total_length / 1000` passes a float where `iter_content` expects an int (also masked by the same except)
- [ ] Add `timeout=` to all `requests.get()` calls in `scryfall.py` (bulk-data API and CDN download) — currently unbounded and can hang a worker indefinitely
- [ ] Remove all `print()` statements — replace with `logging` module (including debug leftovers like `print(spieler)` in `app/main/routes.py` `user()`)
- [ ] Fix bare `except:` clauses — catch specific exceptions, log the error (includes `app/main/routes.py` `player()`, not just the ones already flagged)
- [ ] Remove variable shadowing (`for player in player:` in `get_player()`)
- [ ] Fix double-commit pattern — audit entry and main operation in same transaction
- [ ] Fix partial-update risk in `decks/routes.py` `deck_edit`: `deck.Name` changes are committed before the decklist/card load runs, so a failure in card loading leaves a partial update. Wrap both in a single transaction.
- [ ] Remove unused `Flask-Security` dependency if only `RoleMixin` is needed (it's not even used properly)
- [ ] Add `py.typed` marker and type hints to all service functions
- [ ] Add a `pyproject.toml` to replace/complement `requirements.txt` for dev tooling config

### Success Criteria

- Zero `print()` calls in application code
- No bare `except:` clauses
- All external HTTP calls have explicit timeouts
- Linting passes cleanly (configure `ruff` or `flake8`)

---

## Phase 6: Test Suite

**Goal:** Comprehensive test coverage starting with the most critical paths.

### 6.1 Test Infrastructure Setup

**Sequencing note:** Phase 3 splits into two parts with very different risk profiles — (a) the ORM-level model changes (`Mapped[]` style, relationships, English/snake_case naming decisions) and (b) the actual `data_owner` → `magic_stats_owner` database cutover (new role, parallel schema build, data copy, `DATABASE_URL` change). Part (a) can and should land early, alongside Phase 1, since it's the shape 6.1's fixtures need. Part (b) is the high-risk, dedicated-maintenance-window piece and can trail behind — 6.1 does not need to wait for the live cutover, only for the model definitions to be finalized.

- [ ] Create `tests/` directory with `conftest.py`
- [ ] Configure test database (SQLite in-memory or test PostgreSQL schema) — build it against the finalized post-Phase-3(a) model shape (naming, relationships, constraints), not the legacy structure, since tests should validate the code the project is moving to, not the one being retired. This does not require the `magic_stats_owner` cutover (3b) to have actually happened yet.
- [ ] Create fixtures: `app`, `client`, `db_session`, `authenticated_client`, `admin_client`
- [ ] Create factory functions for test data: `create_player()`, `create_deck()`, `create_game()`
- [ ] Add `pytest.ini` or `pyproject.toml [tool.pytest.ini_options]` config
- [ ] Add `pytest-cov` for coverage reporting

### 6.2 Unit Tests (Service Layer)

- [ ] `tests/services/test_elo_service.py` — Elo calculation edge cases, K-factor selection, multiplayer normalization
- [ ] `tests/services/test_stats_service.py` — Participant averages, win/turn stats, pod size breakdown
- [ ] `tests/services/test_deck_service.py` — Version bumping, archive/dearchive, card loading
- [ ] `tests/services/test_game_service.py` — Game creation, participant assignment, deletion cascades
- [ ] `tests/services/test_audit_service.py` — Audit log entries created correctly
- [ ] `tests/services/test_color_service.py` — Color image resolution, colorless fallback

### 6.3 Integration Tests (Routes)

- [ ] `tests/routes/test_auth.py` — Login, logout, registration, inactive account rejection
- [ ] `tests/routes/test_main.py` — Index loads, user profile, player profile
- [ ] `tests/routes/test_stats.py` — Game add, player add, deck add (form submission)
- [ ] `tests/routes/test_api.py` — JSON endpoints return expected structure
- [ ] `tests/routes/test_decks.py` — Deck edit, version bump, archive, achievements
- [ ] `tests/routes/test_cards.py` — Card meta page

### 6.4 Edge Case & Regression Tests

- [ ] Games with 3, 4, and 5 players produce correct stats
- [ ] Elo ratings are zero-sum across a game
- [ ] Deck with 0 games doesn't crash stats pages
- [ ] Borrowed deck scenario works correctly in game add
- [ ] Concurrent version bumps don't corrupt deck versioning

### Success Criteria

- 80%+ line coverage on service layer
- All critical user flows have at least one happy-path integration test
- Tests run in < 30 seconds (use in-memory DB, minimal fixtures)
- CI-ready: `pytest --tb=short -q` exits cleanly

---

## Phase 7: Developer Experience

**Goal:** Make the project easy to work on going forward.

### Tasks

- [ ] Add `pyproject.toml` with tool configs (ruff, pytest, mypy)
- [ ] Add `Makefile` or `justfile` with common commands (`make test`, `make lint`, `make migrate`)
- [ ] Add pre-commit hooks (ruff, mypy)
- [ ] Document local dev setup in `README.md`
- [ ] Add `.env.example` with required environment variables — including `DB_SCHEMA` (added in Phase 3) and the `magic_stats_owner` connection credentials, not just the pre-existing `DATABASE_URL`/`SECRET_KEY`

### Success Criteria

- New contributor can set up and run tests within 10 minutes
- Linting and type checking run on every commit

---

## Phase 8: Dependency & Package Hygiene

**Goal:** Remove outdated/redundant packages, pin responsibly, and modernize the stack where it matters.

### Packages to Remove or Replace

| Package | Issue | Action |
|---------|-------|--------|
| `Flask-Security==5.6.2` | Only `RoleMixin` was imported, and only by the now-deleted `Role`/`UserRoles` models (see Phase 3) — nothing else in the codebase used it. Flask-Security pulls in heavy transitive deps (passlib, etc.) | **Remove entirely** — the custom `role_required` decorator in `app/auth/__init__.py` already handles authorization |
| `Flask-Principal==0.4.0` | Set up in `app/__init__.py` and `webstats.py` but the `identity_loaded` handler grants admin to everyone. No real permission checks use it | **Remove** — replace with the existing `role_required` decorator or a lightweight alternative |
| `WTForms-SQLAlchemy==0.4.2` | `QuerySelectField` is imported in forms but never actually used | **Remove** unless planned for future use |
| `libpass==1.9.1.post0` | Transitive dep from Flask-Security — goes away when Flask-Security is removed | Auto-removed |
| `Pygments==2.20.0` | No syntax highlighting anywhere in the app | **Remove** (likely a transitive dep, verify first) |
| `alembic==1.16.5`, `Flask-Migrate==4.1.0` | Decided in Phase 3: database administration is handled manually via `scripts/schema.sql`, not Alembic. Never had a working baseline in this project anyway (no `migrations/versions/`) | **Remove entirely** — drop both packages, remove `migrate = Migrate()` / `migrate.init_app(app, db)` from `app/__init__.py` |

### Packages to Keep but Note

| Package | Notes |
|---------|-------|
| `gunicorn==25.3.0` | Windows-incompatible (note that local dev uses Flask's built-in server). **Verify this version number against PyPI** — `25.3.0` doesn't match gunicorn's actual release history and may be a typo or a stale/incorrect pin |
| `pyrchidekt==2.1.0` | Third-party Archidekt client — wrap calls with retry logic and proper error handling |
| `ijson==3.4.0` | Used for streaming JSON parsing of Scryfall bulk data — good choice, keep |
| `hypothesis==6.165.10` | Added to `requirements.txt`. Required by the property-based tests specified in the `card-data-restructure` and `card-name-autocomplete` specs (Phase 6 unit/property tests also depend on it). Move to a dev-only dependency group alongside `pytest`/`pytest-cov` per the task below — it's a test-time dependency, not a runtime one |

### Tasks

- [ ] Remove `Flask-Security`, `Flask-Principal`, `WTForms-SQLAlchemy`, `libpass`, `Pygments`, `alembic`, `Flask-Migrate` from `requirements.txt`
- [ ] Remove all imports of `flask_security` and `flask_principal` from application code
- [ ] Remove `principals` initialization from `app/__init__.py`
- [ ] Remove the `identity_loaded` handler and `identity_changed` calls from `webstats.py` and `auth/routes.py` — **this is the same fix already listed in Phase 2**, done once alongside that task rather than twice; don't duplicate the change
- [ ] Remove `migrate = Migrate()` and `migrate.init_app(app, db)` from `app/__init__.py`. (The old `migrations/` directory has already been deleted — see Phase 3.)
- [ ] Verify the app still starts and all auth/role checks pass with the remaining `role_required` decorator
- [ ] Move `pytest`, `pytest-cov`, and `hypothesis` to a separate `requirements-dev.txt` (or `[dev]` extras in `pyproject.toml`)
- [ ] Pin `ruff` as a dev dependency for linting
- [ ] Verify the `gunicorn==25.3.0` pin against PyPI and correct it if it's wrong
- [ ] Separate direct dependencies from transitive ones in `requirements.txt` (e.g. via `pip-compile` from a minimal `requirements.in`) so it's clear what the app actually imports vs. what's pulled in

---

## Phase 9: Frontend & API Response Patterns

**Goal:** Fix anti-patterns in how data flows from backend to frontend.

### Current Issues

1. **Bizarre JSON structure** — API endpoints return arrays-of-dicts where each value is a single-element list:
   ```json
   {"Name": ["Niklas"], "Games": [42], "Wins": [10]}
   ```
   This forces the frontend to access `item.Name[0]` everywhere instead of just `item.Name`. It's error-prone and non-standard.

2. **Inline JSON in templates** — The index page embeds Python data into `<script>` tags via Jinja, mixing concerns. The dashboard JS already fetches from `/api/` endpoints for other pages — the index should do the same.

3. **No CDN fallback or bundling** — Chart.js and plugins are loaded from `cdn.jsdelivr.net` with no version lock in a lockfile, no subresource integrity (SRI) hashes, and no local fallback if the CDN is down.

4. **No API error handling in frontend JS** — `fetch()` calls have `.then()` but no `.catch()` — network errors silently fail.

5. **Inconsistent date formatting** — Backend manually builds `str(entry[4].day) + "." + str(entry[4].month) + "." + str(entry[4].year)` instead of using `strftime` or returning ISO strings and letting the frontend format.

6. **Reflected XSS risk in `deckstats.js`** — `populateTable()` builds `row.innerHTML` via template literals that directly interpolate `item[key]` (deck names, player names) and tag strings without HTML-escaping. Deck names/tags are user-editable and tags are pulled from Archidekt imports, so unescaped values flowing into `innerHTML` is a genuine injection vector, not just a style issue.

### Tasks

- [ ] Normalize all API responses to flat objects: `{"name": "Niklas", "games": 42, "wins": 10}`
- [ ] Update frontend JS to match new response shape (search-and-replace `[0]` accessors)
- [ ] Return dates as ISO strings (`YYYY-MM-DD`) from all endpoints — format in frontend if needed
- [ ] Add `.catch()` error handlers to all `fetch()` calls in JS
- [ ] Add SRI hashes to CDN script tags, or vendor Chart.js locally
- [ ] Move inline chart data on the index page to an API endpoint
- [ ] Fix XSS in `deckstats.js` `populateTable()` — escape interpolated values (deck names, tags, player names) before inserting into `innerHTML`, or build rows via `textContent`/DOM APIs instead of string concatenation

### Success Criteria

- No API response contains single-element arrays as values
- All dates are ISO-formatted in API responses
- Frontend handles fetch errors gracefully (shows user-facing error state)
- No unescaped user-controlled data is passed to `innerHTML` anywhere in the frontend

---

## Phase 10: Application Architecture Improvements

**Goal:** Address structural patterns that don't fit cleanly into earlier phases.

### 10.1 Background Task Queue (Redis/RQ)

The Procfile references an RQ worker (`rq worker`) but the actual task queueing code is commented out or broken:
- `load_cards_for_decks()` references `current_app.task_queue.enqueue(...)` but `task_queue` is never initialized on the app
- The function falls through to calling `load_all_decks()` synchronously as a route handler

**Tasks:**
- [ ] Decide: keep RQ or remove it. If the card import is fast enough synchronously, drop the Redis dependency
- [ ] If keeping: properly initialize the task queue in `create_app()`, add health checks
- [ ] If removing: delete the `worker` line from `Procfile`, remove `redis` references

### 10.2 Form Validation in Routes

Forms call `db.session.scalar()` inside validators — this couples form validation directly to the database and makes forms untestable in isolation.

**Tasks:**
- [ ] Move uniqueness checks to the service layer (validate in the route after form validation)
- [ ] Or accept this WTForms pattern but document it as intentional

### 10.3 Error Responses for API Endpoints

API routes (`/api/*`) return HTML error pages on failure (Flask's default 404/500 handlers). They should return JSON.

**Tasks:**
- [ ] Register JSON error handlers for the `api` blueprint
- [ ] Return `{"error": "message"}` with appropriate HTTP status codes
- [ ] Ensure frontend JS can parse error responses

### 10.4 Configuration for Multiple Environments

`config.py` only has one `Config` class. No distinction between dev, test, staging, production.

**Tasks:**
- [ ] Add `DevelopmentConfig`, `TestingConfig`, `ProductionConfig` subclasses
- [ ] `TestingConfig` should use SQLite in-memory or a separate test schema
- [ ] `ProductionConfig` should enforce `SECRET_KEY` is set, enable secure cookies, and explicitly disable `DEBUG`
- [ ] Add `SQLALCHEMY_ENGINE_OPTIONS` (pool size, `pool_pre_ping`, etc.) to `config.py` — currently unset, relying entirely on SQLAlchemy defaults

---

## Phase 11: Codebase Documentation

**Goal:** Produce comprehensive, maintainable documentation in `docs/` once the refactoring is complete.

### Directory Structure: `docs/`

```
docs/
├── index.md                  -- Overview, links to all sections
├── architecture.md           -- High-level architecture, blueprint layout, request flow
├── models.md                 -- Data model reference (tables, relationships, ER diagram)
├── services.md               -- Service layer API docs (public functions, parameters, return types)
├── api/
│   ├── index.md              -- API overview, authentication, error format
│   ├── player.md             -- Player-related endpoints
│   ├── deck.md               -- Deck-related endpoints
│   ├── game.md               -- Game-related endpoints
│   └── stats.md              -- Statistics endpoints
├── guides/
│   ├── local-setup.md        -- Local development environment setup
│   ├── deployment.md         -- Production deployment (Heroku/Gunicorn, env vars)
│   ├── database-migrations.md -- How to write and run migration scripts
│   └── adding-a-feature.md   -- Walkthrough: adding a new feature end-to-end
├── decisions/
│   └── adr-001-remove-flask-security.md  -- Architecture Decision Records
└── testing.md                -- How to run tests, write new tests, coverage targets
```

### Content Requirements

- **Architecture doc** — explains the blueprint structure, service layer, how data flows from route → service → model → response
- **Models doc** — documents every table, column purpose, and relationships. Include a Mermaid ER diagram or link to one
- **API docs** — for each endpoint: method, path, parameters, request/response examples, auth requirements
- **Service docs** — auto-generated from docstrings (or manually written). Each public function documented with purpose, params, return type, and exceptions
- **Guides** — practical, step-by-step instructions a new developer can follow
- **ADRs** — document significant decisions made during refactoring (why Flask-Security was removed, why raw SQL was replaced, etc.)

### Tasks

- [ ] Create `docs/` directory structure
- [ ] Write `docs/index.md` with project overview and navigation
- [ ] Write `docs/architecture.md` covering blueprints, service layer, and data flow
- [ ] Write `docs/models.md` with table documentation and ER diagram
- [ ] Write `docs/services.md` documenting all service module functions
- [ ] Write API endpoint documentation for each blueprint's routes
- [ ] Write `docs/guides/local-setup.md` (prerequisites, venv, env vars, DB setup, running the app)
- [ ] Write `docs/guides/deployment.md` (Heroku config, Procfile, environment variables)
- [ ] Write `docs/guides/database-migrations.md` (how to edit and run `scripts/schema.sql`, and how the separate one-off data-copy/cutover scripts work)
- [ ] Write `docs/guides/adding-a-feature.md` (service → route → template → test workflow)
- [ ] Write `docs/testing.md` (running tests, writing new ones, coverage goals)
- [ ] Create ADRs for the significant decisions made during this refactor, at minimum:
  - `adr-001-remove-flask-security.md` — why Flask-Security/Flask-Principal were removed in favor of the existing `role_required` decorator
  - `adr-002-parallel-schema-cutover.md` — why the `data_owner` → `magic_stats_owner` migration was done as a fresh parallel-schema build + data copy rather than incremental in-place `ALTER`s
  - `adr-003-no-alembic.md` — why Alembic/Flask-Migrate were dropped in favor of a single, hand-maintained, always-current `scripts/schema.sql`
  - `adr-004-seat-deferred-trigger.md` — why `Participant.seat`'s upper-bound validation required a deferred constraint trigger instead of a plain `CHECK` constraint
- [ ] Add docstrings to all service functions so docs can be partially auto-generated

### Success Criteria

- A new developer can read `docs/guides/local-setup.md` and have the app running locally within 15 minutes
- Every API endpoint is documented with request/response examples
- Architecture decisions are recorded and searchable
- Documentation stays in sync with code (add a CI check or note in contributing guide)

---

## Phase 12: Agent Steering Files for Codebase Consistency

**Goal:** Create Kiro steering files (`.kiro/steering/`) that encode the project's conventions, patterns, and architectural decisions. These act as living guidelines that ensure future development — whether by a human or an AI agent — follows the same standards established during refactoring.

### Why Steering Files

Steering files are automatically included in agent context when relevant files are touched. This means:
- When adding a new route, the agent sees the route/service pattern rules
- When writing a model, the agent sees the ORM conventions
- When creating an API endpoint, the agent sees the response format standards
- Conventions are enforced at development time, not just in code review

### Steering Files to Create

#### 1. `.kiro/steering/architecture.md` (always included)

High-level architecture overview. Included in every interaction.

**Content:**
- Project structure: blueprints, service layer, models, templates, static
- Request flow: Route → Service → Model → Response
- Blueprint responsibilities (what goes where)
- Separation of concerns: routes are thin, services hold logic, models hold data
- No business logic in route handlers (max ~30 lines)
- No direct `db.session` calls in routes — go through services

#### 2. `.kiro/steering/models.md` (conditional: `fileMatchPattern: "app/models.py"`)

Triggered when the models file is read or edited.

**Content:**
- All models use SQLAlchemy 2.0 `Mapped[]` style
- Column naming: snake_case only, English only
- Every model must define `__tablename__` and `__table_args__` with schema
- Relationships must use `relationship()` with explicit `back_populates`
- No `db.Column()` legacy style — use `mapped_column()`
- Foreign keys reference lowercase table names
- All new tables or schema changes are made directly in `scripts/schema.sql`, keeping it a complete, idempotent, always-current build script — there is no Alembic/Flask-Migrate in this project, and no separate versioned migration files; schema changes are manual and reviewed

#### 3. `.kiro/steering/api-routes.md` (conditional: `fileMatchPattern: "app/api/**"`)

Triggered when working on API endpoints.

**Content:**
- All API responses are flat JSON objects (no single-element arrays as values)
- Dates returned as ISO 8601 strings (`YYYY-MM-DD`)
- Error responses: `{"error": "message"}` with appropriate HTTP status code
- All endpoints require `@login_required`
- Admin-only endpoints use `@role_required('admin')`
- No raw SQL — use ORM queries or database views
- Response data uses snake_case keys
- Endpoints that modify data must write to the audit log via the audit service

#### 4. `.kiro/steering/services.md` (conditional: `fileMatchPattern: "app/services/**"`)

Triggered when working on service modules.

**Content:**
- Every public function has a docstring with Args/Returns/Raises
- All functions have type hints (parameters and return type)
- Services accept primitive types or model instances — never raw form data or request objects
- Services raise specific exceptions (not bare `Exception`) for error cases
- Database transactions are handled within the service (commit or rollback)
- Audit logging is part of the same transaction as the operation
- No Flask request/response context inside services (keep them framework-agnostic)

#### 5. `.kiro/steering/frontend.md` (conditional: `fileMatchPattern: "app/static/js/**"`)

Triggered when working on JavaScript files.

**Content:**
- All `fetch()` calls must include `.catch()` error handling
- API responses are flat objects — access `item.name` not `item.Name[0]`
- DOM manipulation uses vanilla JS (no jQuery)
- Chart.js is the charting library — no alternatives
- Scripts use `defer` attribute when loaded in templates
- Variables use camelCase
- Event listeners attached via `addEventListener`, not inline HTML attributes

#### 6. `.kiro/steering/templates.md` (conditional: `fileMatchPattern: "app/templates/**"`)

Triggered when working on Jinja2 templates.

**Content:**
- All templates extend `base.html`
- Page-specific CSS goes in `{% block head %}` as a `<link>` tag
- Page-specific JS goes in `{% block head %}` with `defer`
- Use `url_for()` for all links and static assets — never hardcode paths
- Flash messages are rendered by `base.html` — don't duplicate
- Templates should not contain business logic — prep data in the route/service
- Accessibility: all images need `alt` attributes, form fields need labels

#### 7. `.kiro/steering/testing.md` (conditional: `fileMatchPattern: "tests/**"`)

Triggered when writing tests.

**Content:**
- Use `pytest` with fixtures from `conftest.py`
- Unit tests for services: mock the database, test logic in isolation
- Integration tests for routes: use the Flask test client with a test database
- Test file naming: `test_<module>.py` mirrors `app/<module>`
- Factory functions for test data: `create_player()`, `create_deck()`, `create_game()`
- Assertions use plain `assert` (not `self.assertEqual`)
- Each test function tests one behavior — name describes the scenario
- Target 80%+ coverage on service layer, 60%+ on routes

### Tasks

- [ ] Create `.kiro/steering/architecture.md` — always included, project-wide conventions
- [ ] Create `.kiro/steering/models.md` — model/ORM conventions, triggered on model files
- [ ] Create `.kiro/steering/api-routes.md` — API patterns, triggered on api/ files
- [ ] Create `.kiro/steering/services.md` — service layer rules, triggered on services/ files
- [ ] Create `.kiro/steering/frontend.md` — JavaScript conventions, triggered on JS files
- [ ] Create `.kiro/steering/templates.md` — Jinja2/HTML patterns, triggered on template files
- [ ] Create `.kiro/steering/testing.md` — test conventions, triggered on test files
- [ ] Verify steering files are picked up correctly (conditional inclusion via `fileMatchPattern`)
- [ ] Review and refine after first few features are built with them active

### Success Criteria

- Every part of the codebase has a corresponding steering file that activates contextually
- New features built with steering files active follow project conventions without manual reminders
- Steering files are treated as living documents — updated when conventions evolve

---

## Execution Order & Dependencies

```
Phase 1 (Service Layer) ──┐
                          ├──→ Phase 6.2 (Unit Tests)
Phase 2 (Security) ──────┘
Phase 8 (Dep Cleanup) ───→ runs with Phase 2 (removes Flask-Security/Principal/Alembic)

Phase 3 (Models + Migrations) ─→ Phase 4 (Replace Raw SQL)

Phase 5 (Cleanup) ────────→ Phase 6.3 (Integration Tests)

Phase 9 (API/Frontend) ───→ can run after Phase 4

Phase 10 (Architecture) ──→ can run in parallel with Phases 5-9

Phase 7 (DX) ── can run in parallel with any phase

Phase 11 (Documentation) ─→ runs after refactoring is complete
Phase 12 (Steering Files) ─→ runs alongside or after Phase 11
```

Phases 1 and 2 are the foundation. Phase 6.1 (test infra) should happen alongside Phase 1, once Phase 3's model-level changes (naming, relationships — not the live `data_owner` → `magic_stats_owner` cutover itself) are finalized, so services are tested against the shape the code is moving to. Phase 12 can start as soon as conventions are established (after Phases 1-5) but should be finalized after Phase 11 so the steering files and docs are consistent.

---

## Estimated Effort

| Phase | Effort | Risk |
|-------|--------|------|
| 1. Service Layer | Medium-High | Low (pure refactor, no behavior change) |
| 2. Security | Low | Medium (must verify no auth regressions) |
| 3. Models + Migrations | High (full parallel-schema rebuild, data copy, new role/credentials, seat trigger, restore rehearsal — no longer a simple rename) | High (DB migration required) |
| 4. Raw SQL → ORM | Medium | Medium (must match existing query results) |
| 5. Cleanup | Low | Low |
| 6. Test Suite | High | Low |
| 7. Developer Experience | Low | Low |
| 8. Dependency Cleanup | Low | Low (remove unused packages) |
| 9. Frontend/API Patterns | Medium | Medium (frontend + backend changes together) |
| 10. Architecture | Medium | Low-Medium |
| 11. Documentation | Medium | Low (no code changes, just writing) |
| 12. Steering Files | Low-Medium | Low (no code changes, convention encoding) |

---

## Notes

- Phase 3 (model renames) requires coordination with the database. Run on a staging copy first.
- **Phase 3's `data_owner` → `magic_stats_owner` cutover is a bigger operational change than a rename and deserves a dedicated maintenance window.** Because the new schema is built fresh (not `ALTER`ed in place), the app must point at one schema or the other atomically — there's no safe middle state where some requests hit `data_owner` and others hit `magic_stats_owner`. Plan for brief downtime (or a maintenance-mode page) during the actual cutover, even though the schema build and data copy can happen ahead of time with zero downtime.
- **No `data_owner` schema changes will land while this migration is in progress.** The project owner has committed to freezing schema changes for the duration of the Phase 3 build — no new specs adding tables/columns until the cutover is complete. This removes the schema-drift risk that would otherwise require re-diffing `scripts/schema.sql` against a moving target mid-migration.
- **Standing rule: any new library introduced anywhere in this refactor gets added to `requirements.txt` (or `requirements-dev.txt` once Phase 8 splits it out) with a pinned exact version in the same change that introduces it.** Don't let a spec or task add an import without also updating the dependency file — `hypothesis` (added above) is the first instance of this rule being applied.
- **Local development currently points at the production database (`DATABASE_URL`).** This is a problem for Phase 3's migration work specifically — schema experiments during the `magic_stats_owner` build shouldn't run against production. `scripts/backup_full_database.py` (full `pg_dump` of schema + data) and `scripts/restore_full_database.py` (restores into a target database, refusing to ever target `DATABASE_URL`) now exist so a production snapshot can be pulled down and restored into a local Postgres instance — see `LOCAL_DATABASE_URL` in `.env.example`. Point local `.env`'s `DATABASE_URL` at that local database before starting Phase 3 experimentation.
- The existing `v_color_usage` and `v_color_usage_player` views show the right pattern — more complex aggregations should be views rather than inline SQL.
- `pyrchidekt` (Archidekt API client) is a third-party dependency with no error handling around it — worth wrapping in a retry/fallback in the deck service.
- The RQ worker in the Procfile suggests this was meant to handle long-running imports async, but the infrastructure isn't wired up — decide early whether to fix or remove it.
