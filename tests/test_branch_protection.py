"""
Tests for Branch Protection Module

Validates:
    - Protected branch detection for all tier patterns
    - Working branch name generation
    - Branch protection validation (raises on protected branches)
    - Tier classification
    - Safe branch routing logic
    - Module-level convenience functions
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.branch_protection import (
    BranchProtection,
    ProtectionConfig,
    ProtectedBranchError,
    BranchCreationError,
    is_protected_branch,
    validate_branch_for_edit,
)


class TestBranchDetection(unittest.TestCase):
    """Test that protected branches are correctly identified."""

    def setUp(self):
        self.bp = BranchProtection()

    def test_main_is_protected(self):
        self.assertTrue(self.bp.is_protected("main"))

    def test_master_is_protected(self):
        self.assertTrue(self.bp.is_protected("master"))

    def test_develop_is_protected(self):
        self.assertTrue(self.bp.is_protected("develop"))

    def test_development_is_protected(self):
        self.assertTrue(self.bp.is_protected("development"))

    def test_release_underscore_is_protected(self):
        self.assertTrue(self.bp.is_protected("release_26_3"))

    def test_release_slash_is_protected(self):
        self.assertTrue(self.bp.is_protected("release/26.3"))

    def test_hotfix_slash_is_protected(self):
        self.assertTrue(self.bp.is_protected("hotfix/urgent-fix"))

    def test_hotfix_underscore_is_protected(self):
        self.assertTrue(self.bp.is_protected("hotfix_urgent-fix"))

    def test_feature_branch_is_not_protected(self):
        self.assertFalse(self.bp.is_protected("feature/add-new-thing"))

    def test_custom_branch_is_not_protected(self):
        self.assertFalse(self.bp.is_protected("my-working-branch"))

    def test_hivemind_branch_is_not_protected(self):
        self.assertFalse(self.bp.is_protected("hivemind/main-fix-config"))

    def test_origin_prefix_stripped(self):
        """Branches with origin/ prefix should still be detected."""
        self.assertTrue(self.bp.is_protected("origin/main"))
        self.assertTrue(self.bp.is_protected("origin/release_26_3"))

    def test_case_insensitive(self):
        """Branch names should be matched case-insensitively."""
        self.assertTrue(self.bp.is_protected("Main"))
        self.assertTrue(self.bp.is_protected("MAIN"))
        self.assertTrue(self.bp.is_protected("Release_26_3"))

    def test_disabled_protection(self):
        """When protection is disabled, nothing is protected."""
        config = ProtectionConfig(enabled=False)
        bp = BranchProtection(config)
        self.assertFalse(bp.is_protected("main"))
        self.assertFalse(bp.is_protected("release_26_3"))


class TestTierClassification(unittest.TestCase):
    """Test branch tier classification."""

    def setUp(self):
        self.bp = BranchProtection()

    def test_main_is_production(self):
        self.assertEqual(self.bp.get_protection_tier("main"), "production")

    def test_master_is_production(self):
        self.assertEqual(self.bp.get_protection_tier("master"), "production")

    def test_develop_is_integration(self):
        self.assertEqual(self.bp.get_protection_tier("develop"), "integration")

    def test_release_is_release(self):
        self.assertEqual(self.bp.get_protection_tier("release_26_3"), "release")

    def test_hotfix_is_hotfix(self):
        self.assertEqual(self.bp.get_protection_tier("hotfix/urgent"), "hotfix")

    def test_feature_is_feature(self):
        self.assertEqual(self.bp.get_protection_tier("feature/cool-thing"), "feature")

    def test_unknown_tier(self):
        self.assertEqual(self.bp.get_protection_tier("random-branch"), "unknown")


class TestValidation(unittest.TestCase):
    """Test branch validation raises on protected branches."""

    def setUp(self):
        self.bp = BranchProtection()

    def test_validate_raises_on_main(self):
        with self.assertRaises(ProtectedBranchError) as ctx:
            self.bp.validate_branch_for_edit("main")
        self.assertIn("main", str(ctx.exception))
        self.assertIn("production", str(ctx.exception))

    def test_validate_raises_on_release(self):
        with self.assertRaises(ProtectedBranchError):
            self.bp.validate_branch_for_edit("release_26_3")

    def test_validate_raises_on_hotfix(self):
        with self.assertRaises(ProtectedBranchError):
            self.bp.validate_branch_for_edit("hotfix/fix-login")

    def test_validate_passes_on_feature(self):
        # Should not raise
        self.bp.validate_branch_for_edit("feature/my-feature")

    def test_validate_passes_on_hivemind_branch(self):
        # Should not raise
        self.bp.validate_branch_for_edit("hivemind/main-fix-config")

    def test_validate_passes_on_custom_branch(self):
        # Should not raise
        self.bp.validate_branch_for_edit("my-working-branch")


class TestWorkingBranchNaming(unittest.TestCase):
    """Test working branch name generation."""

    def setUp(self):
        self.bp = BranchProtection()

    def test_name_with_description(self):
        name = self.bp.generate_working_branch_name("main", "fix-pipeline-config")
        self.assertEqual(name, "hivemind/main-fix-pipeline-config")

    def test_name_without_description_has_timestamp(self):
        name = self.bp.generate_working_branch_name("main")
        self.assertTrue(name.startswith("hivemind/main-"))
        # Timestamp suffix should be digits
        suffix = name.split("-", 2)[-1]
        self.assertTrue(suffix.isdigit())

    def test_name_with_release_branch(self):
        name = self.bp.generate_working_branch_name("release_26_3", "update-helm")
        self.assertEqual(name, "hivemind/release_26_3-update-helm")

    def test_name_sanitizes_description(self):
        name = self.bp.generate_working_branch_name("main", "fix pipeline config!!!")
        self.assertEqual(name, "hivemind/main-fix-pipeline-config")

    def test_name_with_slash_in_source(self):
        name = self.bp.generate_working_branch_name("release/26.3", "update")
        self.assertTrue(name.startswith("hivemind/release-26.3-"))

    def test_custom_prefix(self):
        config = ProtectionConfig(working_branch_prefix="workbranch")
        bp = BranchProtection(config)
        name = bp.generate_working_branch_name("main", "test")
        self.assertEqual(name, "workbranch/main-test")


class TestCreateWorkingBranch(unittest.TestCase):
    """Test working branch creation with mocked git operations."""

    def setUp(self):
        self.bp = BranchProtection()

    @patch("sync.branch_protection.run_git")
    def test_creates_branch_from_remote(self, mock_run_git):
        """Should create branch from origin/<source> when it exists."""
        # fetch succeeds, rev-parse for origin/main succeeds, checkout -b succeeds
        mock_run_git.side_effect = [
            (0, "", ""),              # fetch
            (0, "abc123", ""),        # rev-parse origin/main
            (0, "", ""),              # checkout -b
        ]

        result = self.bp.create_working_branch("/fake/repo", "main", "test-fix")

        self.assertEqual(result, "hivemind/main-test-fix")
        # Verify checkout was called with correct args
        calls = mock_run_git.call_args_list
        self.assertIn("checkout", calls[2][0][1])
        self.assertIn("-b", calls[2][0][1])

    @patch("sync.branch_protection.run_git")
    def test_falls_back_to_local_branch(self, mock_run_git):
        """Should fall back to local branch when remote not found."""
        mock_run_git.side_effect = [
            (0, "", ""),              # fetch
            (1, "", "not found"),     # rev-parse origin/main fails
            (0, "abc123", ""),        # rev-parse main succeeds
            (0, "", ""),              # checkout -b succeeds
        ]

        result = self.bp.create_working_branch("/fake/repo", "main", "test-fix")
        self.assertEqual(result, "hivemind/main-test-fix")

    @patch("sync.branch_protection.run_git")
    def test_raises_when_source_not_found(self, mock_run_git):
        """Should raise BranchCreationError when source branch doesn't exist."""
        mock_run_git.side_effect = [
            (0, "", ""),              # fetch
            (1, "", "not found"),     # rev-parse origin/main fails
            (1, "", "not found"),     # rev-parse main fails
        ]

        with self.assertRaises(BranchCreationError):
            self.bp.create_working_branch("/fake/repo", "main", "test-fix")

    @patch("sync.branch_protection.run_git")
    def test_raises_when_checkout_fails(self, mock_run_git):
        """Should raise BranchCreationError when git checkout fails."""
        mock_run_git.side_effect = [
            (0, "", ""),              # fetch
            (0, "abc123", ""),        # rev-parse origin/main
            (1, "", "branch exists"), # checkout -b fails
        ]

        with self.assertRaises(BranchCreationError):
            self.bp.create_working_branch("/fake/repo", "main", "test-fix")


class TestSafeBranchRouting(unittest.TestCase):
    """Test the get_safe_branch_for_edit routing logic."""

    def setUp(self):
        self.bp = BranchProtection()

    @patch("sync.branch_protection.run_git")
    def test_protected_branch_gets_redirected(self, mock_run_git):
        """Protected branch should be redirected to a working branch."""
        mock_run_git.side_effect = [
            (0, "", ""),
            (0, "abc123", ""),
            (0, "", ""),
        ]

        branch, was_redirected = self.bp.get_safe_branch_for_edit(
            "/fake/repo", "main", "fix-config"
        )

        self.assertTrue(was_redirected)
        self.assertEqual(branch, "hivemind/main-fix-config")

    def test_unprotected_branch_passes_through(self):
        """Unprotected branch should pass through without redirect."""
        branch, was_redirected = self.bp.get_safe_branch_for_edit(
            "/fake/repo", "feature/cool-thing"
        )

        self.assertFalse(was_redirected)
        self.assertEqual(branch, "feature/cool-thing")


class TestProtectionNotice(unittest.TestCase):
    """Test the user-friendly protection notice formatting."""

    def setUp(self):
        self.bp = BranchProtection()

    def test_notice_contains_branch_info(self):
        notice = self.bp.format_protection_notice("main", "hivemind/main-fix")
        self.assertIn("main", notice)
        self.assertIn("hivemind/main-fix", notice)
        self.assertIn("production", notice)
        self.assertIn("Pull Request", notice)

    def test_notice_for_release_branch(self):
        notice = self.bp.format_protection_notice("release_26_3", "hivemind/release_26_3-update")
        self.assertIn("release", notice)


class TestListProtectedBranches(unittest.TestCase):
    """Test listing protected branches in a repo."""

    def setUp(self):
        self.bp = BranchProtection()

    @patch("sync.branch_protection.get_branches")
    def test_lists_only_protected(self, mock_get_branches):
        mock_get_branches.return_value = [
            "main", "develop", "release_26_3", "feature/cool", "hivemind/main-fix"
        ]

        result = self.bp.list_protected_branches("/fake/repo")

        protected_names = [r["branch"] for r in result]
        self.assertIn("main", protected_names)
        self.assertIn("develop", protected_names)
        self.assertIn("release_26_3", protected_names)
        self.assertNotIn("feature/cool", protected_names)
        self.assertNotIn("hivemind/main-fix", protected_names)

    @patch("sync.branch_protection.get_branches")
    def test_includes_tier_info(self, mock_get_branches):
        mock_get_branches.return_value = ["main", "release_26_3"]

        result = self.bp.list_protected_branches("/fake/repo")

        tiers = {r["branch"]: r["tier"] for r in result}
        self.assertEqual(tiers["main"], "production")
        self.assertEqual(tiers["release_26_3"], "release")


class TestModuleLevelFunctions(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_is_protected_branch(self):
        self.assertTrue(is_protected_branch("main"))
        self.assertFalse(is_protected_branch("feature/test"))

    def test_validate_branch_for_edit_raises(self):
        with self.assertRaises(ProtectedBranchError):
            validate_branch_for_edit("main")

    def test_validate_branch_for_edit_passes(self):
        # Should not raise
        validate_branch_for_edit("my-custom-branch")


class TestCustomProtectionConfig(unittest.TestCase):
    """Test custom protection configuration."""

    def test_custom_patterns(self):
        """Custom patterns should override defaults."""
        config = ProtectionConfig(
            protected_patterns=[r"^prod$", r"^staging$"]
        )
        bp = BranchProtection(config)

        self.assertTrue(bp.is_protected("prod"))
        self.assertTrue(bp.is_protected("staging"))
        self.assertFalse(bp.is_protected("main"))  # Not in custom patterns

    def test_custom_prefix(self):
        config = ProtectionConfig(working_branch_prefix="safe")
        bp = BranchProtection(config)
        name = bp.generate_working_branch_name("main", "test")
        self.assertTrue(name.startswith("safe/"))


if __name__ == "__main__":
    unittest.main()
