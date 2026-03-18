"""
Read File — Read actual file content from a repo with KB cross-reference

Searches the HiveMind knowledge base first for indexed chunks matching
the file path, then reads from disk for complete content.  Returns both
KB coverage info and full file content when available.

Usage:
    python tools/read_file.py --client dfin --repo dfin-harness-pipelines \\
        --file newad/cd/cd_deploy_env/pipeline.yaml --branch main

    python tools/read_file.py --client dfin --repo Eastwood-terraform \\
        --file layer_5/secrets.tf
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

# Force UTF-8 output on Windows to avoid charmap encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.query_memory import query_memory


# ---------------------------------------------------------------------------
# Repo Resolution (reuses pattern from write_file.py)
# ---------------------------------------------------------------------------

def _find_repo_path(client: str, repo_name: str) -> str:
    """
    Find the local path for a repo from clients/<client>/repos.yaml.

    Raises:
        FileNotFoundError: If repos.yaml is missing.
        ValueError: If repo is not found in repos.yaml.
    """
    repos_yaml = PROJECT_ROOT / "clients" / client / "repos.yaml"
    if not repos_yaml.exists():
        raise FileNotFoundError(
            f"Client config not found: {repos_yaml}\n"
            f"Ensure clients/{client}/repos.yaml exists."
        )

    with open(repos_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    repos = config.get("repos", [])
    for repo in repos:
        if repo.get("name") == repo_name:
            repo_path = repo.get("path", "")
            if not repo_path:
                raise ValueError(
                    f"Repo '{repo_name}' has no path in {repos_yaml}"
                )
            return repo_path

    available = [r.get("name", "?") for r in repos]

    # Fuzzy match: check if repo_name is a substring of any repo or vice versa
    fuzzy = [
        r.get("name", "")
        for r in repos
        if repo_name.lower() in r.get("name", "").lower()
        or r.get("name", "").lower() in repo_name.lower()
    ]
    if len(fuzzy) == 1:
        match = fuzzy[0]
        matched_repo = next(r for r in repos if r.get("name") == match)
        repo_path = matched_repo.get("path", "")
        if repo_path:
            return repo_path

    raise ValueError(
        f"Repo '{repo_name}' not found in {repos_yaml}.\n"
        f"Available repos: {', '.join(available)}"
    )


def _list_available_repos(client: str) -> list[str]:
    """List all repo names for a client."""
    repos_yaml = PROJECT_ROOT / "clients" / client / "repos.yaml"
    if not repos_yaml.exists():
        return []
    with open(repos_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return [r.get("name", "?") for r in config.get("repos", [])]


# ---------------------------------------------------------------------------
# KB Lookup
# ---------------------------------------------------------------------------

def _search_kb_for_file(client: str, file_path: str, branch: str = None) -> dict:
    """
    Search the KB (ChromaDB / BM25) for chunks matching this file path.

    Returns dict with keys: chunks_found, coverage, chunks
    """
    try:
        results = query_memory(
            client=client,
            query=file_path,
            branch=branch,
            top_k=20,
        )
    except Exception:
        return {"chunks_found": 0, "coverage": "none", "chunks": []}

    if not results:
        return {"chunks_found": 0, "coverage": "none", "chunks": []}

    # Filter results to only those matching this exact file path
    file_path_lower = file_path.lower().replace("\\", "/")
    matching = []
    for chunk in results:
        chunk_path = chunk.get("file_path", "").lower().replace("\\", "/")
        if file_path_lower in chunk_path or chunk_path.endswith(file_path_lower):
            matching.append(chunk)

    if not matching:
        return {"chunks_found": 0, "coverage": "none", "chunks": []}

    # Estimate coverage based on number of chunks found
    count = len(matching)
    if count >= 5:
        coverage = "full"
    elif count >= 2:
        coverage = "partial"
    else:
        coverage = "partial"

    return {
        "chunks_found": count,
        "coverage": coverage,
        "chunks": matching,
    }


# ---------------------------------------------------------------------------
# Disk Read
# ---------------------------------------------------------------------------

def _read_from_disk(repo_path: str, file_path: str, branch: str = None) -> dict:
    """
    Read file content from disk or via git show for a specific branch.

    Returns dict with keys: content, line_count, size_bytes, source_branch
    """
    full_path = Path(repo_path) / file_path

    if branch:
        # Try git show <branch>:<file_path> first
        try:
            result = subprocess.run(
                ["git", "show", f"{branch}:{file_path}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=15,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                content = result.stdout
                return {
                    "content": content,
                    "line_count": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
                    "size_bytes": len(content.encode("utf-8")),
                    "source_branch": branch,
                }
        except (subprocess.TimeoutExpired, OSError):
            pass
        # Fall through to working tree read

    # Read from working tree
    if not full_path.exists():
        return {"error": f"File not found: {full_path}"}

    if not full_path.is_file():
        return {"error": f"Path is not a file: {full_path}"}

    content = full_path.read_text(encoding="utf-8", errors="replace")
    return {
        "content": content,
        "line_count": content.count("\n") + (1 if content and not content.endswith("\n") else 0),
        "size_bytes": len(content.encode("utf-8")),
        "source_branch": branch or "working-tree",
    }


# ---------------------------------------------------------------------------
# Main Read Logic
# ---------------------------------------------------------------------------

def read_file(
    client: str,
    repo: str,
    file_path: str,
    branch: str = None,
) -> dict:
    """
    Read a file from a repo with KB cross-reference.

    Step 1: Search KB for chunks matching this file path
    Step 2: Read from disk (or via git show for a specific branch)
    Step 3: Return both KB info and full content

    Args:
        client: Client name (e.g., 'dfin').
        repo: Repository name (e.g., 'dfin-harness-pipelines').
        file_path: Path within the repo (e.g., 'newad/cd/cd_deploy_env/pipeline.yaml').
        branch: Optional branch to read from (uses git show).

    Returns:
        Dict with file content and metadata.
    """
    result = {
        "file_path": file_path,
        "repo": repo,
        "branch": branch,
        "source": "none",
        "content": "",
        "line_count": 0,
        "kb_chunks_found": 0,
        "kb_coverage": "none",
        "note": "",
    }

    # Step 1: KB lookup
    kb_info = _search_kb_for_file(client, file_path, branch)
    result["kb_chunks_found"] = kb_info["chunks_found"]
    result["kb_coverage"] = kb_info["coverage"]

    # Step 2: Disk read
    try:
        repo_path = _find_repo_path(client, repo)
    except (FileNotFoundError, ValueError) as e:
        # Repo not found — return KB content only if available
        if kb_info["chunks_found"] > 0:
            # Reconstruct content from KB chunks
            kb_content = "\n---\n".join(
                c.get("text", "") for c in kb_info.get("chunks", [])
            )
            result["content"] = kb_content
            result["line_count"] = kb_content.count("\n") + 1
            result["source"] = "kb"
            result["note"] = (
                f"Repo resolution failed: {e}. "
                f"Returning {kb_info['chunks_found']} KB chunks only."
            )
            return result

        available = _list_available_repos(client)
        result["note"] = (
            f"Error: {e}\n"
            f"Available repos: {', '.join(available) if available else 'none'}"
        )
        return result

    disk_info = _read_from_disk(repo_path, file_path, branch)

    if "error" in disk_info:
        # Disk read failed — return KB content if available
        if kb_info["chunks_found"] > 0:
            kb_content = "\n---\n".join(
                c.get("text", "") for c in kb_info.get("chunks", [])
            )
            result["content"] = kb_content
            result["line_count"] = kb_content.count("\n") + 1
            result["source"] = "kb"
            result["note"] = (
                f"{disk_info['error']}. "
                f"Returning {kb_info['chunks_found']} KB chunks (coverage: {kb_info['coverage']})."
            )
            return result

        result["note"] = disk_info["error"]
        return result

    # Step 3: Return disk content (authoritative) + KB metadata
    result["content"] = disk_info["content"]
    result["line_count"] = disk_info["line_count"]
    result["branch"] = disk_info.get("source_branch", branch)

    if kb_info["chunks_found"] > 0:
        result["source"] = "both"
        result["note"] = (
            f"Full content from disk ({disk_info['size_bytes']} bytes). "
            f"KB also has {kb_info['chunks_found']} indexed chunks "
            f"(coverage: {kb_info['coverage']})."
        )
    else:
        result["source"] = "disk"
        result["note"] = (
            f"Read from disk ({disk_info['size_bytes']} bytes). "
            f"No KB chunks found for this file."
        )

    return result


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Read file content from a repo with KB cross-reference."
    )
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--file", required=True, help="File path within the repo")
    parser.add_argument("--branch", default=None, help="Branch to read from (optional)")
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output raw JSON instead of formatted text",
    )

    args = parser.parse_args()

    try:
        result = read_file(
            client=args.client,
            repo=args.repo,
            file_path=args.file,
            branch=args.branch,
        )

        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"[FILE] {result['file_path']}")
            print(f"[REPO] {result['repo']}")
            print(f"[BRANCH] {result['branch'] or 'working-tree'}")
            print(f"[SOURCE] {result['source']}")
            print(f"[LINES] {result['line_count']}")
            print(f"[KB CHUNKS] {result['kb_chunks_found']} (coverage: {result['kb_coverage']})")
            print(f"[NOTE] {result['note']}")
            if result["content"]:
                print("---")
                print(result["content"])

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
