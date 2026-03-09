"""
Query Graph — Branch-aware graph traversal

Traverses the relationship graph (SQLite) to find connected entities.

Usage:
    python tools/query_graph.py --client dfin --entity "audit-service" --direction out
    python tools/query_graph.py --client dfin --entity "rollout_k8s" --direction both --depth 2
    python tools/query_graph.py --client dfin --entity "kv_secret:automation-dev-dbauditservice" --branch develop
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _fuzzy_match(query: str, candidate: str) -> bool:
    """
    Check if query fuzzy-matches candidate.
    Handles partial matches, case-insensitive, ignoring separators.
    """
    q = query.lower().replace('-', '').replace('_', '').replace(' ', '')
    c = candidate.lower().replace('-', '').replace('_', '').replace(' ', '')

    if q in c or c in q:
        return True
    if q == c:
        return True

    # Check if query matches the last part of a namespaced ID
    parts = candidate.lower().split(':')
    for part in parts:
        clean = part.replace('-', '').replace('_', '')
        if q in clean:
            return True

    return False


def query_graph(
    client: str,
    entity: str,
    direction: str = "both",
    depth: int = 1,
    branch: str = None,
) -> dict:
    """
    Traverse the graph from an entity.

    Args:
        client: Client name.
        entity: Entity name or ID to start from.
        direction: "out" (outbound), "in" (inbound), or "both".
        depth: How many hops to traverse.
        branch: Optional branch filter.

    Returns:
        dict with keys:
            entity: str — the matched entity
            nodes: list[dict] — connected nodes with type and metadata
            edges: list[dict] — edges traversed
            depth_reached: int
    """
    db_path = PROJECT_ROOT / "memory" / client / "graph.sqlite"
    if not db_path.exists():
        return {"entity": entity, "nodes": [], "edges": [], "depth_reached": 0, "error": "Graph DB not found"}

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find matching nodes (exact or fuzzy)
    cursor.execute("SELECT id, node_type, file, repo FROM nodes")
    all_nodes = cursor.fetchall()

    matched_ids = []
    for node in all_nodes:
        if node["id"] == entity:
            matched_ids.append(node["id"])
        elif _fuzzy_match(entity, node["id"]):
            matched_ids.append(node["id"])

    if not matched_ids:
        conn.close()
        return {"entity": entity, "nodes": [], "edges": [], "depth_reached": 0, "error": "Entity not found"}

    # BFS traversal
    visited_nodes = set(matched_ids)
    visited_edges = []
    current_frontier = set(matched_ids)

    for d in range(depth):
        next_frontier = set()

        for node_id in current_frontier:
            # Outbound edges (source = node_id)
            if direction in ("out", "both"):
                query_str = "SELECT source, target, edge_type, file, repo, branch, metadata FROM edges WHERE source = ?"
                params = [node_id]
                if branch:
                    query_str += " AND (branch = ? OR branch = 'default')"
                    params.append(branch)

                cursor.execute(query_str, params)
                for row in cursor.fetchall():
                    edge = {
                        "source": row["source"],
                        "target": row["target"],
                        "edge_type": row["edge_type"],
                        "file": row["file"],
                        "repo": row["repo"],
                        "branch": row["branch"],
                    }
                    visited_edges.append(edge)
                    if row["target"] not in visited_nodes:
                        visited_nodes.add(row["target"])
                        next_frontier.add(row["target"])

            # Inbound edges (target = node_id)
            if direction in ("in", "both"):
                query_str = "SELECT source, target, edge_type, file, repo, branch, metadata FROM edges WHERE target = ?"
                params = [node_id]
                if branch:
                    query_str += " AND (branch = ? OR branch = 'default')"
                    params.append(branch)

                cursor.execute(query_str, params)
                for row in cursor.fetchall():
                    edge = {
                        "source": row["source"],
                        "target": row["target"],
                        "edge_type": row["edge_type"],
                        "file": row["file"],
                        "repo": row["repo"],
                        "branch": row["branch"],
                    }
                    visited_edges.append(edge)
                    if row["source"] not in visited_nodes:
                        visited_nodes.add(row["source"])
                        next_frontier.add(row["source"])

        current_frontier = next_frontier
        if not current_frontier:
            break

    # Collect node details
    result_nodes = []
    for node_id in visited_nodes:
        cursor.execute("SELECT id, node_type, file, repo FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if row:
            result_nodes.append({
                "id": row["id"],
                "node_type": row["node_type"],
                "file": row["file"],
                "repo": row["repo"],
            })
        else:
            result_nodes.append({"id": node_id, "node_type": "unknown", "file": "", "repo": ""})

    conn.close()

    # Deduplicate edges
    seen_edges = set()
    unique_edges = []
    for edge in visited_edges:
        key = (edge["source"], edge["target"], edge["edge_type"])
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(edge)

    return {
        "entity": entity,
        "matched_ids": matched_ids,
        "nodes": result_nodes,
        "edges": unique_edges,
        "depth_reached": depth,
    }


def main():
    parser = argparse.ArgumentParser(description="HiveMind Graph Query — traverse relationships")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--entity", required=True, help="Entity name or ID")
    parser.add_argument("--direction", default="both", choices=["out", "in", "both"], help="Traversal direction")
    parser.add_argument("--depth", type=int, default=1, help="Traversal depth")
    parser.add_argument("--branch", default=None, help="Branch filter")
    args = parser.parse_args()

    result = query_graph(
        client=args.client,
        entity=args.entity,
        direction=args.direction,
        depth=args.depth,
        branch=args.branch,
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        return

    print(f"Entity: {result['entity']}")
    print(f"Matched: {result.get('matched_ids', [])}")
    print(f"\nNodes ({len(result['nodes'])}):")
    for node in result['nodes']:
        print(f"  [{node['node_type']}] {node['id']} — {node['file']}")
    print(f"\nEdges ({len(result['edges'])}):")
    for edge in result['edges']:
        print(f"  {edge['source']} --{edge['edge_type']}--> {edge['target']}")


if __name__ == "__main__":
    main()

