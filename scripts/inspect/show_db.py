# scripts/inspect/show_db.py
"""Inspect any table in the trading bot database.

Usage:
    python -m scripts.inspect.show_db --tables                     # list all tables
    python -m scripts.inspect.show_db --table funding_rates         # dump table
    python -m scripts.inspect.show_db --table signal_log --limit 5  # last 5 rows
    python -m scripts.inspect.show_db --table asset_registry --where "has_perps = 1"
"""
import argparse
import json

from utils.db import DataStore


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect trading bot database")
    parser.add_argument("--tables", action="store_true", help="List all tables")
    parser.add_argument("--table", type=str, help="Table name to dump")
    parser.add_argument("--limit", type=int, default=20, help="Max rows (default 20)")
    parser.add_argument("--where", type=str, default=None, help="SQL WHERE clause")
    parser.add_argument("--count", action="store_true", help="Show row count only")
    args = parser.parse_args(argv)

    with DataStore() as db:
        if args.tables:
            tables = db.list_tables()
            print("Tables in trading_bot.db:")
            for t in tables:
                count = db.fetchone(f"SELECT COUNT(*) as cnt FROM [{t}]")
                print(f"  {t:25s} {count['cnt']:>8d} rows")
            return

        if not args.table:
            parser.print_help()
            return

        table = args.table
        where = f" WHERE {args.where}" if args.where else ""

        if args.count:
            count = db.fetchone(f"SELECT COUNT(*) as cnt FROM [{table}]{where}")
            print(f"{table}: {count['cnt']} rows")
            return

        rows = db.fetchall(
            f"SELECT * FROM [{table}]{where} ORDER BY rowid DESC LIMIT ?",
            (args.limit,),
        )
        data = [dict(row) for row in rows]
        data.reverse()  # oldest first
        print(json.dumps(data, indent=2, default=str))
        print(f"\n({len(data)} rows shown, limit={args.limit})")


if __name__ == "__main__":
    main()
