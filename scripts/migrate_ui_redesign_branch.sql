-- =============================================================================
-- BRANCH MIGRATION: feature/ui-redesign
-- =============================================================================
-- Single, rerunnable migration collecting every schema change introduced on the
-- feature/ui-redesign branch. Apply it ONCE to production when the branch
-- merges; it is idempotent, so running it again (or after partial application)
-- is a safe no-op.
--
-- No Alembic is used in this project (ADR-001); schema changes are hand-run SQL
-- and mirrored in scripts/schema.sql (the single source of truth).
--
-- ── How to use ───────────────────────────────────────────────────────────────
--   • Local development (allowed): apply against LOCAL_DATABASE_URL as you go.
--   • Production (owner-run only): run this whole file once on merge. Per the
--     project's database-safety rule, the agent never runs writes against the
--     production DATABASE_URL — the owner runs the command below themselves:
--
--         psql "$DATABASE_URL" -f scripts/migrate_ui_redesign_branch.sql
--
-- Each change is wrapped in its own transaction and guarded, so the file can
-- grow as the branch adds further schema changes without breaking re-runs.
-- =============================================================================


-- -----------------------------------------------------------------------------
-- Change 1 — User role tiers: constrain users.role to the known set.
-- -----------------------------------------------------------------------------
-- The role concept gained a middle tier. Roles are now exactly one of:
--   'user'       — normal authenticated rights.
--   'maintainer' — user + add players/decks/games and moderate archives.
--   'admin'      — maintainer + audit log, Elo recalculation, role management.
--
-- The column already exists (VARCHAR(64) NOT NULL DEFAULT 'user'); this change
-- only ADDS a CHECK constraint so invalid/typo roles (e.g. from the new role-
-- management UI) can never be stored. Existing 'admin' and 'user' rows already
-- satisfy it and are left untouched (existing admins stay admins by design).
--
-- Guarded drop+add makes the constraint swap idempotent.
BEGIN;

-- Defensive: if any legacy row holds a role outside the known set, this
-- migration would fail when adding the CHECK. Surface such rows instead of
-- silently rewriting them — inspect and fix them by hand first:
--
--   SELECT id, username, role FROM magic_stats_owner.users
--   WHERE role NOT IN ('user', 'maintainer', 'admin');
--
-- (No automatic UPDATE here: we must not guess a user's intended privilege.)

ALTER TABLE magic_stats_owner.users
    DROP CONSTRAINT IF EXISTS ck_users_role;
ALTER TABLE magic_stats_owner.users
    ADD CONSTRAINT ck_users_role
    CHECK (role IN ('user', 'maintainer', 'admin'));

COMMIT;


-- =============================================================================
-- Verification (run manually after applying; not part of any transaction):
--
--   -- Constraint exists:
--   SELECT conname, pg_get_constraintdef(oid)
--   FROM pg_constraint
--   WHERE conrelid = 'magic_stats_owner.users'::regclass
--     AND conname = 'ck_users_role';
--
--   -- Current role distribution:
--   SELECT role, count(*) FROM magic_stats_owner.users GROUP BY role ORDER BY role;
--
--   -- Should return zero rows (no out-of-set roles):
--   SELECT id, username, role FROM magic_stats_owner.users
--   WHERE role NOT IN ('user', 'maintainer', 'admin');
-- =============================================================================
