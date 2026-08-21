"""
Full database restore script — restores a pg_dump custom-format dump
(produced by scripts/backup_full_database.py) into a target database.

Intended use: pull a production backup down and restore it into a local
Postgres instance for development, so local dev no longer points at the
production database while the data_owner -> magic_stats_owner migration is
underway.

This also doubles as the "rehearse a full restore before dropping
data_owner" step called for in REFACTOR_PLAN.md's Phase 3 validation
checklist — run it against a scratch database and confirm the data comes
back intact before anything in production is ever dropped.

Requires the PostgreSQL client tools (pg_restore, createdb, dropdb) to be
installed and either on PATH or discoverable via the PG_BIN_DIR environment
variable / the --pg-bin-dir argument.

SAFETY:
    This script can DROP AND RECREATE the target database when --clean is
    passed. It refuses to run without --clean or --create unless the
    target database does not exist yet. It never touches the source
    (production) database — it only ever connects to --database-url as a
    write target for the restore itself, and to the server's default
    'postgres' database for create/drop-database administration.

Usage:
    # Restore into a fresh local database (created if it doesn't exist):
    python scripts/restore_full_database.py --dump-file backups/full_20260820_120000/database.dump \
        --database-url postgresql://postgres:postgres@localhost:5432/magicwebstats_dev --create

    # Wipe and re-restore into an existing local database:
    python scripts/restore_full_database.py --dump-file backups/full_20260820_120000/database.dump \
        --database-url postgresql://postgres:postgres@localhost:5432/magicwebstats_dev --clean
"""

import argparse
import os
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv


def find_tool(name: str, pg_bin_dir: str | None) -> str:
    """Locate a PostgreSQL client tool, preferring an explicit bin dir, then PATH."""
    exe_name = f"{name}.exe" if os.name == "nt" else name
    candidates = []
    if pg_bin_dir:
        candidates.append(os.path.join(pg_bin_dir, exe_name))

    env_bin_dir = os.environ.get("PG_BIN_DIR")
    if env_bin_dir:
        candidates.append(os.path.join(env_bin_dir, exe_name))

    on_path = shutil.which(name)
    if on_path:
        candidates.append(on_path)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    print(f"ERROR: Could not find {name}. Install the PostgreSQL client tools and "
          "either add them to PATH, set PG_BIN_DIR, or pass --pg-bin-dir.")
    print("On Windows, the client tools typically live at:")
    print(r"  C:\Program Files\PostgreSQL\<version>\bin")
    sys.exit(1)


def split_db_url(db_url: str):
    """Split a database URL into (server_url_pointing_at_postgres_db, database_name)."""
    parts = urlsplit(db_url)
    db_name = parts.path.lstrip("/")
    if not db_name:
        print("ERROR: --database-url must include a database name, e.g. "
              "postgresql://user:pass@host:5432/mydb")
        sys.exit(1)
    admin_parts = parts._replace(path="/postgres")
    return urlunsplit(admin_parts), db_name


def database_exists(psql_path: str, admin_url: str, db_name: str) -> bool:
    result = subprocess.run(
        [psql_path, admin_url, "-tAc",
         f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        print("ERROR: Could not check whether the target database exists "
              "(is the target Postgres server reachable?).")
        sys.exit(result.returncode)
    return result.stdout.strip() == "1"


def run_streaming(cmd, label):
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        print(f"\nERROR: {label} exited with status {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-file", required=True,
        help="Path to the .dump file produced by scripts/backup_full_database.py",
    )
    parser.add_argument(
        "--database-url", default=None,
        help="Target database URL to restore into, e.g. "
             "postgresql://postgres:postgres@localhost:5432/magicwebstats_dev. "
             "Defaults to LOCAL_DATABASE_URL from the environment/.env if set — "
             "DATABASE_URL (the production URL) is deliberately NOT used as a default "
             "here, to avoid accidentally restoring over production.",
    )
    parser.add_argument(
        "--pg-bin-dir", default=None,
        help=r'Directory containing pg_restore/psql/createdb/dropdb '
             r'(e.g. "C:\Program Files\PostgreSQL\18\bin"). '
             "Falls back to the PG_BIN_DIR env var, then PATH.",
    )
    parser.add_argument(
        "--create", action="store_true",
        help="Create the target database first if it doesn't already exist.",
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Drop and recreate the target database before restoring, even if it "
             "already exists. DESTRUCTIVE to whatever is currently in that database.",
    )
    parser.add_argument(
        "--jobs", type=int, default=1,
        help="Number of parallel pg_restore jobs (custom format supports this). Default: 1.",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.dump_file):
        print(f"ERROR: Dump file not found: {args.dump_file}")
        sys.exit(1)

    load_dotenv()

    db_url = args.database_url or os.environ.get("LOCAL_DATABASE_URL", "")
    db_url = db_url.replace("postgres://", "postgresql://")
    if not db_url:
        print("ERROR: No target database URL provided. Pass --database-url or set "
              "LOCAL_DATABASE_URL in the environment. Refusing to fall back to "
              "DATABASE_URL to avoid restoring over the production database.")
        sys.exit(1)

    prod_url = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://")
    if prod_url and db_url == prod_url:
        print("ERROR: --database-url matches DATABASE_URL (the production database). "
              "Refusing to restore over production. Point this at a local database instead.")
        sys.exit(1)

    pg_restore = find_tool("pg_restore", args.pg_bin_dir)
    psql = find_tool("psql", args.pg_bin_dir)
    createdb = find_tool("createdb", args.pg_bin_dir)
    dropdb = find_tool("dropdb", args.pg_bin_dir)

    admin_url, db_name = split_db_url(db_url)
    exists = database_exists(psql, admin_url, db_name)

    if exists and args.clean:
        print(f"Dropping existing database '{db_name}'...")
        run_streaming([dropdb, "--if-exists", "--maintenance-db", admin_url, db_name], "dropdb")
        exists = False

    if not exists:
        if not args.create and not args.clean:
            print(f"ERROR: Target database '{db_name}' does not exist. Pass --create to "
                  "create it, or --clean to drop (if present) and recreate it.")
            sys.exit(1)
        print(f"Creating database '{db_name}'...")
        run_streaming([createdb, "--maintenance-db", admin_url, db_name], "createdb")
    else:
        print(f"Target database '{db_name}' already exists — restoring into it as-is "
              "(existing objects with the same name will cause pg_restore to report "
              "'already exists' errors; use --clean for a guaranteed-empty restore).")

    print(f"\nRestoring '{args.dump_file}' into '{db_name}'...")
    cmd = [
        pg_restore,
        "--verbose",
        "--no-owner",
        "--no-privileges",
        "--jobs", str(args.jobs),
        "--dbname", db_url,
        args.dump_file,
    ]
    run_streaming(cmd, "pg_restore")

    print(f"\nRestore complete: '{db_name}' now contains the data from {args.dump_file}")
    print("Point your local .env's DATABASE_URL at this database to use it for development.")


if __name__ == "__main__":
    main()
