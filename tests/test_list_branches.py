"""
Unit Tests — List Branches

Tests tools/list_branches.py

Covers:
    - list_branches() result structure
    - Tier classification (via mocked git output)
    - Sorting order (production first)
    - Missing config / path handling
    - "all" vs specific repo filtering

Note: Uses mocked git/branch operations to avoid touching real repos.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO


class TestListBranches(HiveMindTestCase):
    """Tests for tools/list_branches.py with mocked git operations."""

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

        # Create a branch_index.json
        import json
        index_path = self.memory_dir / "branch_index.json"
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump({
                "fake-harness": {
                    "main": {"indexed": True, "last_commit": "abc123"},
                    "develop": {"indexed": True, "last_commit": "def456"},
                }
            }, f)

    def _list(self, repo="all"):
        import tools.list_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir

        # Mock external dependencies
        mock_branches = ["main", "develop", "release_26_1", "feature/new-svc", "hotfix/bug-123"]
        mock_classify = lambda b: {
            "main": "production",
            "develop": "integration",
            "release_26_1": "release",
            "feature/new-svc": "feature",
            "hotfix/bug-123": "hotfix",
        }.get(b, "unknown")

        try:
            with patch("sync.git_utils.get_branches", return_value=mock_branches), \
                 patch("sync.git_utils.get_last_commit_time", return_value="2026-03-01T12:00:00"), \
                 patch("ingest.branch_indexer.classify_branch_tier", side_effect=mock_classify), \
                 patch("ingest.branch_indexer.BranchIndex") as MockIndex:
                # Mock the index instance
                mock_index = MagicMock()
                mock_index.is_indexed.side_effect = lambda repo, branch: branch in ["main", "develop"]
                MockIndex.return_value = mock_index

                return mod.list_branches("testclient", repo)
        finally:
            mod.PROJECT_ROOT = original_root

    # --- Result structure ---

    def test_returns_list(self):
        results = self._list()
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)

    def test_repo_info_has_required_keys(self):
        results = self._list()
        for repo_info in results:
            if repo_info.get("error"):
                continue
            self.assertIn("repo", repo_info)
            self.assertIn("branches", repo_info)
            self.assertIn("total_branches", repo_info)

    def test_branch_has_required_keys(self):
        results = self._list()
        for repo_info in results:
            if repo_info.get("error"):
                continue
            for branch in repo_info["branches"]:
                self.assertIn("name", branch)
                self.assertIn("tier", branch)
                self.assertIn("indexed", branch)

    # --- Branch count ---

    def test_branch_count(self):
        results = self._list()
        self.assertEqual(results[0]["total_branches"], 5)

    # --- Tier classification ---

    def test_main_is_production(self):
        results = self._list()
        branches = results[0]["branches"]
        main_branch = [b for b in branches if b["name"] == "main"][0]
        self.assertEqual(main_branch["tier"], "production")

    def test_develop_is_integration(self):
        results = self._list()
        branches = results[0]["branches"]
        dev = [b for b in branches if b["name"] == "develop"][0]
        self.assertEqual(dev["tier"], "integration")

    def test_release_branch_tier(self):
        results = self._list()
        branches = results[0]["branches"]
        rel = [b for b in branches if b["name"] == "release_26_1"][0]
        self.assertEqual(rel["tier"], "release")

    def test_feature_branch_tier(self):
        results = self._list()
        branches = results[0]["branches"]
        feat = [b for b in branches if b["name"] == "feature/new-svc"][0]
        self.assertEqual(feat["tier"], "feature")

    # --- Sorting ---

    def test_production_first(self):
        results = self._list()
        branches = results[0]["branches"]
        self.assertEqual(branches[0]["tier"], "production")

    def test_feature_last(self):
        results = self._list()
        branches = results[0]["branches"]
        # Feature branches should come after production/integration/release
        feature_idx = next(i for i, b in enumerate(branches) if b["tier"] == "feature")
        prod_idx = next(i for i, b in enumerate(branches) if b["tier"] == "production")
        self.assertGreater(feature_idx, prod_idx)

    # --- Repo filtering ---

    def test_specific_repo(self):
        results = self._list(repo="fake-harness")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["repo"], "fake-harness")

    # --- Indexed flag ---

    def test_indexed_branches_flagged(self):
        results = self._list()
        branches = results[0]["branches"]
        main_branch = [b for b in branches if b["name"] == "main"][0]
        self.assertTrue(main_branch["indexed"])

    def test_non_indexed_branches_flagged(self):
        results = self._list()
        branches = results[0]["branches"]
        feat = [b for b in branches if b["name"] == "feature/new-svc"][0]
        self.assertFalse(feat["indexed"])

    # --- Error paths ---

    def test_missing_config(self):
        import tools.list_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir / "nonexistent"
        try:
            results = mod.list_branches("testclient")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(len(results), 1)
        self.assertIn("error", results[0])

    def test_missing_repo_path(self):
        """Config points to non-existent path."""
        client_dir = self.test_dir / "clients" / "testclient"
        (client_dir / "repos.yaml").write_text(
            "repos:\n"
            "  - name: ghost-repo\n"
            "    path: /nonexistent/path/xyz\n"
            "    type: cicd/harness\n",
            encoding="utf-8",
        )
        import tools.list_branches as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            with patch("ingest.branch_indexer.BranchIndex") as MockIndex:
                MockIndex.return_value = MagicMock()
                results = mod.list_branches("testclient")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(len(results), 1)
        self.assertIn("error", results[0])


if __name__ == "__main__":
    unittest.main()
