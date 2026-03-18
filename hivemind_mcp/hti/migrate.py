"""HTI Schema Migration — Apply HTI tables to SQLite database.

Usage:
    python hivemind_mcp/hti/migrate.py --client dfin
    python hivemind_mcp/hti/migrate.py --client dfin --verify
"""

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from hivemind_mcp.hti.utils import get_hti_db_path


def migrate(client: str, project_root: Path = None) -> dict:
    """Apply HTI schema to the client's hti.sqlite database.

    Returns dict with migration results.
    """
    root = project_root or PROJECT_ROOT
    db_path = get_hti_db_path(client, root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text(encoding="utf-8")

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Check existing tables before migration
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    existing_before = [row[0] for row in cursor.fetchall()]

    # Apply schema
    conn.executescript(schema_sql)

    # Check tables after migration
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    existing_after = [row[0] for row in cursor.fetchall()]

    conn.close()

    created = [t for t in existing_after if t not in existing_before]

    return {
        "client": client,
        "db_path": str(db_path),
        "tables_before": existing_before,
        "tables_after": existing_after,
        "tables_created": created,
        "hti_tables_present": "hti_skeletons" in existing_after and "hti_nodes" in existing_after,
    }


def verify(client: str, project_root: Path = None) -> dict:
    """Verify HTI schema exists and is correct."""
    root = project_root or PROJECT_ROOT
    db_path = get_hti_db_path(client, root)

    if not db_path.exists():
        return {"ok": False, "error": f"Database not found: {db_path}"}

    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]

    # Check for required tables
    required = ["hti_skeletons", "hti_nodes"]
    missing = [t for t in required if t not in tables]

    # Check column counts
    checks = {}
    for table in required:
        if table in tables:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            cols = [row[1] for row in cursor.fetchall()]
            checks[table] = {"columns": cols, "ok": len(cols) > 0}

    conn.close()

    return {
        "ok": len(missing) == 0,
        "tables": tables,
        "missing_tables": missing,
        "table_checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="HTI Schema Migration")
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--verify", action="store_true", help="Verify schema only")
    args = parser.parse_args()

    if args.verify:
        result = verify(args.client)
        if result["ok"]:
            print(f"[OK] HTI schema verified for client '{args.client}'")
            for table, info in result.get("table_checks", {}).items():
                print(f"  {table}: {len(info['columns'])} columns")
        else:
            print(f"[FAIL] {result.get('error', 'Missing tables: ' + ', '.join(result.get('missing_tables', [])))}")
            sys.exit(1)
    else:
        result = migrate(args.client)
        print(f"[OK] Migration complete for client '{result['client']}'")
        print(f"  Database: {result['db_path']}")
        print(f"  Tables created: {result['tables_created'] or 'none (already existed)'}")
        print(f"  All HTI tables present: {result['hti_tables_present']}")


if __name__ == "__main__":
    main()
