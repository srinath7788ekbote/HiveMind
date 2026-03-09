"""
Branch Protection Module

Enforces branch safety rules:
- Protected branches (main, master, release_*, hotfix/*) CANNOT be modified directly.
- All changes MUST go through a working branch created from the target branch.
- Provides utilities to create safe working branches and validate branch operations.

Usage:
    from sync.branch_protection import BranchProtection

    bp = BranchProtection()
    bp.validate_branch_for_edit("main")           # raises ProtectedBranchError
    bp.create_working_branch("/path/to/repo", "main")  # creates feature/hivemind/main-<timestamp>
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from sync.git_utils import run_git, get_branches


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProtectedBranchError(Exception):
    """Raised when an operation targets a protected branch directly."""

    def __init__(self, branch: str, message: str = ""):
        self.branch = branch
        self.message = message or (
            f"Branch '{branch}' is protected. "
            f"Create a working branch first using create_working_branch()."
        )
        super().__init__(self.message)


class BranchCreationError(Exception):
    """Raised when a working branch cannot be created."""
    pass


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ProtectionConfig:
    """Configuration for branch protection rules."""

    # Regex patterns for protected branches (case-insensitive)
    protected_patterns: list[str] = None

    # Prefix for auto-created working branches
    working_branch_prefix: str = "hivemind"

    # Whether to enforce protection (can be disabled for testing)
    enabled: bool = True

    def __post_init__(self):
        if self.protected_patterns is None:
            self.protected_patterns = [
                r"^main$",
                r"^master$",
                r"^release[_/].*",
                r"^hotfix[_/].*",
                r"^develop$",
                r"^development$",
            ]


# ---------------------------------------------------------------------------
# Branch Protection Engine
# ---------------------------------------------------------------------------

class BranchProtection:
    """
    Enforces branch protection rules.

    Protected branches cannot be modified directly. All changes must go
    through a working branch created via create_working_branch().
    """

    def __init__(self, config: Optional[ProtectionConfig] = None):
        self.config = config or ProtectionConfig()
        self._compiled_patterns = [
            re.compile(p, re.IGNORECASE) for p in self.config.protected_patterns
        ]

    def is_protected(self, branch: str) -> bool:
        """
        Check if a branch is protected.

        Args:
            branch: Branch name to check.

        Returns:
            True if the branch matches any protected pattern.
        """
        if not self.config.enabled:
            return False

        # Strip remote prefix if present
        clean_branch = branch
        if clean_branch.startswith("origin/"):
            clean_branch = clean_branch[7:]

        return any(p.match(clean_branch) for p in self._compiled_patterns)

    def get_protection_tier(self, branch: str) -> str:
        """
        Get the protection tier of a branch.

        Returns:
            Tier classification: 'production', 'integration', 'release',
            'hotfix', 'feature' (unprotected), or 'unknown'.
        """
        clean = branch.replace("origin/", "")

        if re.match(r"^(main|master)$", clean, re.IGNORECASE):
            return "production"
        if re.match(r"^(develop|development)$", clean, re.IGNORECASE):
            return "integration"
        if re.match(r"^release[_/]", clean, re.IGNORECASE):
            return "release"
        if re.match(r"^hotfix[_/]", clean, re.IGNORECASE):
            return "hotfix"
        if re.match(r"^feature[_/]", clean, re.IGNORECASE):
            return "feature"
        return "unknown"

    def validate_branch_for_edit(self, branch: str) -> None:
        """
        Validate that a branch can be edited directly.

        Args:
            branch: Branch name to validate.

        Raises:
            ProtectedBranchError: If the branch is protected.
        """
        if self.is_protected(branch):
            tier = self.get_protection_tier(branch)
            raise ProtectedBranchError(
                branch=branch,
                message=(
                    f"BLOCKED: Branch '{branch}' is a {tier}-tier protected branch. "
                    f"Direct modifications are not allowed. "
                    f"Use create_working_branch() to create a safe working branch, "
                    f"then submit changes via Pull Request."
                ),
            )

    def generate_working_branch_name(self, source_branch: str, description: str = "") -> str:
        """
        Generate a working branch name based on the source branch.

        Args:
            source_branch: The protected branch to branch from.
            description: Optional short description for the branch name.

        Returns:
            A safe working branch name like 'hivemind/main-1709900000'
            or 'hivemind/main-fix-pipeline-config'.
        """
        clean = source_branch.replace("origin/", "").replace("/", "-")
        prefix = self.config.working_branch_prefix

        if description:
            # Sanitize description for branch name
            safe_desc = re.sub(r"[^a-zA-Z0-9_-]", "-", description.lower())
            safe_desc = re.sub(r"-+", "-", safe_desc).strip("-")[:50]
            return f"{prefix}/{clean}-{safe_desc}"
        else:
            timestamp = int(time.time())
            return f"{prefix}/{clean}-{timestamp}"

    def create_working_branch(
        self,
        repo_path: str,
        source_branch: str,
        description: str = "",
    ) -> str:
        """
        Create a working branch from a protected branch.

        This is the ONLY safe way to make changes that target a protected
        branch. After making changes on the working branch, create a PR
        to merge back.

        Args:
            repo_path: Path to the git repository.
            source_branch: The protected branch to branch from.
            description: Optional description for branch naming.

        Returns:
            Name of the created working branch.

        Raises:
            BranchCreationError: If the branch could not be created.
        """
        working_branch = self.generate_working_branch_name(source_branch, description)

        # First, make sure we have the latest from remote
        run_git(repo_path, ["fetch", "origin"])

        # Try to create branch from remote tracking branch first, then local
        source_ref = f"origin/{source_branch}"
        code, _, stderr = run_git(repo_path, ["rev-parse", "--verify", source_ref])
        if code != 0:
            # Fall back to local branch
            source_ref = source_branch
            code, _, stderr = run_git(repo_path, ["rev-parse", "--verify", source_ref])
            if code != 0:
                raise BranchCreationError(
                    f"Source branch '{source_branch}' not found locally or on remote."
                )

        # Create the new branch
        code, stdout, stderr = run_git(
            repo_path, ["checkout", "-b", working_branch, source_ref]
        )
        if code != 0:
            raise BranchCreationError(
                f"Failed to create branch '{working_branch}' from '{source_ref}': {stderr}"
            )

        return working_branch

    def get_safe_branch_for_edit(
        self,
        repo_path: str,
        target_branch: str,
        description: str = "",
    ) -> tuple[str, bool]:
        """
        Get a safe branch for editing. If the target is protected,
        creates a working branch automatically.

        Args:
            repo_path: Path to the git repository.
            target_branch: The branch the user wants to edit.
            description: Optional description for working branch naming.

        Returns:
            Tuple of (branch_name, was_redirected).
            If was_redirected is True, a new branch was created.
        """
        if not self.is_protected(target_branch):
            return target_branch, False

        working_branch = self.create_working_branch(
            repo_path, target_branch, description
        )
        return working_branch, True

    def format_protection_notice(self, branch: str, working_branch: str) -> str:
        """
        Format a user-friendly notice about branch protection redirect.

        Args:
            branch: The original protected branch.
            working_branch: The working branch that was created.

        Returns:
            Formatted notice string.
        """
        tier = self.get_protection_tier(branch)
        return (
            f"🛡️ Branch Protection Active\n"
            f"  Target branch '{branch}' is protected ({tier} tier).\n"
            f"  Created working branch: '{working_branch}'\n"
            f"  Make your changes on this branch, then create a Pull Request\n"
            f"  to merge into '{branch}'."
        )

    def list_protected_branches(self, repo_path: str) -> list[dict]:
        """
        List all protected branches in a repository.

        Args:
            repo_path: Path to the git repository.

        Returns:
            List of dicts with branch name, tier, and protected status.
        """
        all_branches = get_branches(repo_path)
        result = []
        for branch in all_branches:
            if self.is_protected(branch):
                result.append({
                    "branch": branch,
                    "tier": self.get_protection_tier(branch),
                    "protected": True,
                })
        return result


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_default_protection = BranchProtection()


def is_protected_branch(branch: str) -> bool:
    """Check if a branch is protected (module-level convenience)."""
    return _default_protection.is_protected(branch)


def validate_branch_for_edit(branch: str) -> None:
    """Validate a branch for direct editing (module-level convenience)."""
    _default_protection.validate_branch_for_edit(branch)


def create_working_branch(
    repo_path: str,
    source_branch: str,
    description: str = "",
) -> str:
    """Create a working branch from a protected branch (module-level convenience)."""
    return _default_protection.create_working_branch(repo_path, source_branch, description)


def get_safe_branch(
    repo_path: str,
    target_branch: str,
    description: str = "",
) -> tuple[str, bool]:
    """Get a safe branch for editing (module-level convenience)."""
    return _default_protection.get_safe_branch_for_edit(repo_path, target_branch, description)
