"""
Unit Tests — Diff Branches

Tests tools/diff_branches.py

Covers:
    - diff_branches() result structure
    - Parsing git diff --name-status output (A/M/D)
    - File classification per type
    - Category counting
    - Summary generation
    - Error paths (missing config, repo, path)
    - No-diff case

Note: Uses mocked git_diff to avoid touching real repos.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO


class TestDiffBranches(HiveMindTestCase):
    """Tests for tools/diff_branches.py with mocked git operations."""

    def setUp(self):
        super().setUp()
        # Create a client config pointing to fixture repo (it exists on disk)
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True, exist_ok=True)
        repos_yaml = client_dir / "repos.yaml"
        repos_yaml.write_text(
            f"repos:\n"
            f"  - name: fake-harness\n"
            f"    path: {FAKE_HARNESS_REPO}\n"
            f"    type: cicd/harness\n",
            encoding="utf-8",
        )

    def _diff(self, repo="fake-harness", base="main", compare="develop", mock_output=None):
        import tools.diff_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir

        # Default mock output simulating git diff --name-status
        if mock_output is None:
            mock_output = (
                "A\tpipelines/new_pipeline.yaml\n"
                "M\tpipelines/deploy_audit.yaml\n"
                "M\ttemplates/rollout_k8s.yaml\n"
                "D\tpipelines/old_pipeline.yaml\n"
            )

        try:
            with patch("sync.git_utils.diff_branches", return_value=mock_output):
                return mod.diff_branches("testclient", repo, base, compare)
        finally:
            mod.PROJECT_ROOT = original_root

    # --- Result structure ---

    def test_result_has_required_keys(self):
        result = self._diff()
        for key in ["repo", "base", "compare", "files_added", "files_modified", "files_deleted", "categories", "summary"]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_repo_base_compare_in_result(self):
        result = self._diff()
        self.assertEqual(result["repo"], "fake-harness")
        self.assertEqual(result["base"], "main")
        self.assertEqual(result["compare"], "develop")

    # --- File classification ---

    def test_added_files(self):
        result = self._diff()
        self.assertEqual(len(result["files_added"]), 1)
        self.assertIn("new_pipeline.yaml", result["files_added"][0]["path"])

    def test_modified_files(self):
        result = self._diff()
        self.assertEqual(len(result["files_modified"]), 2)

    def test_deleted_files(self):
        result = self._diff()
        self.assertEqual(len(result["files_deleted"]), 1)

    def test_files_have_path_and_type(self):
        result = self._diff()
        for file_list in [result["files_added"], result["files_modified"], result["files_deleted"]]:
            for f in file_list:
                self.assertIn("path", f)
                self.assertIn("type", f)

    # --- Categories ---

    def test_categories_populated(self):
        result = self._diff()
        self.assertGreater(len(result["categories"]), 0)

    def test_categories_are_counts(self):
        result = self._diff()
        for cat, count in result["categories"].items():
            self.assertIsInstance(count, int)
            self.assertGreater(count, 0)

    # --- Summary ---

    def test_summary_is_string(self):
        result = self._diff()
        self.assertIsInstance(result["summary"], str)
        self.assertGreater(len(result["summary"]), 0)

    def test_summary_contains_branch_names(self):
        result = self._diff()
        self.assertIn("main", result["summary"])
        self.assertIn("develop", result["summary"])

    def test_summary_contains_counts(self):
        result = self._diff()
        self.assertIn("Added:", result["summary"])
        self.assertIn("Modified:", result["summary"])
        self.assertIn("Deleted:", result["summary"])

    # --- No diff ---

    def test_no_diff_returns_empty(self):
        result = self._diff(mock_output="")
        self.assertEqual(result["files_added"], [])
        self.assertEqual(result["files_modified"], [])
        self.assertEqual(result["files_deleted"], [])

    def test_no_diff_returns_none(self):
        result = self._diff(mock_output=None)
        # When git_diff returns None
        import tools.diff_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            with patch("sync.git_utils.diff_branches", return_value=None):
                result = mod.diff_branches("testclient", "fake-harness", "main", "develop")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertIn("No differences", result["summary"])

    # --- Mixed file types ---

    def test_terraform_changes(self):
        mock = "M\tlayer_01_keyvaults/main.tf\nA\tlayer_02_aks/variables.tf\n"
        # Need a config with terraform repo type
        client_dir = self.test_dir / "clients" / "testclient"
        (client_dir / "repos.yaml").write_text(
            f"repos:\n"
            f"  - name: fake-harness\n"
            f"    path: {FAKE_HARNESS_REPO}\n"
            f"    type: infrastructure/terraform\n",
            encoding="utf-8",
        )
        result = self._diff(mock_output=mock)
        types = [f["type"] for f in result["files_modified"] + result["files_added"]]
        self.assertTrue(any(t == "terraform" for t in types))

    # --- Error paths ---

    def test_missing_config(self):
        import tools.diff_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir / "nonexistent"
        try:
            result = mod.diff_branches("testclient", "repo", "main", "dev")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertIn("error", result)

    def test_missing_repo(self):
        result = self._diff(repo="nonexistent-repo")
        self.assertIn("error", result)

    def test_missing_repo_path(self):
        """Repo exists in config but path doesn't exist on disk."""
        client_dir = self.test_dir / "clients" / "testclient"
        (client_dir / "repos.yaml").write_text(
            "repos:\n"
            "  - name: ghost-repo\n"
            "    path: /tmp/nonexistent_path_xyz_123\n"
            "    type: cicd/harness\n",
            encoding="utf-8",
        )
        import tools.diff_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            result = mod.diff_branches("testclient", "ghost-repo", "main", "dev")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertIn("error", result)


class TestDiffBranchesOnlyAdded(HiveMindTestCase):
    """Edge case: all files are newly added."""

    def setUp(self):
        super().setUp()
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True, exist_ok=True)
        (client_dir / "repos.yaml").write_text(
            f"repos:\n"
            f"  - name: fake-harness\n"
            f"    path: {FAKE_HARNESS_REPO}\n"
            f"    type: cicd/harness\n",
            encoding="utf-8",
        )

    def test_all_added(self):
        import tools.diff_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        mock = "A\tnew1.yaml\nA\tnew2.yaml\nA\tnew3.yaml\n"
        try:
            with patch("sync.git_utils.diff_branches", return_value=mock):
                result = mod.diff_branches("testclient", "fake-harness", "main", "feature")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(len(result["files_added"]), 3)
        self.assertEqual(len(result["files_modified"]), 0)
        self.assertEqual(len(result["files_deleted"]), 0)


if __name__ == "__main__":
    unittest.main()
