"""
Git Utilities

Provides Git operations for repository management:
- Fetching latest changes
- Getting commit hashes
- Computing file diffs between branches
- Checking for uncommitted changes
"""

import os
import subprocess
from pathlib import Path
from typing import Optional


def run_git(repo_path: str, args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """
    Run a git command in the given repository.

    Args:
        repo_path: Absolute path to the repo.
        args: Git command arguments (e.g., ["status", "--porcelain"]).
        timeout: Timeout in seconds.

    Returns:
        Tuple of (return_code, stdout, stderr)
    """
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", "git not found in PATH"
    except OSError as e:
        return -1, "", str(e)


def fetch(repo_path: str) -> bool:
    """Fetch latest from all remotes."""
    code, _, _ = run_git(repo_path, ["fetch", "--all", "--prune"])
    return code == 0


def get_head_hash(repo_path: str, branch: Optional[str] = None) -> str:
    """Get the HEAD commit hash for a branch (or current HEAD)."""
    args = ["rev-parse", "HEAD"]
    if branch:
        args = ["rev-parse", branch]
    code, stdout, _ = run_git(repo_path, args)
    return stdout if code == 0 else ""


def get_changed_files_since(repo_path: str, since_hash: str, branch: str = "HEAD") -> list[dict]:
    """
    Get files changed between a commit hash and the current branch HEAD.

    Returns:
        List of dicts with keys: file, status (A=added, M=modified, D=deleted)
    """
    code, stdout, _ = run_git(repo_path, ["diff", "--name-status", since_hash, branch])
    if code != 0 or not stdout:
        return []

    changes = []
    for line in stdout.split('\n'):
        parts = line.split('\t', 1)
        if len(parts) == 2:
            status_code = parts[0].strip()
            file_path = parts[1].strip()
            status_map = {'A': 'added', 'M': 'modified', 'D': 'deleted', 'R': 'renamed'}
            status = status_map.get(status_code[0], 'modified')
            changes.append({"file": file_path, "status": status})
    return changes


def diff_branches(repo_path: str, branch1: str, branch2: str) -> list[dict]:
    """
    Get files that differ between two branches.

    Returns:
        List of dicts with keys: file, status
    """
    code, stdout, _ = run_git(repo_path, ["diff", "--name-status", branch1, branch2])
    if code != 0 or not stdout:
        return []

    changes = []
    for line in stdout.split('\n'):
        if not line.strip():
            continue
        parts = line.split('\t', 1)
        if len(parts) == 2:
            status_code = parts[0].strip()
            file_path = parts[1].strip()
            status_map = {'A': 'added', 'M': 'modified', 'D': 'deleted', 'R': 'renamed'}
            status = status_map.get(status_code[0], 'modified')
            changes.append({"file": file_path, "status": status})
    return changes


def get_file_content_at_branch(repo_path: str, file_path: str, branch: str) -> str:
    """Get the content of a file at a specific branch."""
    code, stdout, _ = run_git(repo_path, ["show", f"{branch}:{file_path}"])
    if code == 0:
        return stdout
    return ""


def has_uncommitted_changes(repo_path: str) -> bool:
    """Check if the repo has uncommitted changes."""
    code, stdout, _ = run_git(repo_path, ["status", "--porcelain"])
    return code == 0 and bool(stdout.strip())


def get_branches(repo_path: str) -> list[str]:
    """Get all local and remote branch names."""
    code, stdout, _ = run_git(repo_path, ["branch", "-a", "--format=%(refname:short)"])
    if code != 0:
        return []
    branches = []
    for line in stdout.split('\n'):
        branch = line.strip()
        if not branch or branch == "HEAD":
            continue
        if branch.startswith("origin/"):
            branch = branch[7:]
        if branch not in branches:
            branches.append(branch)
    return branches


def get_last_commit_time(repo_path: str, branch: str = "HEAD") -> str:
    """Get the timestamp of the last commit."""
    code, stdout, _ = run_git(repo_path, ["log", "-1", "--format=%ci", branch])
    return stdout if code == 0 else ""
