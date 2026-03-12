"""
Unit Tests — Check Branch

Tests tools/check_branch.py

Covers:
    - Branch indexed → returns indexed=true immediately, no remote check
    - Branch not indexed but exists on remote → returns exists_on_remote=true
    - Branch not indexed and not on remote → returns exists_on_remote=false with suggestions
    - Fuzzy suggestion picks closest branch name (release_26_1 → release_26_2 not release_12_18)
    - Missing repo in repos.yaml → clear error message
    - git ls-remote failure (no network) → graceful fallback, returns exists_on_remote=unknown
    - Edge cases: empty candidates, single candidate, non-release branches

Note: Uses mocked git/branch operations to avoid touching real repos or network.
"""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestCheckBranch(HiveMindTestCase):
    """Tests for tools/check_branch.py with mocked git and index operations."""

    def setUp(self):
        super().setUp()
        # Create a fake client config
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True, exist_ok=True)

        # Create a fake repo path that actually exists on disk
        self.fake_repo_path = self.test_dir / "fake_repos" / "test-repo"
        self.fake_repo_path.mkdir(parents=True, exist_ok=True)

        # Use forward slashes in YAML to avoid escape issues
        repo_path_str = str(self.fake_repo_path).replace("\\", "/")
        (client_dir / "repos.yaml").write_text(
            'repos:\n'
            '  - name: test-repo\n'
            f'    path: "{repo_path_str}"\n'
            '    type: infrastructure\n'
            '    branches:\n'
            '      - main\n'
            '      - release_26_1\n'
            '      - release_26_2\n',
            encoding="utf-8",
        )

        # Create a branch_index.json with some indexed branches
        index_path = self.memory_dir / "branch_index.json"
        index_data = {
            "test-repo:main": {
                "repo": "test-repo",
                "branch": "main",
                "tier": "production",
                "indexed_at": "2026-03-01T12:00:00Z",
                "commit_hash": "abc123",
            },
            "test-repo:release_26_2": {
                "repo": "test-repo",
                "branch": "release_26_2",
                "tier": "release",
                "indexed_at": "2026-03-02T12:00:00Z",
                "commit_hash": "def456",
            },
            "test-repo:release_12_18": {
                "repo": "test-repo",
                "branch": "release_12_18",
                "tier": "release",
                "indexed_at": "2026-02-15T12:00:00Z",
                "commit_hash": "ghi789",
            },
        }
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index_data, f)

    def _check(self, client="testclient", repo="test-repo", branch="main",
               ls_remote_output="", ls_remote_returncode=0,
               ls_remote_side_effect=None):
        """Helper: run check_branch with mocked PROJECT_ROOT and subprocess."""
        import tools.check_branch as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            with patch("subprocess.run") as mock_run:
                if ls_remote_side_effect:
                    mock_run.side_effect = ls_remote_side_effect
                else:
                    mock_result = MagicMock()
                    mock_result.stdout = ls_remote_output
                    mock_result.returncode = ls_remote_returncode
                    mock_run.return_value = mock_result

                return mod.check_branch(client=client, repo=repo, branch=branch)
        finally:
            mod.PROJECT_ROOT = original_root

    # -----------------------------------------------------------------
    # 1. Branch is indexed → returns indexed=true, no remote check
    # -----------------------------------------------------------------

    def test_indexed_branch_returns_true(self):
        """Indexed branch returns indexed=True immediately."""
        result = self._check(branch="main")
        self.assertTrue(result["indexed"])

    def test_indexed_branch_exists_on_remote_true(self):
        """If indexed, exists_on_remote is True (it existed at index time)."""
        result = self._check(branch="main")
        self.assertTrue(result["exists_on_remote"])

    def test_indexed_branch_no_subprocess_call(self):
        """When branch is indexed, git ls-remote should NOT be called."""
        import tools.check_branch as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            with patch("subprocess.run") as mock_run:
                mod.check_branch(client="testclient", repo="test-repo", branch="main")
                mock_run.assert_not_called()
        finally:
            mod.PROJECT_ROOT = original_root

    def test_indexed_branch_suggestion_is_none(self):
        """Indexed branch needs no suggestion."""
        result = self._check(branch="main")
        self.assertIsNone(result["suggestion"])

    def test_indexed_branch_has_indexed_branches_list(self):
        """Result always includes the indexed_branches list."""
        result = self._check(branch="main")
        self.assertIn("indexed_branches", result)
        self.assertIsInstance(result["indexed_branches"], list)

    # -----------------------------------------------------------------
    # 2. Branch not indexed, exists on remote
    # -----------------------------------------------------------------

    def test_not_indexed_exists_on_remote(self):
        """Unindexed branch that exists on remote returns exists_on_remote=True."""
        ls_output = "abc123def456\trefs/heads/release_26_1\n"
        result = self._check(branch="release_26_1", ls_remote_output=ls_output)
        self.assertFalse(result["indexed"])
        self.assertTrue(result["exists_on_remote"])

    def test_not_indexed_exists_on_remote_has_suggestion(self):
        """Unindexed branch gets a suggestion for the closest indexed branch."""
        ls_output = "abc123def456\trefs/heads/release_26_1\n"
        result = self._check(branch="release_26_1", ls_remote_output=ls_output)
        self.assertIsNotNone(result["suggestion"])

    # -----------------------------------------------------------------
    # 3. Branch not indexed, not on remote
    # -----------------------------------------------------------------

    def test_not_indexed_not_on_remote(self):
        """Branch that doesn't exist returns exists_on_remote=False."""
        result = self._check(branch="release_99_99", ls_remote_output="")
        self.assertFalse(result["indexed"])
        self.assertFalse(result["exists_on_remote"])

    def test_not_on_remote_has_suggestion(self):
        """Even when not on remote, suggestions are provided."""
        result = self._check(branch="release_99_99", ls_remote_output="")
        self.assertIn("suggestion", result)

    def test_not_on_remote_lists_indexed_branches(self):
        """Indexed branches list is always returned."""
        result = self._check(branch="release_99_99", ls_remote_output="")
        self.assertGreater(len(result["indexed_branches"]), 0)

    # -----------------------------------------------------------------
    # 4. Fuzzy suggestion picks closest branch name
    # -----------------------------------------------------------------

    def test_suggestion_release_26_1_gets_release_26_2(self):
        """release_26_1 should suggest release_26_2, not release_12_18."""
        result = self._check(branch="release_26_1", ls_remote_output="")
        self.assertEqual(result["suggestion"], "release_26_2")

    def test_suggestion_release_26_3_gets_release_26_2(self):
        """release_26_3 should suggest release_26_2 (closest version)."""
        result = self._check(branch="release_26_3", ls_remote_output="")
        self.assertEqual(result["suggestion"], "release_26_2")

    def test_suggestion_release_12_17_gets_release_12_18(self):
        """release_12_17 should suggest release_12_18 (closest version)."""
        result = self._check(branch="release_12_17", ls_remote_output="")
        self.assertEqual(result["suggestion"], "release_12_18")

    # -----------------------------------------------------------------
    # 5. Missing repo in repos.yaml → clear error
    # -----------------------------------------------------------------

    def test_missing_repo_returns_error(self):
        """Non-existent repo returns error with available repos listed."""
        result = self._check(repo="nonexistent-repo")
        self.assertIn("error", result)
        self.assertIn("nonexistent-repo", result["error"])
        self.assertIn("test-repo", result["error"])

    def test_missing_repo_error_includes_repo_name(self):
        """Error message mentions which repo was not found."""
        result = self._check(repo="does-not-exist")
        self.assertIn("does-not-exist", result["error"])

    # -----------------------------------------------------------------
    # 6. Missing client config → clear error
    # -----------------------------------------------------------------

    def test_missing_client_returns_error(self):
        """Non-existent client returns error."""
        result = self._check(client="nonexistent-client")
        self.assertIn("error", result)
        self.assertIn("nonexistent-client", result["error"])

    # -----------------------------------------------------------------
    # 7. git ls-remote failure → graceful fallback
    # -----------------------------------------------------------------

    def test_ls_remote_nonzero_exit_returns_unknown(self):
        """git ls-remote non-zero exit → exists_on_remote='unknown'."""
        result = self._check(branch="release_26_1", ls_remote_returncode=128)
        self.assertFalse(result["indexed"])
        self.assertEqual(result["exists_on_remote"], "unknown")

    def test_ls_remote_timeout_returns_unknown(self):
        """git ls-remote timeout → exists_on_remote='unknown'."""
        import subprocess
        result = self._check(
            branch="release_26_1",
            ls_remote_side_effect=subprocess.TimeoutExpired("git", 30),
        )
        self.assertEqual(result["exists_on_remote"], "unknown")

    def test_ls_remote_os_error_returns_unknown(self):
        """git ls-remote OSError → exists_on_remote='unknown'."""
        result = self._check(
            branch="release_26_1",
            ls_remote_side_effect=OSError("No git"),
        )
        self.assertEqual(result["exists_on_remote"], "unknown")

    def test_ls_remote_file_not_found_returns_unknown(self):
        """git ls-remote FileNotFoundError → exists_on_remote='unknown'."""
        result = self._check(
            branch="release_26_1",
            ls_remote_side_effect=FileNotFoundError("git not installed"),
        )
        self.assertEqual(result["exists_on_remote"], "unknown")

    # -----------------------------------------------------------------
    # 8. Return structure validation
    # -----------------------------------------------------------------

    def test_result_has_required_keys_indexed(self):
        """Indexed result has all required keys."""
        result = self._check(branch="main")
        for key in ["indexed", "exists_on_remote", "repo", "branch",
                     "indexed_branches", "suggestion"]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_result_has_required_keys_not_indexed(self):
        """Unindexed result has all required keys."""
        result = self._check(branch="release_99_99", ls_remote_output="")
        for key in ["indexed", "exists_on_remote", "repo", "branch",
                     "indexed_branches", "suggestion"]:
            self.assertIn(key, result, f"Missing key: {key}")

    def test_error_result_has_repo_and_branch(self):
        """Error results always include repo and branch."""
        result = self._check(repo="nonexistent-repo")
        self.assertIn("repo", result)
        self.assertIn("branch", result)

    # -----------------------------------------------------------------
    # 9. Edge cases for _find_closest_branch
    # -----------------------------------------------------------------

    def test_suggestion_with_no_candidates(self):
        """No indexed branches → suggestion is None."""
        from tools.check_branch import _find_closest_branch
        self.assertIsNone(_find_closest_branch("release_26_1", []))

    def test_suggestion_with_single_candidate(self):
        """Single indexed branch → that's the suggestion."""
        from tools.check_branch import _find_closest_branch
        self.assertEqual(
            _find_closest_branch("release_26_1", ["main"]),
            "main",
        )

    def test_suggestion_non_release_branch(self):
        """Non-release branch uses string similarity."""
        from tools.check_branch import _find_closest_branch
        result = _find_closest_branch("develop", ["main", "development", "release_26_2"])
        self.assertEqual(result, "development")

    # -----------------------------------------------------------------
    # 10. _parse_release_version unit tests
    # -----------------------------------------------------------------

    def test_parse_release_underscore(self):
        """release_26_1 → 26.01."""
        from tools.check_branch import _parse_release_version
        ver = _parse_release_version("release_26_1")
        self.assertIsNotNone(ver)
        self.assertAlmostEqual(ver, 26.01, places=2)

    def test_parse_release_slash(self):
        """release/26.3 → parses correctly."""
        from tools.check_branch import _parse_release_version
        ver = _parse_release_version("release/26.3")
        self.assertIsNotNone(ver)

    def test_parse_non_release(self):
        """main → None (not a release branch)."""
        from tools.check_branch import _parse_release_version
        ver = _parse_release_version("main")
        self.assertIsNone(ver)

    def test_parse_feature_branch(self):
        """feature/my-feature → None."""
        from tools.check_branch import _parse_release_version
        ver = _parse_release_version("feature/my-feature")
        self.assertIsNone(ver)

    # -----------------------------------------------------------------
    # 11. ls-remote output parsing edge cases
    # -----------------------------------------------------------------

    def test_ls_remote_wrong_branch_name_returns_false(self):
        """ls-remote returns a different branch → exists_on_remote=False."""
        ls_output = "abc123def456\trefs/heads/release_26_2\n"
        result = self._check(branch="release_26_1", ls_remote_output=ls_output)
        self.assertFalse(result["exists_on_remote"])

    def test_ls_remote_multiple_refs_finds_match(self):
        """ls-remote returns multiple refs, one matches."""
        ls_output = (
            "abc123\trefs/heads/release_26_2\n"
            "def456\trefs/heads/release_26_1\n"
        )
        result = self._check(branch="release_26_1", ls_remote_output=ls_output)
        self.assertTrue(result["exists_on_remote"])

    # -----------------------------------------------------------------
    # 12. Repo path does not exist → remote check returns unknown
    # -----------------------------------------------------------------

    def test_repo_path_missing_returns_remote_unknown(self):
        """If repo path doesn't exist, remote check returns 'unknown'."""
        # Write a config with a non-existent path
        client_dir = self.test_dir / "clients" / "testclient"
        (client_dir / "repos.yaml").write_text(
            'repos:\n'
            '  - name: test-repo\n'
            '    path: "C:/does/not/exist"\n'
            '    type: infrastructure\n',
            encoding="utf-8",
        )
        result = self._check(branch="release_26_1", ls_remote_output="")
        self.assertFalse(result["indexed"])
        self.assertEqual(result["exists_on_remote"], "unknown")


if __name__ == "__main__":
    unittest.main()
