"""
Incremental Sync

Detects changes in repos since last indexing and updates only
the affected chunks, graph edges, and entities.
"""

import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.git_utils import fetch, get_head_hash, get_changed_files_since
from ingest.branch_indexer import BranchIndex
from ingest.classify_files import classify_file
from ingest.embed_chunks import embed_repo
from ingest.extract_relationships import extract_relationships, save_to_graph_db


def sync_repo(
    repo_path: str,
    repo_name: str,
    branch: str,
    memory_dir: str,
    verbose: bool = False,
) -> dict:
    """
    Perform incremental sync for a single repo+branch.

    Args:
        repo_path: Absolute path to the repo.
        repo_name: Name of the repo.
        branch: Branch to sync.
        memory_dir: Path to memory directory for this client.
        verbose: Print detailed progress.

    Returns:
        dict with sync results: changed_files, new_chunks, new_edges, etc.
    """
    mem = Path(memory_dir)
    branch_index = BranchIndex(str(mem / "branch_index.json"))

    # Fetch latest
    if verbose:
        print(f"    Fetching {repo_name}...")
    fetch(repo_path)

    # Get current commit hash
    current_hash = get_head_hash(repo_path, branch)
    if not current_hash:
        current_hash = get_head_hash(repo_path)

    # Check if re-index needed
    if not branch_index.needs_reindex(repo_name, branch, current_hash):
        if verbose:
            print(f"    {repo_name}:{branch} — up to date")
        return {
            "repo": repo_name,
            "branch": branch,
            "status": "up_to_date",
            "changed_files": 0,
        }

    # Get changed files since last index
    last_hash = branch_index.get_commit_hash(repo_name, branch)
    if last_hash:
        changed = get_changed_files_since(repo_path, last_hash, branch)
    else:
        # First time — full index
        changed = None

    if changed is not None and len(changed) == 0:
        if verbose:
            print(f"    {repo_name}:{branch} — no file changes")
        branch_index.mark_indexed(repo_name, branch, current_hash)
        return {
            "repo": repo_name,
            "branch": branch,
            "status": "no_changes",
            "changed_files": 0,
        }

    if verbose:
        count = len(changed) if changed else "all"
        print(f"    {repo_name}:{branch} — {count} files changed")

    # Re-embed (for now, full re-embed; future: incremental chunk update)
    embed_result = embed_repo(
        repo_path=repo_path,
        memory_dir=memory_dir,
        branch=branch,
        collection_name=f"{repo_name}_{branch}",
    )

    # Re-extract relationships
    edges = extract_relationships(repo_path)
    for edge in edges:
        edge["branch"] = branch
    graph_db_path = str(mem / "graph.sqlite")
    save_to_graph_db(edges, graph_db_path)

    # Update branch index
    branch_index.mark_indexed(repo_name, branch, current_hash)

    return {
        "repo": repo_name,
        "branch": branch,
        "status": "updated",
        "changed_files": len(changed) if changed else -1,
        "new_chunks": embed_result.get("chunk_count", 0),
        "new_edges": len(edges),
        "commit_hash": current_hash,
    }


def sync_all(
    client: str,
    config: dict,
    verbose: bool = False,
) -> list[dict]:
    """
    Sync all repos for a client.

    Args:
        client: Client name.
        config: Client config dict (from repos.yaml).
        verbose: Print detailed progress.

    Returns:
        List of sync result dicts, one per repo+branch.
    """
    memory_dir = str(PROJECT_ROOT / "memory" / client)
    Path(memory_dir).mkdir(parents=True, exist_ok=True)

    results = []
    repos = config.get("repos", [])

    for repo_config in repos:
        repo_path = repo_config.get("path", "")
        repo_name = repo_config.get("name", "")
        branches = repo_config.get("branches", ["default"])

        if not repo_path or not Path(repo_path).exists():
            if verbose:
                print(f"  SKIP: {repo_name} — path not found")
            continue

        for branch in branches:
            result = sync_repo(
                repo_path=repo_path,
                repo_name=repo_name,
                branch=branch,
                memory_dir=memory_dir,
                verbose=verbose,
            )
            results.append(result)

    return results
