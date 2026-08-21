"""
Full database backup script (schema + data, all schemas/roles).

Wraps `pg_dump` to produce a single compressed custom-format dump file that
can be restored with `scripts/restore_full_database.py` (or `pg_restore`
directly). This is the recommended backup for the data_owner ->
magic_stats_owner migration: unlike backup_database.py (which only exports
data_owner's tables as JSON, useful for row-count spot checks), this script
captures the entire database byte-for-byte, including schemas, roles*,
sequences, views, and constraints, so a restore reproduces the source
database exactly.

* pg_dump only captures role GRANTs referenced by dumped objects, not
  CREATE ROLE statements themselves. If you rely on custom roles/passwords,
  make sure they also exist in the target database (see the migration
  scripts / scripts/schema.sql for magic_stats_owner).

Requires the PostgreSQL client tools (pg_dump) to be installed and either
on PATH or discoverable via the PG_BIN_DIR environment variable / the
--pg-bin-dir argument.

Usage:
    python scripts/backup_full_database.py
    python scripts/backup_full_database.py --database-url postgresql://user:pass@host/db
    python scripts/backup_full_database.py --pg-bin-dir "C:\\Program Files\\PostgreSQL\\18\\bin"
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime

from dotenv import load_dotenv


def find_pg_dump(pg_bin_dir: str | None) -> str:
    """Locate the pg_dump executable, preferring an explicit bin dir, then PATH."""
    candidates = []
    if pg_bin_dir:
        candidates.append(os.path.join(pg_bin_dir, "pg_dump.exe" if os.name == "nt" else "pg_dump"))

    env_bin_dir = os.environ.get("PG_BIN_DIR")
    if env_bin_dir:
        candidates.append(os.path.join(env_bin_dir, "pg_dump.exe" if os.name == "nt" else "pg_dump"))

    on_path = shutil.which("pg_dump")
    if on_path:
        candidates.append(on_path)

    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate

    print("ERROR: Could not find pg_dump. Install the PostgreSQL client tools and "
          "either add them to PATH, set PG_BIN_DIR, or pass --pg-bin-dir.")
    print("On Windows, the client tools typically live at:")
    print(r"  C:\Program Files\PostgreSQL\<version>\bin")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Source database URL. Defaults to DATABASE_URL from the environment/.env "
             "(the production database this project points at today).",
    )
    parser.add_argument(
        "--pg-bin-dir",
        default=None,
        help=r'Directory containing pg_dump (e.g. "C:\Program Files\PostgreSQL\18\bin"). '
             "Falls back to the PG_BIN_DIR env var, then PATH.",
    )
    parser.add_argument(
        "--output-dir",
        default="backups",
        help="Directory under which a timestamped backup folder is created. Default: backups/",
    )
    args = parser.parse_args()

    load_dotenv()

    db_url = args.database_url or os.environ.get("DATABASE_URL", "")
    db_url = db_url.replace("postgres://", "postgresql://")
    if not db_url:
        print("ERROR: No database URL provided and DATABASE_URL is not set in the environment.")
        sys.exit(1)

    pg_dump = find_pg_dump(args.pg_bin_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join(args.output_dir, f"full_{timestamp}")
    os.makedirs(backup_dir, exist_ok=True)
    dump_path = os.path.join(backup_dir, "database.dump")

    print(f"Backing up database to: {dump_path}")
    print("(This dumps the entire database: all schemas, tables, data, views, "
          "sequences, and constraints.)")

    # -F c: custom format — compressed, supports selective/parallel restore via pg_restore.
    # -v: verbose, so progress is visible for large databases.
    cmd = [
        pg_dump,
        "--format=custom",
        "--verbose",
        "--no-owner",       # skip 'OWNER TO <role>' statements — target role/user may differ
        "--no-privileges",  # skip GRANT/REVOKE statements tied to source-only roles
        "--file", dump_path,
        db_url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    # pg_dump writes its verbose progress to stderr even on success.
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print(f"\nERROR: pg_dump exited with status {result.returncode}")
        sys.exit(result.returncode)

    size_mb = os.path.getsize(dump_path) / (1024 * 1024)
    print(f"\nBackup complete: {dump_path} ({size_mb:.1f} MB)")
    print("Restore it with:")
    print(f"  python scripts/restore_full_database.py --dump-file \"{dump_path}\" "
          f"--database-url <target-database-url>")


if __name__ == "__main__":
    main()
