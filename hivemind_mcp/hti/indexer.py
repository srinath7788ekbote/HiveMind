"""HTI Indexer — Walk repos and index YAML/HCL files into SQLite.

Reads clients/<client>/repos.yaml, walks each repo for infrastructure
files, extracts skeleton trees and nodes, and stores them in hti.sqlite.

Usage:
    python hivemind_mcp/hti/indexer.py --client dfin
    python hivemind_mcp/hti/indexer.py --client dfin --branch release_26_2
    python hivemind_mcp/hti/indexer.py --client dfin --force
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import yaml

from hivemind_mcp.hti.extractor import extract_yaml_tree, extract_hcl_tree
from hivemind_mcp.hti.utils import detect_file_type, get_hti_connection


# Directories to skip during file walking
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "vendor", ".terraform",
    ".pytest_cache", ".mypy_cache", "__pycache__", ".venv", "venv",
}

# File extensions to index
INDEX_EXTENSIONS = {".yaml", ".yml", ".tf", ".hcl", ".json"}


def _load_repos(client: str, project_root: Path = None) -> list:
    """Load repo configs from clients/<client>/repos.yaml."""
    root = project_root or PROJECT_ROOT
    repos_yaml = root / "clients" / client / "repos.yaml"
    if not repos_yaml.exists():
        raise FileNotFoundError(f"Client config not found: {repos_yaml}")

    with open(repos_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config.get("repos", [])


def _walk_repo_files(repo_path: str) -> list:
    """Walk a repo and yield relevant infrastructure file paths."""
    repo = Path(repo_path)
    if not repo.exists():
        return []

    files = []
    for root, dirs, filenames in os.walk(repo):
        # Skip unwanted directories in-place
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext in INDEX_EXTENSIONS:
                files.append(Path(root) / fname)

    return files


def index_client(
    client: str,
    branch: str = None,
    force: bool = False,
    project_root: Path = None,
    verbose: bool = False,
) -> dict:
    """Index all repos for a client into hti.sqlite.

    Args:
        client: Client name (e.g., "dfin").
        branch: Optional branch filter. If None, uses "main".
        force: If True, re-index all files regardless of mtime.
        project_root: Override project root for testing.
        verbose: Print progress details.

    Returns:
        Summary dict with file_count, node_count, skeleton_count, etc.
    """
    root = project_root or PROJECT_ROOT
    repos = _load_repos(client, root)

    if not repos:
        return {"error": "No repos configured", "file_count": 0}

    effective_branch = branch or "main"
    total_files = 0
    total_nodes = 0
    total_skeletons = 0
    skipped = 0

    # --- Phase 1: Read mtime cache to know what to skip ---
    existing_mtimes = {}
    if not force:
        conn = get_hti_connection(client, root)
        cursor = conn.cursor()
        cursor.execute("SELECT id, mtime_epoch FROM hti_skeletons WHERE branch = ?",
                       (effective_branch,))
        for row in cursor.fetchall():
            existing_mtimes[row[0]] = row[1]
        conn.close()

    # --- Phase 2: Parse all files in memory (CPU-bound, parallel-safe) ---
    parsed_data = []  # list of (skeleton_id, repo_name, rel_path, file_type,
                      #          skeleton_json, nodes, file_mtime)

    for repo_config in repos:
        repo_name = repo_config.get("name", "unknown")
        repo_path = repo_config.get("path", "")

        if not repo_path or not Path(repo_path).exists():
            if verbose:
                print(f"  SKIP: {repo_name} — path not found: {repo_path}")
            continue

        if verbose:
            print(f"\n  Parsing: {repo_name} ({repo_path})")

        files = _walk_repo_files(repo_path)
        repo_file_count = 0

        for file_path in files:
            try:
                rel_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
            except ValueError:
                rel_path = str(file_path)

            skeleton_id = f"{client}:{repo_name}:{effective_branch}:{rel_path}"

            # Incremental: check mtime
            file_mtime = int(file_path.stat().st_mtime)
            if not force:
                prev_mtime = existing_mtimes.get(skeleton_id)
                if prev_mtime is not None and prev_mtime >= file_mtime:
                    skipped += 1
                    continue

            # Read and extract
            ext = file_path.suffix.lower()
            try:
                content = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue

            file_type = detect_file_type(rel_path, content)

            if ext in (".tf", ".hcl"):
                try:
                    skeleton, nodes = extract_hcl_tree(str(file_path))
                except ImportError:
                    continue
            else:
                skeleton, nodes = extract_yaml_tree(str(file_path))

            if "_error" in skeleton:
                continue

            skeleton_json = json.dumps(skeleton, separators=(",", ":"))
            parsed_data.append((skeleton_id, repo_name, rel_path, file_type,
                                skeleton_json, nodes, file_mtime))
            repo_file_count += 1

        total_files += repo_file_count
        if verbose:
            print(f"    Files parsed: {repo_file_count}")

    # --- Phase 3: Write to SQLite in batches with retry ---
    if parsed_data:
        if verbose:
            print(f"\n  Writing {len(parsed_data)} skeletons to SQLite...")

        BATCH_SIZE = 50
        max_retries = 5

        for batch_start in range(0, len(parsed_data), BATCH_SIZE):
            batch = parsed_data[batch_start:batch_start + BATCH_SIZE]

            for attempt in range(max_retries):
                conn = None
                try:
                    conn = get_hti_connection(client, root)
                    cursor = conn.cursor()

                    for (skeleton_id, repo_name, rel_path, file_type,
                         skeleton_json, nodes, file_mtime) in batch:

                        cursor.execute(
                            """INSERT OR REPLACE INTO hti_skeletons
                               (id, client, repo, branch, file_path, file_type, skeleton_json,
                                node_count, mtime_epoch, indexed_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                            (skeleton_id, client, repo_name, effective_branch, rel_path,
                             file_type, skeleton_json, len(nodes), file_mtime),
                        )

                        cursor.execute(
                            "DELETE FROM hti_nodes WHERE skeleton_id = ?",
                            (skeleton_id,),
                        )

                        for node in nodes:
                            node_id = f"{skeleton_id}:{node['node_path']}"
                            cursor.execute(
                                """INSERT OR REPLACE INTO hti_nodes
                                   (id, skeleton_id, node_path, depth, content_json)
                                   VALUES (?, ?, ?, ?, ?)""",
                                (node_id, skeleton_id, node["node_path"],
                                 node["depth"], node["content_json"]),
                            )

                        total_nodes += len(nodes)
                        total_skeletons += 1

                    conn.commit()
                    conn.close()
                    break  # Success — exit retry loop
                except Exception as e:
                    if conn:
                        try:
                            conn.close()
                        except Exception:
                            pass
                    if "database is locked" in str(e) and attempt < max_retries - 1:
                        import time as _time
                        wait = (attempt + 1) * 2  # 2, 4, 6, 8, 10 seconds
                        if verbose:
                            print(f"    DB locked, retry {attempt + 1}/{max_retries} in {wait}s...")
                        _time.sleep(wait)
                    else:
                        raise

    return {
        "client": client,
        "branch": effective_branch,
        "file_count": total_files,
        "skeleton_count": total_skeletons,
        "node_count": total_nodes,
        "skipped_unchanged": skipped,
        "force": force,
    }


def main():
    parser = argparse.ArgumentParser(description="HTI Indexer — index YAML/HCL files")
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--branch", default=None, help="Branch to index (default: main)")
    parser.add_argument("--force", action="store_true", help="Re-index all files")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    print("=" * 50)
    print("HTI INDEXER")
    print("=" * 50)
    print(f"Client: {args.client}")
    if args.branch:
        print(f"Branch: {args.branch}")
    if args.force:
        print("Mode: FORCE (re-index all)")
    print()

    try:
        summary = index_client(
            client=args.client,
            branch=args.branch,
            force=args.force,
            verbose=args.verbose,
        )
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    print("\n" + "=" * 50)
    print("INDEXING COMPLETE")
    print("=" * 50)
    for key, value in summary.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    main()
