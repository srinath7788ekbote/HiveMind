"""
Branch Indexer

Manages branch-aware indexing of repositories.
Each branch gets its own namespace in the vector store and graph DB.

Supports:
- Classifying branches by tier (production, integration, release, etc.)
- Switching between branches for indexing
- Tracking which branches have been indexed and when
"""

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional


BRANCH_TIER_PATTERNS = {
    "production": [r'^main$', r'^master$'],
    "integration": [r'^develop$', r'^development$'],
    "release": [r'^release[_/]', r'^release$'],
    "hotfix": [r'^hotfix[_/]', r'^hotfix$'],
    "feature": [r'^feature[_/]', r'^feature$'],
    "bugfix": [r'^bugfix[_/]', r'^fix[_/]'],
}


def classify_branch_tier(branch_name: str) -> str:
    """
    Classify a branch name into a tier.

    Args:
        branch_name: Branch name (e.g., "develop", "release_26_1", "hotfix/fix-kv")

    Returns:
        Tier string: production, integration, release, hotfix, feature, bugfix, or unknown
    """
    branch_lower = branch_name.lower().strip()
    for tier, patterns in BRANCH_TIER_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, branch_lower):
                return tier
    return "unknown"


def get_repo_branches(repo_path: str) -> list[str]:
    """
    Get list of branches for a local Git repository.

    Args:
        repo_path: Absolute path to the repo.

    Returns:
        List of branch names.
    """
    try:
        result = subprocess.run(
            ["git", "branch", "-a", "--format=%(refname:short)"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []

        branches = []
        for line in result.stdout.strip().split('\n'):
            branch = line.strip()
            if not branch:
                continue
            # Remove origin/ prefix for remote branches
            if branch.startswith("origin/"):
                branch = branch[7:]
            if branch == "HEAD":
                continue
            if branch not in branches:
                branches.append(branch)
        return branches
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []


def get_current_branch(repo_path: str) -> str:
    """
    Get the current branch of a local Git repository.

    Args:
        repo_path: Absolute path to the repo.

    Returns:
        Current branch name, or "unknown" if unable to determine.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return "unknown"


def checkout_branch(repo_path: str, branch: str) -> bool:
    """
    Checkout a specific branch in a repository.

    Args:
        repo_path: Absolute path to the repo.
        branch: Branch name to checkout.

    Returns:
        True if successful, False otherwise.
    """
    try:
        result = subprocess.run(
            ["git", "checkout", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


class BranchIndex:
    """
    Tracks which branches have been indexed and when.
    Persists to a JSON file in the memory directory.
    """

    def __init__(self, index_file: str):
        self.index_file = Path(index_file)
        self._index: dict = {}
        self._load()

    def _load(self) -> None:
        """Load the index from disk."""
        if self.index_file.exists():
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._index = {}

    def _save(self) -> None:
        """Save the index to disk."""
        self.index_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self._index, f, indent=2)

    def mark_indexed(self, repo: str, branch: str, commit_hash: str = "") -> None:
        """
        Mark a branch as indexed.

        Args:
            repo: Repository name
            branch: Branch name
            commit_hash: Git commit hash at time of indexing
        """
        key = f"{repo}:{branch}"
        self._index[key] = {
            "repo": repo,
            "branch": branch,
            "tier": classify_branch_tier(branch),
            "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "commit_hash": commit_hash,
        }
        self._save()

    def is_indexed(self, repo: str, branch: str) -> bool:
        """Check if a branch has been indexed."""
        key = f"{repo}:{branch}"
        return key in self._index

    def get_indexed_branches(self, repo: Optional[str] = None) -> list[dict]:
        """
        Get all indexed branches, optionally filtered by repo.

        Returns:
            List of dicts with repo, branch, tier, indexed_at, commit_hash
        """
        results = list(self._index.values())
        if repo:
            results = [r for r in results if r["repo"] == repo]
        return sorted(results, key=lambda r: (r["repo"], r["branch"]))

    def get_commit_hash(self, repo: str, branch: str) -> str:
        """Get the commit hash at which a branch was last indexed."""
        key = f"{repo}:{branch}"
        entry = self._index.get(key, {})
        return entry.get("commit_hash", "")

    def needs_reindex(self, repo: str, branch: str, current_hash: str) -> bool:
        """
        Check if a branch needs re-indexing based on commit hash.

        Returns:
            True if the branch has not been indexed or the hash differs.
        """
        stored_hash = self.get_commit_hash(repo, branch)
        if not stored_hash:
            return True
        return stored_hash != current_hash
