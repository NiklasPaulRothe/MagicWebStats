"""
Full database backup script.

Exports all tables in the data_owner schema to JSON files,
stored in a timestamped folder under backups/.

Usage:
    python scripts/backup_database.py
"""

import json
import os
import sys
from datetime import datetime, date
from decimal import Decimal

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv


def json_serializer(obj):
    """Handle date/datetime/Decimal serialization for JSON."""
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def get_all_tables(cur, schema="data_owner"):
    """Get all table names in the given schema."""
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, (schema,))
    return [row[0] for row in cur.fetchall()]


def export_table(cur, schema, table_name):
    """Export all rows from a table as a list of dicts."""
    cur.execute(f'SELECT * FROM {schema}."{table_name}"')
    columns = [desc[0] for desc in cur.description]
    rows = cur.fetchall()
    return [dict(zip(columns, row)) for row in rows]


def main():
    load_dotenv()

    db_url = os.environ.get("DATABASE_URL", "").replace("postgres://", "postgresql://")
    if not db_url:
        print("ERROR: DATABASE_URL not set in environment.")
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    cur = conn.cursor()

    schema = "data_owner"
    tables = get_all_tables(cur, schema)
    print(f"Found {len(tables)} tables in schema '{schema}'")

    # Create backup directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = os.path.join("backups", timestamp)
    os.makedirs(backup_dir, exist_ok=True)

    total_rows = 0
    for table_name in tables:
        rows = export_table(cur, schema, table_name)
        total_rows += len(rows)

        filepath = os.path.join(backup_dir, f"{table_name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(rows, f, default=json_serializer, ensure_ascii=False, indent=2)

        print(f"  {table_name}: {len(rows)} rows")

    cur.close()
    conn.close()

    # Write a small manifest
    manifest = {
        "timestamp": timestamp,
        "schema": schema,
        "tables": {t: len(export_table(psycopg2.connect(db_url).cursor(), schema, t))
                   for t in []},  # already exported, just record names
        "table_names": tables,
        "total_rows": total_rows,
    }
    manifest_path = os.path.join(backup_dir, "_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, default=json_serializer, ensure_ascii=False, indent=2)

    print(f"\nBackup complete: {backup_dir}")
    print(f"Total: {len(tables)} tables, {total_rows} rows")


if __name__ == "__main__":
    main()
