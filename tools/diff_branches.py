"""
Diff Branches — Compare two branches and show what changed

Provides a structured diff between branches, categorizing changes
by type (pipeline, terraform, helm, etc.) and showing impact.

Usage:
    python tools/diff_branches.py --client dfin --repo Eastwood-terraform --base main --compare develop
    python tools/diff_branches.py --client dfin --repo dfin-harness-pipelines --base main --compare feature/new-svc
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def diff_branches(
    client: str,
    repo: str,
    base: str,
    compare: str,
) -> dict:
    """
    Compare two branches and return structured changes.

    Args:
        client: Client name.
        repo: Repository name.
        base: Base branch (e.g., main).
        compare: Compare branch (e.g., develop).

    Returns:
        dict with:
            repo: str
            base: str
            compare: str
            files_added: list[dict]
            files_modified: list[dict]
            files_deleted: list[dict]
            categories: dict[str, int] — count by type
            summary: str
    """
    from sync.git_utils import diff_branches as git_diff, get_file_content_at_branch
    from ingest.classify_files import classify_file

    config = _load_config(client)
    if not config:
        return {"error": "Client config not found"}

    repo_cfg = None
    for r in config.get("repos", []):
        if r.get("name", "") == repo:
            repo_cfg = r
            break

    if not repo_cfg:
        return {"error": f"Repo '{repo}' not found in config"}

    repo_path = Path(repo_cfg.get("path", ""))
    if not repo_path.exists():
        return {"error": f"Repo path not found: {repo_path}"}

    # Get git diff
    diff_output = git_diff(str(repo_path), base, compare)
    if not diff_output:
        return {
            "repo": repo,
            "base": base,
            "compare": compare,
            "files_added": [],
            "files_modified": [],
            "files_deleted": [],
            "categories": {},
            "summary": "No differences found or branches are identical.",
        }

    # Parse diff output — git_diff returns list[dict] with {file, status}
    # but may also receive raw string from tests or older git_utils versions
    result = {
        "repo": repo,
        "base": base,
        "compare": compare,
        "files_added": [],
        "files_modified": [],
        "files_deleted": [],
        "categories": {},
        "summary": "",
    }

    repo_type = repo_cfg.get("type", "unknown")

    # Normalize diff_output to list of (file_path, status_code) tuples
    entries: list[tuple] = []
    if isinstance(diff_output, str):
        # Raw git diff --name-status string: "A\tfile.yaml\nM\tfile2.yaml\n"
        for line in diff_output.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                entries.append((parts[1].strip(), parts[0].strip()))
            else:
                entries.append((line.strip(), "M"))
    elif isinstance(diff_output, list):
        for entry in diff_output:
            if isinstance(entry, dict):
                fp = entry.get("file", "")
                sr = entry.get("status", "modified")
                status_map = {"added": "A", "modified": "M", "deleted": "D", "renamed": "M"}
                entries.append((fp, status_map.get(sr, "M")))
            elif isinstance(entry, str):
                entries.append((entry.strip(), "M"))

    for file_path, status in entries:
        classification = classify_file(file_path, repo_type)

        file_info = {
            "path": file_path,
            "type": classification,
        }

        if status == "A":
            result["files_added"].append(file_info)
        elif status == "D":
            result["files_deleted"].append(file_info)
        else:
            result["files_modified"].append(file_info)

        # Track categories
        result["categories"][classification] = result["categories"].get(classification, 0) + 1

    # Build summary
    total = len(result["files_added"]) + len(result["files_modified"]) + len(result["files_deleted"])
    parts = [
        f"Branch diff: {base} → {compare} in {repo}",
        f"  Total changes: {total}",
        f"  Added: {len(result['files_added'])}",
        f"  Modified: {len(result['files_modified'])}",
        f"  Deleted: {len(result['files_deleted'])}",
    ]

    if result["categories"]:
        parts.append("  By category:")
        for cat, count in sorted(result["categories"].items(), key=lambda x: -x[1]):
            parts.append(f"    {cat}: {count}")

    result["summary"] = "\n".join(parts)
    return result


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
    parser = argparse.ArgumentParser(description="HiveMind Diff Branches — compare branch changes")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--base", required=True, help="Base branch")
    parser.add_argument("--compare", required=True, help="Compare branch")
    args = parser.parse_args()

    result = diff_branches(
        client=args.client,
        repo=args.repo,
        base=args.base,
        compare=args.compare,
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        return

    print(result["summary"])

    if result["files_added"]:
        print(f"\n--- Added ---")
        for f in result["files_added"]:
            print(f"  [{f['type']}] {f['path']}")

    if result["files_modified"]:
        print(f"\n--- Modified ---")
        for f in result["files_modified"]:
            print(f"  [{f['type']}] {f['path']}")

    if result["files_deleted"]:
        print(f"\n--- Deleted ---")
        for f in result["files_deleted"]:
            print(f"  [{f['type']}] {f['path']}")


if __name__ == "__main__":
    main()

