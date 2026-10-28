"""Import a player's card collection from a CSV export into the LOCAL database.

Reads a collection CSV (header:
`Quantity,Name,Finish,Condition,Date Added,Language,Purchase Price,Tags,
Edition Name,Edition Code,Multiverse Id,Scryfall ID,Collector Number`),
collapses identical entries into counts (same printing + finish + condition +
language), resolves each to a card in our DB, and writes player_collection rows.

SAFETY
------
This script WRITES to the database, so per the project's database-safety rule it
targets LOCAL_DATABASE_URL ONLY. It deliberately refuses to fall back to, or run
against, DATABASE_URL (production). To apply a collection to production, a
maintainer must run it explicitly against a local DB and promote the result
through the normal backup/restore path — this script will never write to prod.

Usage:
    python scripts/import_player_collection.py --player-id 1 --csv path/to/collection.csv

    # Merge into (rather than replace) the player's existing collection:
    python scripts/import_player_collection.py --player-id 1 --csv coll.csv --merge

    # Parse and report the collapse WITHOUT writing anything:
    python scripts/import_player_collection.py --player-id 1 --csv coll.csv --dry-run
"""

import argparse
import os
import sys

# Make the project root importable when this script is run directly from the
# scripts/ directory (so `import app` / `import config` resolve).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv


def _build_local_config(db_url: str):
    """Return a Config subclass pointed at the LOCAL database URL."""
    from config import Config

    class LocalImportConfig(Config):
        SQLALCHEMY_DATABASE_URI = db_url

    return LocalImportConfig


def _resolve_local_url() -> str:
    """Resolve LOCAL_DATABASE_URL and refuse anything that looks like prod."""
    load_dotenv()

    db_url = os.environ.get("LOCAL_DATABASE_URL", "").replace(
        "postgres://", "postgresql://"
    )
    if not db_url:
        print(
            "ERROR: LOCAL_DATABASE_URL is not set. Writes are only allowed "
            "against the local database. Refusing to fall back to DATABASE_URL "
            "(production).",
            file=sys.stderr,
        )
        sys.exit(1)

    prod_url = os.environ.get("DATABASE_URL", "").replace(
        "postgres://", "postgresql://"
    )
    if prod_url and db_url == prod_url:
        print(
            "ERROR: LOCAL_DATABASE_URL matches DATABASE_URL (production). "
            "Refusing to write to production. Point LOCAL_DATABASE_URL at a "
            "local database instead.",
            file=sys.stderr,
        )
        sys.exit(1)

    return db_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--player-id", type=int, required=True,
                        help="players.id the collection belongs to.")
    parser.add_argument("--csv", required=True,
                        help="Path to the collection CSV export.")
    parser.add_argument("--merge", action="store_true",
                        help="Merge into the existing collection instead of "
                             "replacing it (adds counts to matching entries).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and report the collapse without writing or "
                             "touching the database.")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"ERROR: CSV file not found: {args.csv}", file=sys.stderr)
        sys.exit(1)

    # --- Dry run: parse only, no DB connection at all. --------------------
    if args.dry_run:
        from app.services.collection_service import parse_collection_csv

        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            try:
                entries, result = parse_collection_csv(fh)
            except ValueError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)

        print("DRY RUN — no database changes made. (Printing matches are only "
              "checked during a real import against the database.)")
        _print_summary(result, dry_run=True)
        print("\nCollapsed entries:")
        for e in entries:
            print(f"  {e.count:>4}x  {e.name}  [{e.set_code}#{e.collector_number}] "
                  f"{e.finish}/{e.condition}/{e.language}  ({e.scryfall_id})")
        return

    # --- Real import: LOCAL DB only. --------------------------------------
    db_url = _resolve_local_url()

    from app import create_app, db
    from app.services.collection_service import import_player_collection

    app = create_app(_build_local_config(db_url))

    with app.app_context():
        from app.models import Player

        player = db.session.get(Player, args.player_id)
        if player is None:
            print(f"ERROR: No player with id {args.player_id} in the local "
                  f"database.", file=sys.stderr)
            sys.exit(1)

        with open(args.csv, newline="", encoding="utf-8-sig") as fh:
            try:
                result = import_player_collection(
                    args.player_id, fh, replace=not args.merge
                )
            except ValueError as exc:
                db.session.rollback()
                print(f"ERROR: {exc}", file=sys.stderr)
                sys.exit(1)
            except Exception:
                db.session.rollback()
                raise

        db.session.commit()

        print(f"Imported collection for player {args.player_id} "
              f"({player.name}) — mode: {'merge' if args.merge else 'replace'}.")
        _print_summary(result)
        _print_unimported(result)


def _print_summary(result, *, dry_run: bool = False) -> None:
    print(f"  rows read:         {result.rows_read}")
    print(f"  rows skipped:      {result.rows_skipped}")
    print(f"  distinct entries:  {result.distinct_entries}")
    print(f"  total quantity:    {result.total_quantity}")
    if not dry_run:
        print(f"  imported:          {result.imported}")
        print(f"  not imported:      {len(result.unimported)}")
    if result.skipped_reasons:
        print("  skipped rows (no Scryfall ID / non-positive quantity):")
        for reason in result.skipped_reasons:
            print(f"    - {reason}")


def _print_unimported(result) -> None:
    """List entries left out because their exact printing isn't in our DB."""
    if not result.unimported:
        print("\nAll matched entries were imported — no printings were missing.")
        return
    print(f"\n{len(result.unimported)} entr"
          f"{'y was' if len(result.unimported) == 1 else 'ies were'} NOT imported "
          f"(exact Scryfall printing not found in the card database):")
    for e in result.unimported:
        print(f"  {e.count:>4}x  {e.name}  [{e.set_code}#{e.collector_number}] "
              f"{e.finish}/{e.condition}/{e.language}  ({e.scryfall_id})")
    print("\nThese were left untouched — no substitute printing was recorded. "
          "If a printing is missing, run the nightly card fetch so it is ingested, "
          "then re-import.")


if __name__ == "__main__":
    main()
