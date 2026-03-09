"""
Crawl Repos — Main ingestion orchestrator

Reads the client's repos.yaml, clones/pulls repos, runs discovery,
extracts relationships, embeds chunks, and builds the profile.

Usage:
    python ingest/crawl_repos.py --client dfin --config clients/dfin/repos.yaml
    python ingest/crawl_repos.py --client dfin --config clients/dfin/repos.yaml --branch develop
    python ingest/crawl_repos.py --client dfin --config clients/dfin/repos.yaml --incremental
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingest.discovery.build_profile import build_profile
from ingest.extract_relationships import extract_relationships, save_to_graph_db
from ingest.embed_chunks import embed_repo
from ingest.branch_indexer import BranchIndex, get_current_branch, get_repo_branches, classify_branch_tier
from ingest.classify_files import classify_directory


def _load_config(config_path: str) -> dict:
    """Load client configuration from YAML or JSON file."""
    p = Path(config_path)
    if not p.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    content = p.read_text(encoding='utf-8')

    # Try YAML first
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass

    # Try JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Manual YAML-like parsing for simple configs
    config = {"repos": []}
    current_repo = None
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('client_name:'):
            config['client_name'] = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('- name:'):
            if current_repo:
                config["repos"].append(current_repo)
            current_repo = {"name": line.split(':', 1)[1].strip().strip('"\''), "branches": []}
        elif current_repo and line.startswith('path:'):
            current_repo["path"] = line.split(':', 1)[1].strip().strip('"\'')
        elif current_repo and line.startswith('type:'):
            current_repo["type"] = line.split(':', 1)[1].strip().strip('"\'')
        elif current_repo and line.startswith('- ') and current_repo.get("branches") is not None:
            branch = line[2:].strip().strip('"\'')
            if branch and not branch.startswith('name:'):
                current_repo["branches"].append(branch)
    if current_repo:
        config["repos"].append(current_repo)

    return config


def _ensure_memory_dir(client: str) -> Path:
    """Create and return the memory directory for a client."""
    mem_dir = PROJECT_ROOT / "memory" / client
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def crawl(
    client: str,
    config_path: str,
    branches: list[str] = None,
    incremental: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Main crawl function. Orchestrates all ingestion steps.

    Args:
        client: Client name.
        config_path: Path to repos.yaml.
        branches: Specific branches to index. If None, use config defaults.
        incremental: Only update changed files.
        verbose: Print detailed progress.

    Returns:
        Summary dict with counts and timing.
    """
    start_time = time.time()
    config = _load_config(config_path)
    mem_dir = _ensure_memory_dir(client)

    repos = config.get("repos", [])
    if not repos:
        print("ERROR: No repos configured.", file=sys.stderr)
        return {"error": "No repos configured"}

    # Initialize indexes
    branch_index = BranchIndex(str(mem_dir / "branch_index.json"))
    graph_db_path = str(mem_dir / "graph.sqlite")
    entities_path = str(mem_dir / "entities.json")

    total_chunks = 0
    total_edges = 0
    total_files = 0
    all_entities = []
    repos_processed = 0

    for repo_config in repos:
        repo_path = repo_config.get("path", "")
        repo_name = repo_config.get("name", Path(repo_path).name if repo_path else "unknown")

        if not repo_path or not Path(repo_path).exists():
            if verbose:
                print(f"  SKIP: {repo_name} — path does not exist: {repo_path}")
            continue

        if verbose:
            print(f"\n  Processing: {repo_name} ({repo_path})")

        # Determine branches to index
        repo_branches = branches or repo_config.get("branches", ["default"])
        original_branch = get_current_branch(repo_path)

        for branch in repo_branches:
            if verbose:
                print(f"    Branch: {branch}")

            # Classify files
            classifications = classify_directory(repo_path, repo_path)
            total_files += len(classifications)

            # Extract relationships
            edges = extract_relationships(repo_path)
            for edge in edges:
                edge["branch"] = branch
            total_edges += len(edges)

            if verbose:
                print(f"      Edges: {len(edges)}")

            # Save edges to graph DB
            save_to_graph_db(edges, graph_db_path)

            # Embed chunks
            result = embed_repo(
                repo_path=repo_path,
                memory_dir=str(mem_dir),
                branch=branch,
                collection_name=f"{repo_name}_{branch}",
            )
            total_chunks += result.get("chunk_count", 0)

            if verbose:
                print(f"      Chunks: {result.get('chunk_count', 0)}")

            # Mark branch as indexed
            branch_index.mark_indexed(repo_name, branch)

            # Collect entities
            for clf in classifications:
                if clf["classification"] not in ("skip", "unknown"):
                    all_entities.append({
                        "name": Path(clf["relative_path"]).stem,
                        "type": clf["classification"],
                        "file": clf["relative_path"],
                        "repo": repo_name,
                        "branch": branch,
                    })

        repos_processed += 1

    # Save entities
    with open(entities_path, 'w', encoding='utf-8') as f:
        json.dump(all_entities, f, indent=2)

    # Build profile
    if verbose:
        print("\n  Building discovered profile...")

    profile = build_profile(
        client_name=client,
        repo_configs=repos,
        output_dir=str(mem_dir),
    )

    # Set active branch
    default_branch = config.get("default_branch", "develop")
    active_branch_file = mem_dir / "active_branch.txt"
    active_branch_file.write_text(default_branch, encoding='utf-8')

    elapsed = time.time() - start_time

    summary = {
        "client": client,
        "repos_processed": repos_processed,
        "total_files": total_files,
        "total_chunks": total_chunks,
        "total_edges": total_edges,
        "total_entities": len(all_entities),
        "elapsed_seconds": round(elapsed, 2),
        "profile_path": str(mem_dir / "discovered_profile.yaml"),
        "graph_db_path": graph_db_path,
    }

    if verbose:
        print(f"\n  Done in {elapsed:.1f}s")
        print(f"  Files: {total_files} | Chunks: {total_chunks} | Edges: {total_edges} | Entities: {len(all_entities)}")

    return summary


def main():
    parser = argparse.ArgumentParser(description="HiveMind Repo Crawler — ingest repositories")
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--config", required=True, help="Path to repos.yaml config file")
    parser.add_argument("--branch", action="append", dest="branches", help="Specific branch(es) to index")
    parser.add_argument("--incremental", action="store_true", help="Only update changed files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 60)
    print("HIVEMIND REPO CRAWLER")
    print("=" * 60)
    print(f"Client: {args.client}")
    print(f"Config: {args.config}")
    if args.branches:
        print(f"Branches: {', '.join(args.branches)}")
    print()

    summary = crawl(
        client=args.client,
        config_path=args.config,
        branches=args.branches,
        incremental=args.incremental,
        verbose=args.verbose,
    )

    print("\n" + "=" * 60)
    print("CRAWL COMPLETE")
    print("=" * 60)
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    main()
