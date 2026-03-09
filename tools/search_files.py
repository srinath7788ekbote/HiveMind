"""
Search Files — Search indexed files by name, type, path patterns

Usage:
    python tools/search_files.py --client dfin --query "pipeline" --type pipeline
    python tools/search_files.py --client dfin --query "values" --repo Eastwood-helm
    python tools/search_files.py --client dfin --query "layer_01" --branch main
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def search_files(
    client: str,
    query: str = "",
    file_type: str = None,
    repo: str = None,
    branch: str = None,
    limit: int = 25,
) -> list:
    """
    Search through indexed file classifications to find files matching criteria.

    Args:
        client: Client name.
        query: Search string (matches against file path).
        file_type: Filter by classification type (pipeline, terraform, helm_chart, etc.).
        repo: Filter by repository name.
        branch: Filter by branch.
        limit: Max results.

    Returns:
        list[dict] — matching files with path, type, repo, branch info.
    """
    entities_path = PROJECT_ROOT / "memory" / client / "entities.json"
    if not entities_path.exists():
        return []

    with open(entities_path, "r", encoding="utf-8") as f:
        entities = json.load(f)

    # entities.json is a flat list of entity dicts (not a dict with a "files" key)
    files = entities if isinstance(entities, list) else entities.get("files", [])
    results = []

    for file_entry in files:
        # Apply filters
        file_path = file_entry.get("file", file_entry.get("path", ""))
        if query and query.lower() not in file_path.lower():
            continue

        if file_type and file_entry.get("type", "") != file_type:
            continue

        if repo and file_entry.get("repo", "") != repo:
            continue

        if branch and file_entry.get("branch", "") != branch:
            continue

        results.append(file_entry)

        if len(results) >= limit:
            break

    return results


def search_files_in_repos(
    client: str,
    query: str = "",
    file_type: str = None,
    repo: str = None,
    branch: str = None,
    limit: int = 25,
) -> list:
    """
    Fallback: search actual repo directories for files matching criteria.
    Used when entities.json is not available.
    """
    config = _load_config(client)
    if not config:
        return []

    repos = config.get("repos", [])
    results = []

    for repo_cfg in repos:
        repo_name = repo_cfg.get("name", "")
        repo_path = Path(repo_cfg.get("path", ""))

        if repo and repo_name != repo:
            continue

        if not repo_path.exists():
            continue

        for file_path in repo_path.rglob("*"):
            if file_path.is_dir():
                continue
            if file_path.name.startswith("."):
                continue

            rel = str(file_path.relative_to(repo_path)).replace("\\", "/")

            if query and query.lower() not in rel.lower():
                continue

            if file_type:
                from ingest.classify_files import classify_file
                classification = classify_file(rel, repo_cfg.get("type", ""))
                if classification != file_type:
                    continue

            results.append({
                "path": rel,
                "repo": repo_name,
                "full_path": str(file_path),
            })

            if len(results) >= limit:
                break

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

    # Manual YAML parse
    config = {"repos": []}
    current_repo = None
    current_key = None

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
    parser = argparse.ArgumentParser(description="HiveMind Search Files")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--query", default="", help="Search string (matches file path)")
    parser.add_argument("--type", default=None, help="Filter by file type")
    parser.add_argument("--repo", default=None, help="Filter by repo name")
    parser.add_argument("--branch", default=None, help="Filter by branch")
    parser.add_argument("--limit", type=int, default=25, help="Max results")
    args = parser.parse_args()

    results = search_files(
        client=args.client,
        query=args.query,
        file_type=args.type,
        repo=args.repo,
        branch=args.branch,
        limit=args.limit,
    )

    if not results:
        # Try repo scan
        results = search_files_in_repos(
            client=args.client,
            query=args.query,
            file_type=args.type,
            repo=args.repo,
            branch=args.branch,
            limit=args.limit,
        )

    if not results:
        print("No files found matching criteria.")
        return

    print(f"Found {len(results)} files:\n")
    for r in results:
        typ = r.get("type", "—")
        repo_name = r.get("repo", "—")
        file_path = r.get("file", r.get("path", "—"))
        print(f"  [{typ}] {repo_name}/{file_path}")


if __name__ == "__main__":
    main()

