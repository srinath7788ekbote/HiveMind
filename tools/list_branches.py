"""
List Branches — List branches for a repo with tier classification

Shows all branches, their tiers, last activity, and indexing status.

Usage:
    python tools/list_branches.py --client dfin --repo Eastwood-terraform
    python tools/list_branches.py --client dfin --repo all
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def list_branches(client: str, repo: str = "all") -> list:
    """
    List branches for a repo (or all repos) with metadata.

    Args:
        client: Client name.
        repo: Repository name, or "all" for all repos.

    Returns:
        list[dict] with branch info per repo.
    """
    from ingest.branch_indexer import classify_branch_tier, BranchIndex
    from sync.git_utils import get_branches, get_last_commit_time

    config = _load_config(client)
    if not config:
        return [{"error": "Client config not found"}]

    branch_index = BranchIndex(PROJECT_ROOT / "memory" / client / "branch_index.json")
    results = []

    for repo_cfg in config.get("repos", []):
        repo_name = repo_cfg.get("name", "")
        if repo != "all" and repo_name != repo:
            continue

        repo_path = Path(repo_cfg.get("path", ""))
        if not repo_path.exists():
            results.append({
                "repo": repo_name,
                "error": f"Path not found: {repo_path}",
                "branches": [],
            })
            continue

        branches = get_branches(str(repo_path))
        branch_list = []

        for branch_name in branches:
            tier = classify_branch_tier(branch_name)
            last_commit = get_last_commit_time(str(repo_path), branch_name)
            indexed = branch_index.is_indexed(repo_name, branch_name)

            branch_list.append({
                "name": branch_name,
                "tier": tier,
                "last_commit": last_commit,
                "indexed": indexed,
            })

        # Sort: production first, then by tier, then alphabetically
        tier_order = {"production": 0, "staging": 1, "integration": 2, "development": 3, "feature": 4, "unknown": 5}
        branch_list.sort(key=lambda b: (tier_order.get(b["tier"], 5), b["name"]))

        results.append({
            "repo": repo_name,
            "path": str(repo_path),
            "total_branches": len(branch_list),
            "branches": branch_list,
        })

    return results


def _load_config(client: str) -> dict:
    """Load client repos config."""
    config_path = PROJECT_ROOT / "clients" / client / "repos.yaml"
    if not config_path.exists():
        return {}

    content = config_path.read_text(encoding="utf-8")

    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass

    config = {"repos": []}
    current_repo = None

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- name:"):
            current_repo = {"name": stripped.split(":", 1)[1].strip().strip('"\"')}
            config["repos"].append(current_repo)
        elif current_repo and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"\"')
            if key == "path":
                current_repo["path"] = val
            elif key == "type":
                current_repo["type"] = val

    return config


def main():
    parser = argparse.ArgumentParser(description="HiveMind List Branches")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--repo", default="all", help="Repository name or 'all'")
    args = parser.parse_args()

    results = list_branches(client=args.client, repo=args.repo)

    for repo_info in results:
        if repo_info.get("error"):
            print(f"[{repo_info['repo']}] Error: {repo_info['error']}")
            continue

        print(f"\n{repo_info['repo']} ({repo_info['total_branches']} branches)")
        print(f"  Path: {repo_info['path']}")
        print()

        for b in repo_info["branches"]:
            idx_mark = "✓" if b["indexed"] else "·"
            commit_str = b["last_commit"] if b["last_commit"] else "unknown"
            print(f"  {idx_mark} [{b['tier']:12s}] {b['name']:40s} {commit_str}")


if __name__ == "__main__":
    main()

