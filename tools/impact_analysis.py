"""
Impact Analysis — Determine blast radius of a change

Given a changed file or entity, traces all downstream dependencies
to show what would be affected by the change.

Usage:
    python tools/impact_analysis.py --client dfin --file "layer_01_keyvaults/main.tf" --repo Eastwood-terraform
    python tools/impact_analysis.py --client dfin --entity "audit-service" --branch main
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def impact_analysis(
    client: str,
    file: str = None,
    entity: str = None,
    repo: str = None,
    branch: str = None,
    depth: int = 3,
) -> dict:
    """
    Analyze impact/blast radius of a change.

    Args:
        client: Client name.
        file: Changed file path (within repo).
        entity: Changed entity name.
        repo: Repository name.
        branch: Branch context.
        depth: How deep to trace dependencies.

    Returns:
        dict with:
            source: str — what changed
            affected_entities: list[dict]
            affected_files: list[str]
            affected_services: list[str]
            affected_environments: list[str]
            risk_level: str — low/medium/high/critical
            summary: str
    """
    result = {
        "source": file or entity or "unknown",
        "affected_entities": [],
        "affected_files": [],
        "affected_services": [],
        "affected_environments": [],
        "risk_level": "low",
        "summary": "",
    }

    db_path = PROJECT_ROOT / "memory" / client / "graph.sqlite"
    if not db_path.exists():
        result["summary"] = "Graph DB not found — cannot perform impact analysis"
        return result

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Step 1: Find starting nodes
    seed_nodes = set()

    if file:
        cursor.execute("SELECT id, node_type FROM nodes WHERE file LIKE ?", (f"%{file}%",))
        for row in cursor.fetchall():
            seed_nodes.add(row["id"])

        # Also find edges from this file
        cursor.execute("SELECT source, target FROM edges WHERE file LIKE ?", (f"%{file}%",))
        for row in cursor.fetchall():
            seed_nodes.add(row["source"])
            seed_nodes.add(row["target"])

    if entity:
        cursor.execute("SELECT id FROM nodes WHERE id LIKE ?", (f"%{entity}%",))
        for row in cursor.fetchall():
            seed_nodes.add(row["id"])

    if not seed_nodes:
        conn.close()
        # Fallback: search entities.json for matching entities
        entities_path = PROJECT_ROOT / "memory" / client / "entities.json"
        if entities_path.exists():
            fallback = _search_entities_json(entities_path, file, entity)
            if fallback:
                result["affected_entities"] = fallback["entities"]
                result["affected_files"] = fallback["files"]
                result["affected_services"] = fallback["services"]
                result["risk_level"] = _assess_risk(result)
                result["summary"] = _build_summary(result)
                return result
        result["summary"] = f"No entities found for '{file or entity}'"
        return result

    # Step 2: BFS to find all downstream impact
    visited = set(seed_nodes)
    frontier = set(seed_nodes)
    all_edges = []

    for d in range(depth):
        next_frontier = set()
        for node_id in frontier:
            # Find everything that depends on this node (inbound = things that reference this)
            query = "SELECT source, target, edge_type, file, repo, branch FROM edges WHERE target = ?"
            params = [node_id]
            if branch:
                query += " AND (branch = ? OR branch IS NULL)"
                params.append(branch)

            cursor.execute(query, params)
            for row in cursor.fetchall():
                edge = dict(row)
                all_edges.append(edge)
                if edge["source"] not in visited:
                    visited.add(edge["source"])
                    next_frontier.add(edge["source"])

            # Also check outbound for propagation
            query = "SELECT source, target, edge_type, file, repo, branch FROM edges WHERE source = ?"
            params = [node_id]
            if branch:
                query += " AND (branch = ? OR branch IS NULL)"
                params.append(branch)

            cursor.execute(query, params)
            for row in cursor.fetchall():
                edge = dict(row)
                all_edges.append(edge)
                if edge["target"] not in visited:
                    visited.add(edge["target"])
                    next_frontier.add(edge["target"])

        frontier = next_frontier
        if not frontier:
            break

    # Step 3: Categorize affected entities
    affected_files = set()
    affected_services = set()
    affected_envs = set()

    for node_id in visited:
        cursor.execute("SELECT id, node_type, file, repo FROM nodes WHERE id = ?", (node_id,))
        row = cursor.fetchone()
        if row:
            entity_info = {
                "id": row["id"],
                "node_type": row["node_type"],
                "file": row["file"],
                "repo": row["repo"],
            }
            result["affected_entities"].append(entity_info)

            if row["file"]:
                affected_files.add(row["file"])

            # Classify by type
            node_type = (row["node_type"] or "").lower()
            node_id_lower = row["id"].lower()
            if "service" in node_type or "service" in node_id_lower:
                affected_services.add(row["id"])
            if "environment" in node_type or "env" in node_id_lower:
                affected_envs.add(row["id"])

    for edge in all_edges:
        if edge.get("file"):
            affected_files.add(edge["file"])

    conn.close()

    result["affected_files"] = sorted(affected_files)
    result["affected_services"] = sorted(affected_services)
    result["affected_environments"] = sorted(affected_envs)

    # Step 4: Determine risk level
    result["risk_level"] = _assess_risk(result)

    # Step 5: Build summary
    result["summary"] = _build_summary(result)

    return result


def _search_entities_json(entities_path: Path, file: str = None, entity: str = None) -> dict | None:
    """Fallback: search entities.json when graph.sqlite has no matching nodes."""
    try:
        with open(entities_path, "r", encoding="utf-8") as f:
            entities = json.load(f)
    except Exception:
        return None

    if isinstance(entities, dict):
        entity_list = []
        for v in entities.values():
            if isinstance(v, list):
                entity_list.extend(v)
    elif isinstance(entities, list):
        entity_list = entities
    else:
        return None

    search_term = (file or entity or "").lower()
    if not search_term:
        return None

    matched = []
    matched_files = set()
    matched_services = set()
    seen = set()

    for ent in entity_list:
        ent_name = (ent.get("name", "") or "").lower()
        ent_file = (ent.get("file", "") or "").lower()
        ent_type = (ent.get("type", "") or "").lower()

        if search_term in ent_name or search_term in ent_file:
            # Deduplicate by (name, type, file) tuple
            dedup_key = (ent.get("name", ""), ent.get("type", ""), ent.get("file", ""))
            if dedup_key not in seen:
                seen.add(dedup_key)
                matched.append({
                    "id": ent.get("name", ""),
                    "node_type": ent.get("type", ""),
                    "file": ent.get("file", ""),
                    "repo": ent.get("repo", ""),
                })
                if ent.get("file"):
                    matched_files.add(ent["file"])
                if "service" in ent_type or "svc" in ent_type:
                    matched_services.add(ent.get("name", ""))

    if not matched:
        return None

    return {
        "entities": matched,
        "files": sorted(matched_files),
        "services": sorted(matched_services),
    }


def _assess_risk(result: dict) -> str:
    """Assess risk level based on blast radius."""
    num_entities = len(result["affected_entities"])
    num_files = len(result["affected_files"])
    num_services = len(result["affected_services"])
    has_prod = any("prod" in e.lower() for e in result["affected_environments"])

    if has_prod and num_services > 2:
        return "critical"
    if has_prod or num_services > 3:
        return "high"
    if num_entities > 10 or num_files > 5:
        return "medium"
    return "low"


def _build_summary(result: dict) -> str:
    """Build human-readable impact summary."""
    source = result["source"]
    risk = result["risk_level"]
    parts = [
        f"Impact analysis for '{source}':",
        f"  Risk level: {risk.upper()}",
        f"  Affected entities: {len(result['affected_entities'])}",
        f"  Affected files: {len(result['affected_files'])}",
    ]

    if result["affected_services"]:
        parts.append(f"  Services impacted: {', '.join(result['affected_services'])}")

    if result["affected_environments"]:
        parts.append(f"  Environments impacted: {', '.join(result['affected_environments'])}")

    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="HiveMind Impact Analysis — blast radius assessment")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--file", default=None, help="Changed file path")
    parser.add_argument("--entity", default=None, help="Changed entity name")
    parser.add_argument("--repo", default=None, help="Repository name")
    parser.add_argument("--branch", default=None, help="Branch context")
    parser.add_argument("--depth", type=int, default=3, help="Traversal depth")
    args = parser.parse_args()

    if not args.file and not args.entity:
        print("Error: Provide --file or --entity")
        return

    result = impact_analysis(
        client=args.client,
        file=args.file,
        entity=args.entity,
        repo=args.repo,
        branch=args.branch,
        depth=args.depth,
    )

    print(result["summary"])

    if result["affected_files"]:
        print(f"\n--- Affected Files ({len(result['affected_files'])}) ---")
        for f in result["affected_files"]:
            print(f"  {f}")

    if result["affected_entities"]:
        print(f"\n--- Affected Entities ({len(result['affected_entities'])}) ---")
        for e in result["affected_entities"]:
            print(f"  [{e['node_type']}] {e['id']}")


if __name__ == "__main__":
    main()

