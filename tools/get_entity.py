"""
Get Entity — Retrieve an entity's full profile from the graph

Returns all metadata, relationships, and references for a given entity.

Usage:
    python tools/get_entity.py --client dfin --name "audit-service"
    python tools/get_entity.py --client dfin --name "rollout_k8s" --branch develop
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_entity(client: str, name: str, branch: str = None) -> dict:
    """
    Look up an entity by name and return its full profile.

    Returns:
        dict with keys:
            entity: dict — node info (id, type, file, repo)
            outbound: list[dict] — edges where entity is source
            inbound: list[dict] — edges where entity is target
            related_files: list[str] — all files that reference this entity
    """
    db_path = PROJECT_ROOT / "memory" / client / "graph.sqlite"
    if not db_path.exists():
        return {"error": f"Graph DB not found at {db_path}"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find the entity — exact match first, then fuzzy
    cursor.execute("SELECT id, node_type, file, repo FROM nodes WHERE id = ?", (name,))
    row = cursor.fetchone()

    if not row:
        # Try LIKE match
        cursor.execute(
            "SELECT id, node_type, file, repo FROM nodes WHERE id LIKE ?",
            (f"%{name}%",),
        )
        rows = cursor.fetchall()
        if not rows:
            conn.close()
            return {"error": f"Entity '{name}' not found"}
        if len(rows) == 1:
            row = rows[0]
        else:
            # Return possible matches
            conn.close()
            return {
                "error": "Multiple matches",
                "candidates": [{"id": r["id"], "node_type": r["node_type"]} for r in rows],
            }

    entity = {
        "id": row["id"],
        "node_type": row["node_type"],
        "file": row["file"],
        "repo": row["repo"],
    }

    # Outbound edges
    query = "SELECT source, target, edge_type, file, repo, branch FROM edges WHERE source = ?"
    params = [entity["id"]]
    if branch:
        query += " AND (branch = ? OR branch IS NULL)"
        params.append(branch)
    cursor.execute(query, params)
    outbound = [dict(r) for r in cursor.fetchall()]

    # Inbound edges
    query = "SELECT source, target, edge_type, file, repo, branch FROM edges WHERE target = ?"
    params = [entity["id"]]
    if branch:
        query += " AND (branch = ? OR branch IS NULL)"
        params.append(branch)
    cursor.execute(query, params)
    inbound = [dict(r) for r in cursor.fetchall()]

    # Collect all related files
    related_files = set()
    if entity["file"]:
        related_files.add(entity["file"])
    for edge in outbound + inbound:
        if edge.get("file"):
            related_files.add(edge["file"])

    conn.close()

    return {
        "entity": entity,
        "outbound": outbound,
        "inbound": inbound,
        "related_files": sorted(related_files),
    }


def main():
    parser = argparse.ArgumentParser(description="HiveMind Get Entity — look up entity profile")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--name", required=True, help="Entity name or ID")
    parser.add_argument("--branch", default=None, help="Branch filter")
    args = parser.parse_args()

    result = get_entity(client=args.client, name=args.name, branch=args.branch)

    if result.get("error"):
        if result.get("candidates"):
            print(f"Multiple matches for '{args.name}':")
            for c in result["candidates"]:
                print(f"  [{c['node_type']}] {c['id']}")
        else:
            print(f"Error: {result['error']}")
        return

    ent = result["entity"]
    print(f"Entity: {ent['id']}")
    print(f"Type:   {ent['node_type']}")
    print(f"File:   {ent['file']}")
    print(f"Repo:   {ent['repo']}")

    if result["outbound"]:
        print(f"\nOutbound ({len(result['outbound'])}):")
        for e in result["outbound"]:
            print(f"  --{e['edge_type']}--> {e['target']}")

    if result["inbound"]:
        print(f"\nInbound ({len(result['inbound'])}):")
        for e in result["inbound"]:
            print(f"  {e['source']} --{e['edge_type']}--> (this)")

    if result["related_files"]:
        print(f"\nRelated files ({len(result['related_files'])}):")
        for f in result["related_files"]:
            print(f"  {f}")


if __name__ == "__main__":
    main()

