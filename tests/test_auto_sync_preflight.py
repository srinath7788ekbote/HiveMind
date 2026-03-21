"""
Tests for Auto-Sync Pre-flight and Branch Safety Rules

Validates:
    - check_and_sync_if_stale: fresh detection, stale sync, network errors
    - propose_edit: rejects protected branches, rejects hivemind/* prefix,
      accepts standard prefixes (feat/*, fix/*, chore/*, refactor/*)
    - hivemind_ensure_fresh MCP tool registration

Uses only unittest (no pytest). Mocks git and sync operations.
"""

import json
import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# check_and_sync_if_stale Tests
# ---------------------------------------------------------------------------

class TestFreshBranchNoSync(unittest.TestCase):
    """Test that fresh branches do not trigger sync."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        # Create client config
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True)
        config = {
            "client_name": "testclient",
            "repos": [{
                "name": "test-repo",
                "path": str(self.test_dir / "repos" / "test-repo"),
                "type": "terraform",
                "branches": ["main"],
            }],
        }
        import yaml
        (client_dir / "repos.yaml").write_text(
            yaml.dump(config), encoding="utf-8"
        )
        # Create repo dir
        repo_dir = self.test_dir / "repos" / "test-repo"
        repo_dir.mkdir(parents=True)
        # Create sync state with known commit
        memory_dir = self.test_dir / "memory" / "testclient"
        memory_dir.mkdir(parents=True)
        state = {"test-repo/main": {"commit": "abc123", "synced_at": "2025-01-01 00:00"}}
        (memory_dir / "sync_state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("scripts.sync_kb._git_ls_remote")
    def test_fresh_branch_no_sync_triggered(self, mock_ls_remote):
        """When local commit matches remote, no sync is triggered."""
        from scripts.sync_kb import check_and_sync_if_stale

        # Remote returns same commit as local
        mock_ls_remote.return_value = "abc123"

        result = check_and_sync_if_stale(
            client="testclient",
            auto_sync=True,
            project_root=self.test_dir,
        )

        self.assertTrue(result["all_fresh"])
        self.assertEqual(len(result["synced"]), 0)
        self.assertEqual(len(result["errors"]), 0)
        self.assertEqual(result["checked"][0]["status"], "fresh")
        self.assertEqual(result["message"], "All branches fresh")


class TestStaleBranchSync(unittest.TestCase):
    """Test that stale branches trigger incremental sync."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True)
        config = {
            "client_name": "testclient",
            "repos": [{
                "name": "test-repo",
                "path": str(self.test_dir / "repos" / "test-repo"),
                "type": "terraform",
                "branches": ["main", "release_26_3"],
            }],
        }
        import yaml
        (client_dir / "repos.yaml").write_text(
            yaml.dump(config), encoding="utf-8"
        )
        repo_dir = self.test_dir / "repos" / "test-repo"
        repo_dir.mkdir(parents=True)
        memory_dir = self.test_dir / "memory" / "testclient"
        memory_dir.mkdir(parents=True)
        state = {
            "test-repo/main": {"commit": "abc123", "synced_at": "2025-01-01"},
            "test-repo/release_26_3": {"commit": "def456", "synced_at": "2025-01-01"},
        }
        (memory_dir / "sync_state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("scripts.sync_kb.sync_client")
    @patch("scripts.sync_kb._git_rev_list_count")
    @patch("scripts.sync_kb._git_ls_remote")
    def test_stale_branch_triggers_incremental_sync(
        self, mock_ls_remote, mock_rev_list, mock_sync
    ):
        """When remote commit differs, sync_client is called for stale branch."""
        from scripts.sync_kb import check_and_sync_if_stale

        def ls_remote_side_effect(repo_path, branch):
            if branch == "main":
                return "abc123"  # fresh
            return "new_commit_789"  # stale

        mock_ls_remote.side_effect = ls_remote_side_effect
        mock_rev_list.return_value = 3
        mock_sync.return_value = {"synced": 1, "skipped": 0, "errors": 0}

        result = check_and_sync_if_stale(
            client="testclient",
            auto_sync=True,
            project_root=self.test_dir,
        )

        self.assertFalse(result["all_fresh"])
        self.assertEqual(len(result["synced"]), 1)
        self.assertEqual(result["synced"][0]["repo"], "test-repo")
        self.assertEqual(result["synced"][0]["branch"], "release_26_3")

        # Verify sync_client was called with correct params
        mock_sync.assert_called_once()
        call_kwargs = mock_sync.call_args
        self.assertEqual(call_kwargs.kwargs.get("repo_filter") or call_kwargs[1].get("repo_filter"), "test-repo")


class TestNetworkErrorProceeds(unittest.TestCase):
    """Test that network errors don't block investigation."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True)
        config = {
            "client_name": "testclient",
            "repos": [{
                "name": "test-repo",
                "path": str(self.test_dir / "repos" / "test-repo"),
                "type": "terraform",
                "branches": ["main"],
            }],
        }
        import yaml
        (client_dir / "repos.yaml").write_text(
            yaml.dump(config), encoding="utf-8"
        )
        repo_dir = self.test_dir / "repos" / "test-repo"
        repo_dir.mkdir(parents=True)
        memory_dir = self.test_dir / "memory" / "testclient"
        memory_dir.mkdir(parents=True)
        state = {"test-repo/main": {"commit": "abc123", "synced_at": "2025-01-01"}}
        (memory_dir / "sync_state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("scripts.sync_kb._git_ls_remote")
    def test_network_error_proceeds_anyway(self, mock_ls_remote):
        """When git ls-remote fails, status is 'unknown' but no exception."""
        from scripts.sync_kb import check_and_sync_if_stale

        mock_ls_remote.return_value = None  # network failure

        result = check_and_sync_if_stale(
            client="testclient",
            auto_sync=True,
            project_root=self.test_dir,
        )

        # Should not raise, should return result
        self.assertIsInstance(result, dict)
        self.assertEqual(result["checked"][0]["status"], "unknown")
        self.assertGreater(len(result["errors"]), 0)
        self.assertIn("network", result["errors"][0].lower())


class TestCheckFreshnessReportOnly(unittest.TestCase):
    """Test check-freshness with auto_sync=False (report only mode)."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True)
        config = {
            "client_name": "testclient",
            "repos": [{
                "name": "test-repo",
                "path": str(self.test_dir / "repos" / "test-repo"),
                "type": "terraform",
                "branches": ["main"],
            }],
        }
        import yaml
        (client_dir / "repos.yaml").write_text(
            yaml.dump(config), encoding="utf-8"
        )
        repo_dir = self.test_dir / "repos" / "test-repo"
        repo_dir.mkdir(parents=True)
        memory_dir = self.test_dir / "memory" / "testclient"
        memory_dir.mkdir(parents=True)
        state = {"test-repo/main": {"commit": "old_commit", "synced_at": "2025-01-01"}}
        (memory_dir / "sync_state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("scripts.sync_kb.sync_client")
    @patch("scripts.sync_kb._git_rev_list_count")
    @patch("scripts.sync_kb._git_ls_remote")
    def test_report_only_does_not_sync(self, mock_ls_remote, mock_rev_list, mock_sync):
        """When auto_sync=False, stale branches are reported but not synced."""
        from scripts.sync_kb import check_and_sync_if_stale

        mock_ls_remote.return_value = "new_commit"
        mock_rev_list.return_value = 5

        result = check_and_sync_if_stale(
            client="testclient",
            auto_sync=False,
            project_root=self.test_dir,
        )

        self.assertFalse(result["all_fresh"])
        self.assertEqual(len(result["synced"]), 0)
        self.assertEqual(result["checked"][0]["status"], "stale")
        self.assertEqual(result["checked"][0]["commits_behind"], 5)
        mock_sync.assert_not_called()


# ---------------------------------------------------------------------------
# propose_edit Branch Safety Tests
# ---------------------------------------------------------------------------

class TestProposeEditRejectsProtectedBranch(unittest.TestCase):
    """Test that propose_edit blocks edits to protected branches."""

    @patch("tools.propose_edit.hm_read_file")
    def test_rejects_main_branch(self, mock_read):
        """propose_edit returns blocked action for main branch."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="main",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")
        self.assertIn("protected", result["note"].lower())
        self.assertIn("feat/", result["note"])
        mock_read.assert_not_called()

    @patch("tools.propose_edit.hm_read_file")
    def test_rejects_release_branch(self, mock_read):
        """propose_edit returns blocked action for release branches."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="release_26_3",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")
        mock_read.assert_not_called()


class TestProposeEditRejectsHivemindPrefix(unittest.TestCase):
    """Test that propose_edit blocks hivemind/* branch prefix."""

    @patch("tools.propose_edit.hm_read_file")
    def test_rejects_hivemind_prefix(self, mock_read):
        """propose_edit returns blocked action for hivemind/* branches."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="hivemind/main-fix",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")
        self.assertIn("hivemind", result["note"].lower())
        self.assertIn("feat/", result["note"])
        mock_read.assert_not_called()


class TestProposeEditAcceptsStandardPrefixes(unittest.TestCase):
    """Test that propose_edit allows standard branch prefixes."""

    @patch("tools.propose_edit.hm_read_file")
    def test_accepts_feat_prefix(self, mock_read):
        """propose_edit proceeds with feat/* branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="feat/add-feature",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertNotEqual(result["action"], "blocked")

    @patch("tools.propose_edit.hm_read_file")
    def test_accepts_fix_prefix(self, mock_read):
        """propose_edit proceeds with fix/* branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {"content": "old", "source": "disk"}

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="fix/bug-fix",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertNotEqual(result["action"], "blocked")

    @patch("tools.propose_edit.hm_read_file")
    def test_accepts_chore_prefix(self, mock_read):
        """propose_edit proceeds with chore/* branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {"content": "old", "source": "disk"}

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="chore/cleanup",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertNotEqual(result["action"], "blocked")

    @patch("tools.propose_edit.hm_read_file")
    def test_accepts_refactor_prefix(self, mock_read):
        """propose_edit proceeds with refactor/* branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {"content": "old", "source": "disk"}

        result = propose_edit(
            client="testclient",
            repo="test-repo",
            file_path="some/file.yaml",
            branch="refactor/restructure",
            description="test edit",
            proposed_changes="new content",
        )

        self.assertNotEqual(result["action"], "blocked")


# ---------------------------------------------------------------------------
# MCP Tool Registration Test
# ---------------------------------------------------------------------------

class TestEnsureFreshMCPRegistration(unittest.TestCase):
    """Test that hivemind_ensure_fresh is registered in the MCP server."""

    def test_ensure_fresh_in_tool_registry(self):
        """hivemind_ensure_fresh is in the TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY

        self.assertIn("hivemind_ensure_fresh", TOOL_REGISTRY)
        self.assertTrue(callable(TOOL_REGISTRY["hivemind_ensure_fresh"]))


if __name__ == "__main__":
    unittest.main()
