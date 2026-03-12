"""
Check Branch — Verify branch existence in index and on remote

Checks whether a branch is:
1. Already indexed in HiveMind's knowledge base
2. Exists on the remote repository (via git ls-remote)

Returns a structured result with suggestions for the closest indexed branch
if the requested branch is not indexed.

Usage:
    python tools/check_branch.py --client dfin --repo Eastwood-terraform --branch release_26_1
"""

import argparse
import json
import re
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def check_branch(client: str, repo: str, branch: str) -> dict:
    """
    Check if a branch is indexed and/or exists on remote.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name (e.g. "Eastwood-terraform").
        branch: Branch name to check (e.g. "release_26_1").

    Returns:
        dict with keys:
            - indexed (bool): True if branch is in the index
            - exists_on_remote (bool | str): True/False, or "unknown" on network error
            - repo (str): Repository name
            - branch (str): Requested branch name
            - indexed_branches (list[str]): All indexed branches for this repo
            - suggestion (str | None): Closest indexed branch name, or None
    """
    config = _load_config(client)
    if not config:
        return {
            "error": f"Client config not found for '{client}'. "
                     f"Expected at: clients/{client}/repos.yaml",
            "repo": repo,
            "branch": branch,
        }

    # Find the repo in config
    repo_cfg = _find_repo(config, repo)
    if not repo_cfg:
        available_repos = [r.get("name", "") for r in config.get("repos", [])]
        return {
            "error": f"Repository '{repo}' not found in clients/{client}/repos.yaml. "
                     f"Available repos: {', '.join(available_repos)}",
            "repo": repo,
            "branch": branch,
        }

    # Check index
    from ingest.branch_indexer import BranchIndex

    index_path = PROJECT_ROOT / "memory" / client / "branch_index.json"
    branch_index = BranchIndex(str(index_path))
    indexed = branch_index.is_indexed(repo, branch)

    # Get all indexed branches for this repo
    all_indexed = branch_index.get_indexed_branches(repo)
    indexed_branches = [entry["branch"] for entry in all_indexed]

    # If indexed, return immediately — no need to check remote
    if indexed:
        return {
            "indexed": True,
            "exists_on_remote": True,  # If indexed, it existed at index time
            "repo": repo,
            "branch": branch,
            "indexed_branches": indexed_branches,
            "suggestion": None,
        }

    # Not indexed — check remote
    repo_path = repo_cfg.get("path", "")
    exists_on_remote = _check_remote(repo_path, branch)

    # Find closest suggestion
    suggestion = _find_closest_branch(branch, indexed_branches)

    return {
        "indexed": False,
        "exists_on_remote": exists_on_remote,
        "repo": repo,
        "branch": branch,
        "indexed_branches": indexed_branches,
        "suggestion": suggestion,
    }


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

    # Manual YAML-like parsing for simple configs
    config = {"repos": []}
    current_repo = None

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- name:"):
            if current_repo:
                config["repos"].append(current_repo)
            current_repo = {
                "name": stripped.split(":", 1)[1].strip().strip('"\''),
                "branches": [],
            }
        elif current_repo and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"\'')
            if key == "path":
                current_repo["path"] = val
            elif key == "type":
                current_repo["type"] = val
        elif current_repo and stripped.startswith("- ") and not stripped.startswith("- name:"):
            branch = stripped[2:].strip().strip('"\'')
            if branch:
                current_repo.setdefault("branches", []).append(branch)

    if current_repo:
        config["repos"].append(current_repo)

    return config


def _find_repo(config: dict, repo: str) -> dict | None:
    """Find a repo in the config by name (case-insensitive)."""
    for repo_cfg in config.get("repos", []):
        if repo_cfg.get("name", "").lower() == repo.lower():
            return repo_cfg
    return None


def _check_remote(repo_path: str, branch: str) -> bool | str:
    """
    Check if a branch exists on the remote via git ls-remote.

    Args:
        repo_path: Local path to the cloned repo.
        branch: Branch name to look for.

    Returns:
        True if found on remote, False if not found, "unknown" on error.
    """
    if not repo_path or not Path(repo_path).exists():
        return "unknown"

    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return "unknown"

        # ls-remote output: "<hash>\trefs/heads/<branch>"
        # If it returns any line, the branch exists
        output = result.stdout.strip()
        if output:
            # Verify the branch name matches exactly
            for line in output.split("\n"):
                if line.strip():
                    ref = line.split("\t")[-1] if "\t" in line else ""
                    ref_branch = ref.replace("refs/heads/", "")
                    if ref_branch == branch:
                        return True
            return False
        return False

    except subprocess.TimeoutExpired:
        return "unknown"
    except (FileNotFoundError, OSError):
        return "unknown"


def _find_closest_branch(target: str, candidates: list[str]) -> str | None:
    """
    Find the closest matching branch name from a list of candidates.

    Uses a combination of:
    1. Release version proximity (for release_* branches)
    2. SequenceMatcher string similarity

    Args:
        target: Target branch name (e.g. "release_26_1").
        candidates: List of indexed branch names.

    Returns:
        Closest branch name, or None if no candidates.
    """
    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]

    # Try release-version-aware matching first
    target_version = _parse_release_version(target)
    if target_version is not None:
        best_match = None
        best_distance = float("inf")

        for candidate in candidates:
            candidate_version = _parse_release_version(candidate)
            if candidate_version is not None:
                distance = abs(target_version - candidate_version)
                if distance < best_distance:
                    best_distance = distance
                    best_match = candidate

        if best_match is not None:
            return best_match

    # Fall back to string similarity
    best_match = None
    best_ratio = 0.0

    for candidate in candidates:
        ratio = SequenceMatcher(None, target, candidate).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = candidate

    return best_match


def _parse_release_version(branch_name: str) -> float | None:
    """
    Parse a numeric version from a release branch name.

    Examples:
        release_26_1 -> 26.1
        release_26_2 -> 26.2
        release_12_18 -> 12.18
        release/26.3 -> 26.3
        main -> None

    Returns:
        Float version number, or None if not a release branch.
    """
    # Match patterns like release_26_1, release/26.3, release_12_18
    match = re.match(
        r'^release[_/](\d+)[_./](\d+)$',
        branch_name,
        re.IGNORECASE,
    )
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        return major + minor / 100.0

    # Single-number release: release_26
    match = re.match(r'^release[_/](\d+)$', branch_name, re.IGNORECASE)
    if match:
        return float(match.group(1))

    return None


def main():
    parser = argparse.ArgumentParser(
        description="HiveMind Check Branch — verify branch availability"
    )
    parser.add_argument("--client", required=True, help="Client name (e.g. dfin)")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--branch", required=True, help="Branch name to check")
    args = parser.parse_args()

    result = check_branch(client=args.client, repo=args.repo, branch=args.branch)

    print(json.dumps(result, indent=2))

    # Exit with appropriate code
    if result.get("error"):
        sys.exit(1)
    elif result.get("indexed"):
        sys.exit(0)
    else:
        sys.exit(2)  # Not indexed


if __name__ == "__main__":
    main()
