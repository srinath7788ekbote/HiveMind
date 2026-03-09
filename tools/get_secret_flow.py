"""
Get Secret Flow — Trace a secret from creation through mounting

Traces the complete lifecycle of a secret:
  1. Where it's created (Terraform azurerm_key_vault_secret)
  2. Where it's read (data sources)
  3. Where it's mounted (Kubernetes secret, Helm values)
  4. Which services consume it

Usage:
    python tools/get_secret_flow.py --client dfin --secret "automation-dev-dbauditservice"
    python tools/get_secret_flow.py --client dfin --secret "dbauditservice" --branch develop
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_secret_flow(client: str, secret: str, branch: str = None) -> dict:
    """
    Trace a secret's full lifecycle through the infrastructure.

    Args:
        client: Client name.
        secret: Secret name (full or partial).
        branch: Optional branch filter.

    Returns:
        dict with:
            secret: str — matched secret name
            creation: list — where it's created (TF resources)
            reads: list — where it's read (data sources)
            k8s_mounts: list — Kubernetes secret objects
            helm_mounts: list — Helm value references
            consuming_services: list — services that use it
            flow_summary: str — human-readable summary
    """
    result = {
        "secret": secret,
        "creation": [],
        "reads": [],
        "k8s_mounts": [],
        "helm_mounts": [],
        "consuming_services": [],
        "flow_summary": "",
    }

    # Check graph database first
    db_path = PROJECT_ROOT / "memory" / client / "graph.sqlite"
    if db_path.exists():
        _trace_from_graph(db_path, secret, branch, result)

    # Supplement from entities.json
    entities_path = PROJECT_ROOT / "memory" / client / "entities.json"
    if entities_path.exists():
        _trace_from_entities(entities_path, secret, result)

    # Supplement from profile
    profile_path = PROJECT_ROOT / "memory" / client / "discovered_profile.json"
    if profile_path.exists():
        _trace_from_profile(profile_path, secret, result)

    # Build summary
    result["flow_summary"] = _build_summary(result)

    return result


def _trace_from_graph(db_path: Path, secret: str, branch: str, result: dict):
    """Trace secret through the graph database edges."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find edges involving this secret
    query = """
        SELECT source, target, edge_type, file, repo, branch
        FROM edges
        WHERE (source LIKE ? OR target LIKE ?)
    """
    params = [f"%{secret}%", f"%{secret}%"]

    if branch:
        query += " AND (branch = ? OR branch IS NULL)"
        params.append(branch)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    for row in rows:
        edge = dict(row)

        if edge["edge_type"] == "CREATES_KV_SECRET":
            result["creation"].append({
                "resource": edge["source"],
                "secret": edge["target"],
                "file": edge["file"],
                "repo": edge["repo"],
            })
        elif edge["edge_type"] == "READS_KV_SECRET":
            result["reads"].append({
                "resource": edge["source"],
                "secret": edge["target"],
                "file": edge["file"],
                "repo": edge["repo"],
            })
        elif edge["edge_type"] == "CREATES_K8S_SECRET":
            result["k8s_mounts"].append({
                "resource": edge["source"],
                "secret": edge["target"],
                "file": edge["file"],
                "repo": edge["repo"],
            })
        elif edge["edge_type"] == "MOUNTS_SECRET":
            result["helm_mounts"].append({
                "resource": edge["source"],
                "secret": edge["target"],
                "file": edge["file"],
                "repo": edge["repo"],
            })
        elif edge["edge_type"] == "USES_SERVICE":
            if secret.lower() in edge["target"].lower() or secret.lower() in edge["source"].lower():
                svc_name = edge["target"]
                existing = {cs.get("service", "") for cs in result["consuming_services"]}
                if svc_name not in existing:
                    result["consuming_services"].append({
                        "service": svc_name,
                        "pipeline": edge["source"],
                        "file": edge["file"],
                    })

    conn.close()


def _trace_from_entities(entities_path: Path, secret: str, result: dict):
    """Supplement trace from entities.json."""
    with open(entities_path, "r", encoding="utf-8") as f:
        entities = json.load(f)

    # entities.json is a flat list of dicts: [{"name":..., "type":..., "file":..., "repo":..., "branch":...}, ...]
    if isinstance(entities, dict):
        # Legacy dict-with-sections format
        entity_list = entities.get("secrets", []) + entities.get("services", []) + entities.get("entities", [])
    elif isinstance(entities, list):
        entity_list = entities
    else:
        entity_list = []

    for ent in entity_list:
        ent_name = ent.get("name", "")
        ent_type = (ent.get("type", "") or "").lower()
        ent_file = ent.get("file", "")

        # Match secret name in entity name or file path
        if secret.lower() not in ent_name.lower() and secret.lower() not in ent_file.lower():
            continue

        # Legacy dict format: entities with "service" key → consuming service link
        if ent.get("service"):
            existing_svcs = {cs.get("service", "") for cs in result["consuming_services"]}
            if ent["service"] not in existing_svcs:
                result["consuming_services"].append({
                    "service": ent["service"],
                    "source": "entities",
                })

        # Secret-type entities → creation evidence
        if ent_type in ("kv_secret", "kv_data_source", "secret"):
            existing_files = {c.get("file", "") for c in result["creation"]}
            if ent_file not in existing_files:
                result["creation"].append({
                    "resource": ent_name,
                    "secret": ent_name,
                    "file": ent_file,
                    "repo": ent.get("repo", ""),
                    "source": "entities",
                })
        elif ent_type in ("k8s_secret",):
            existing_files = {m.get("file", "") for m in result["k8s_mounts"]}
            if ent_file not in existing_files:
                result["k8s_mounts"].append({
                    "resource": ent_name,
                    "secret": ent_name,
                    "file": ent_file,
                    "repo": ent.get("repo", ""),
                    "source": "entities",
                })
        elif ent_type in ("harness_svc", "service", "helm_chart"):
            existing_svcs = {cs.get("service", "") for cs in result["consuming_services"]}
            if ent_name not in existing_svcs:
                result["consuming_services"].append({
                    "service": ent_name,
                    "file": ent_file,
                    "source": "entities",
                })
        else:
            # Generic match — add as related file
            existing_files = {c.get("file", "") for c in result.get("related_files", [])}
            if "related_files" not in result:
                result["related_files"] = []
            if ent_file not in existing_files:
                result["related_files"].append({
                    "name": ent_name,
                    "type": ent_type,
                    "file": ent_file,
                    "repo": ent.get("repo", ""),
                    "source": "entities",
                })


def _trace_from_profile(profile_path: Path, secret: str, result: dict):
    """Supplement trace from discovered_profile.json."""
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = json.load(f)
    except (json.JSONDecodeError, OSError):
        return

    if not isinstance(profile, dict):
        return

    # Check secrets discovery
    secrets_info = profile.get("secrets", {})

    kv_secrets = secrets_info.get("kv_secrets", [])
    for kv in kv_secrets:
        if secret.lower() in kv.get("name", "").lower():
            if kv not in result["creation"]:
                result["creation"].append({
                    "resource": kv.get("resource", "unknown"),
                    "secret": kv.get("name", ""),
                    "file": kv.get("file", ""),
                    "repo": kv.get("repo", ""),
                    "source": "profile",
                })

    k8s_secrets = secrets_info.get("k8s_secrets", [])
    for ks in k8s_secrets:
        kv_refs = ks.get("kv_refs", [])
        for ref in kv_refs:
            if secret.lower() in ref.lower():
                if ks not in result["k8s_mounts"]:
                    result["k8s_mounts"].append({
                        "resource": ks.get("name", ""),
                        "secret": ref,
                        "file": ks.get("file", ""),
                        "source": "profile",
                    })

    helm_secrets = secrets_info.get("helm_mounts", [])
    for hs in helm_secrets:
        if secret.lower() in (hs.get("secretName") or "").lower() or secret.lower() in (hs.get("secretKeyRef") or "").lower():
            if hs not in result["helm_mounts"]:
                result["helm_mounts"].append({
                    "resource": hs.get("container", ""),
                    "secret": hs.get("secretName", hs.get("secretKeyRef", "")),
                    "file": hs.get("file", ""),
                    "source": "profile",
                })


def _build_summary(result: dict) -> str:
    """Build human-readable flow summary."""
    parts = []
    secret = result["secret"]

    if result["creation"]:
        creators = [c.get("file", "unknown") for c in result["creation"]]
        parts.append(f"CREATED in: {', '.join(creators)}")

    if result["reads"]:
        readers = [r.get("file", "unknown") for r in result["reads"]]
        parts.append(f"READ by: {', '.join(readers)}")

    if result["k8s_mounts"]:
        k8s = [m.get("resource", "unknown") for m in result["k8s_mounts"]]
        parts.append(f"MOUNTED as K8s Secret: {', '.join(k8s)}")

    if result["helm_mounts"]:
        helms = [h.get("file", "unknown") for h in result["helm_mounts"]]
        parts.append(f"HELM mount in: {', '.join(helms)}")

    if result["consuming_services"]:
        svcs = list(set(s.get("service", "unknown") for s in result["consuming_services"]))
        parts.append(f"CONSUMED by services: {', '.join(svcs)}")

    if not parts:
        return f"No flow trace found for secret '{secret}'"

    return f"Secret '{secret}' flow:\n  " + "\n  ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="HiveMind Get Secret Flow — trace secret lifecycle")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--secret", required=True, help="Secret name (full or partial)")
    parser.add_argument("--branch", default=None, help="Branch filter")
    args = parser.parse_args()

    result = get_secret_flow(client=args.client, secret=args.secret, branch=args.branch)

    print(result["flow_summary"])

    if result["creation"]:
        print(f"\n--- Creation ({len(result['creation'])}) ---")
        for c in result["creation"]:
            print(f"  {c.get('repo', '')}/{c.get('file', '')} — {c.get('resource', '')}")

    if result["reads"]:
        print(f"\n--- Reads ({len(result['reads'])}) ---")
        for r in result["reads"]:
            print(f"  {r.get('repo', '')}/{r.get('file', '')} — {r.get('resource', '')}")

    if result["k8s_mounts"]:
        print(f"\n--- K8s Mounts ({len(result['k8s_mounts'])}) ---")
        for m in result["k8s_mounts"]:
            print(f"  {m.get('file', '')} — {m.get('resource', '')}")

    if result["helm_mounts"]:
        print(f"\n--- Helm Mounts ({len(result['helm_mounts'])}) ---")
        for h in result["helm_mounts"]:
            print(f"  {h.get('file', '')} — {h.get('resource', '')}")

    if result["consuming_services"]:
        print(f"\n--- Consuming Services ({len(result['consuming_services'])}) ---")
        for s in result["consuming_services"]:
            print(f"  {s.get('service', '')}")


if __name__ == "__main__":
    main()

