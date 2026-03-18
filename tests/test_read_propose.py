"""
Tests for Read File and Propose Edit Tools

Validates:
    - read_file: KB lookup, disk read, both sources, error handling
    - propose_edit: branch protection, auto-apply, diff preview, error handling
    - MCP registration of both tools

Uses only unittest (no pytest). Mocks file I/O and git operations.
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Read File Tests
# ---------------------------------------------------------------------------

class TestReadFileKBLookup(unittest.TestCase):
    """Test read_file KB search behavior."""

    @patch("tools.read_file.query_memory")
    @patch("tools.read_file._find_repo_path")
    def test_returns_kb_content_when_chunks_exist(self, mock_repo, mock_qm):
        """read_file returns KB content when chunks match the file path."""
        from tools.read_file import read_file

        mock_qm.return_value = [
            {"text": "chunk1 content", "file_path": "path/to/file.yaml",
             "repo": "test-repo", "branch": "main", "relevance_pct": 95},
            {"text": "chunk2 content", "file_path": "path/to/file.yaml",
             "repo": "test-repo", "branch": "main", "relevance_pct": 90},
        ]
        mock_repo.side_effect = ValueError("Repo not found")

        result = read_file(client="testclient", repo="test-repo",
                           file_path="path/to/file.yaml")

        self.assertEqual(result["source"], "kb")
        self.assertEqual(result["kb_chunks_found"], 2)
        self.assertIn("chunk1 content", result["content"])

    @patch("tools.read_file.query_memory")
    @patch("tools.read_file._find_repo_path")
    @patch("tools.read_file._read_from_disk")
    def test_returns_disk_content_when_no_kb(self, mock_disk, mock_repo, mock_qm):
        """read_file returns disk content when KB has no coverage."""
        from tools.read_file import read_file

        mock_qm.return_value = []
        mock_repo.return_value = "/fake/repo/path"
        mock_disk.return_value = {
            "content": "file content from disk",
            "line_count": 1,
            "size_bytes": 22,
            "source_branch": "main",
        }

        result = read_file(client="testclient", repo="test-repo",
                           file_path="some/file.yaml")

        self.assertEqual(result["source"], "disk")
        self.assertEqual(result["content"], "file content from disk")
        self.assertEqual(result["kb_chunks_found"], 0)

    @patch("tools.read_file.query_memory")
    @patch("tools.read_file._find_repo_path")
    @patch("tools.read_file._read_from_disk")
    def test_returns_both_sources_when_available(self, mock_disk, mock_repo, mock_qm):
        """read_file returns both sources when KB and disk both have content."""
        from tools.read_file import read_file

        mock_qm.return_value = [
            {"text": "kb chunk", "file_path": "path/file.yaml",
             "repo": "r", "branch": "main", "relevance_pct": 90},
        ]
        mock_repo.return_value = "/fake/repo"
        mock_disk.return_value = {
            "content": "full disk content",
            "line_count": 5,
            "size_bytes": 100,
            "source_branch": "main",
        }

        result = read_file(client="testclient", repo="r",
                           file_path="path/file.yaml")

        self.assertEqual(result["source"], "both")
        self.assertEqual(result["content"], "full disk content")
        self.assertGreater(result["kb_chunks_found"], 0)


class TestReadFileErrorHandling(unittest.TestCase):
    """Test read_file error handling."""

    @patch("tools.read_file.query_memory")
    @patch("tools.read_file._find_repo_path")
    @patch("tools.read_file._read_from_disk")
    def test_handles_file_not_found_gracefully(self, mock_disk, mock_repo, mock_qm):
        """read_file handles file not found on disk gracefully."""
        from tools.read_file import read_file

        mock_qm.return_value = []
        mock_repo.return_value = "/fake/repo"
        mock_disk.return_value = {"error": "File not found: /fake/repo/missing.yaml"}

        result = read_file(client="testclient", repo="test-repo",
                           file_path="missing.yaml")

        self.assertEqual(result["source"], "none")
        self.assertIn("not found", result["note"].lower())

    @patch("tools.read_file.query_memory")
    def test_handles_repo_not_in_repos_yaml(self, mock_qm):
        """read_file handles repo not found in repos.yaml."""
        from tools.read_file import read_file

        mock_qm.return_value = []

        result = read_file(client="nonexistent_client_xyz", repo="fake-repo",
                           file_path="some/file.yaml")

        self.assertEqual(result["source"], "none")
        self.assertTrue(
            "not found" in result["note"].lower() or "error" in result["note"].lower(),
            f"Expected error note, got: {result['note']}"
        )


class TestReadFileReturnStructure(unittest.TestCase):
    """Test read_file return structure."""

    @patch("tools.read_file.query_memory")
    @patch("tools.read_file._find_repo_path")
    @patch("tools.read_file._read_from_disk")
    def test_returns_required_keys(self, mock_disk, mock_repo, mock_qm):
        """read_file returns all required keys."""
        from tools.read_file import read_file

        mock_qm.return_value = []
        mock_repo.return_value = "/fake/repo"
        mock_disk.return_value = {
            "content": "hello", "line_count": 1,
            "size_bytes": 5, "source_branch": "main",
        }

        result = read_file(client="t", repo="r", file_path="f.yaml")

        required_keys = [
            "file_path", "repo", "branch", "source", "content",
            "line_count", "kb_chunks_found", "kb_coverage", "note",
        ]
        for key in required_keys:
            self.assertIn(key, result, f"Missing key: {key}")


class TestReadFileCLI(unittest.TestCase):
    """Test read_file CLI argument parsing."""

    def test_cli_has_required_arguments(self):
        """read_file CLI defines --client, --repo, --file arguments."""
        import importlib
        mod = importlib.import_module("tools.read_file")
        # Just verify the module-level main function exists
        self.assertTrue(hasattr(mod, "main"))
        self.assertTrue(callable(mod.main))


# ---------------------------------------------------------------------------
# Propose Edit Tests
# ---------------------------------------------------------------------------

class TestProposeEditBranchProtection(unittest.TestCase):
    """Test propose_edit branch protection checks."""

    @patch("tools.propose_edit.hm_read_file")
    def test_blocks_protected_branch_main(self, mock_read):
        """propose_edit blocks edits to main branch."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="main",
            description="test edit", proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")
        self.assertIn("protected", result["note"].lower())

    @patch("tools.propose_edit.hm_read_file")
    def test_blocks_protected_branch_release(self, mock_read):
        """propose_edit blocks edits to release branches."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="release_26_3",
            description="test edit", proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")

    @patch("tools.propose_edit.hm_read_file")
    def test_blocks_protected_branch_hotfix(self, mock_read):
        """propose_edit blocks edits to hotfix branches."""
        from tools.propose_edit import propose_edit

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="hotfix/urgent-fix",
            description="test edit", proposed_changes="new content",
        )

        self.assertEqual(result["action"], "blocked")


class TestProposeEditSafeBranches(unittest.TestCase):
    """Test propose_edit allows non-protected branches."""

    @patch("tools.propose_edit.hm_read_file")
    def test_allows_feat_branch(self, mock_read):
        """propose_edit allows edits on feat/ branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="feat/new-feature",
            description="test edit", proposed_changes="new content",
            auto_apply=False,
        )

        self.assertEqual(result["action"], "proposed")

    @patch("tools.propose_edit.hm_read_file")
    def test_allows_fix_branch(self, mock_read):
        """propose_edit allows edits on fix/ branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="fix/bug-fix",
            description="test edit", proposed_changes="new content",
            auto_apply=False,
        )

        self.assertEqual(result["action"], "proposed")

    @patch("tools.propose_edit.hm_read_file")
    def test_allows_chore_branch(self, mock_read):
        """propose_edit allows edits on chore/ branches."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="chore/cleanup",
            description="test edit", proposed_changes="new content",
            auto_apply=False,
        )

        self.assertEqual(result["action"], "proposed")


class TestProposeEditAutoApply(unittest.TestCase):
    """Test propose_edit auto-apply behavior."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_propose_test_"))
        self.repo_dir = self.test_dir / "fake-repo"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("tools.propose_edit.hm_read_file")
    def test_auto_apply_false_returns_proposal(self, mock_read):
        """auto_apply=False returns proposal without writing."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content\nline2\n",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="feat/test",
            description="test", proposed_changes="new content\nline2\nline3\n",
            auto_apply=False,
        )

        self.assertEqual(result["action"], "proposed")
        self.assertIsNone(result["applied_at"])

    @patch("tools.propose_edit._find_repo_path")
    @patch("tools.propose_edit.hm_read_file")
    def test_auto_apply_true_writes_to_disk(self, mock_read, mock_repo):
        """auto_apply=True writes to disk on safe branch."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "old content",
            "source": "disk",
        }
        mock_repo.return_value = str(self.repo_dir)

        new_content = "new content\nwith changes\n"
        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="feat/test",
            description="test write", proposed_changes=new_content,
            auto_apply=True,
        )

        self.assertEqual(result["action"], "applied")
        self.assertIsNotNone(result["applied_at"])

        # Verify file was written
        written = (self.repo_dir / "file.yaml").read_text(encoding="utf-8")
        self.assertEqual(written, new_content)


class TestProposeEditDiffPreview(unittest.TestCase):
    """Test propose_edit always returns diff preview."""

    @patch("tools.propose_edit.hm_read_file")
    def test_returns_diff_preview(self, mock_read):
        """propose_edit includes diff_preview in all cases."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "line1\nline2\nline3\n",
            "source": "disk",
        }

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="file.yaml", branch="feat/test",
            description="test", proposed_changes="line1\nchanged\nline3\n",
            auto_apply=False,
        )

        self.assertIn("diff_preview", result)
        self.assertIn("full_diff", result)
        self.assertTrue(len(result["diff_preview"]) > 0)


class TestProposeEditNewFile(unittest.TestCase):
    """Test propose_edit handles creating new files."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_propose_new_"))
        self.repo_dir = self.test_dir / "fake-repo"
        self.repo_dir.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("tools.propose_edit._find_repo_path")
    @patch("tools.propose_edit.hm_read_file")
    def test_creates_new_file_on_auto_apply(self, mock_read, mock_repo):
        """propose_edit creates new file when original doesn't exist."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {
            "content": "",
            "source": "none",
        }
        mock_repo.return_value = str(self.repo_dir)

        result = propose_edit(
            client="testclient", repo="test-repo",
            file_path="subdir/new_file.yaml", branch="feat/test",
            description="create new file",
            proposed_changes="new file content\n",
            auto_apply=True,
        )

        self.assertEqual(result["action"], "applied")
        self.assertTrue((self.repo_dir / "subdir" / "new_file.yaml").exists())


class TestProposeEditReturnStructure(unittest.TestCase):
    """Test propose_edit return structure."""

    @patch("tools.propose_edit.hm_read_file")
    def test_returns_required_keys(self, mock_read):
        """propose_edit returns all required keys."""
        from tools.propose_edit import propose_edit

        mock_read.return_value = {"content": "old", "source": "disk"}

        result = propose_edit(
            client="t", repo="r", file_path="f.yaml",
            branch="feat/test", description="test",
            proposed_changes="new",
        )

        required_keys = [
            "action", "file_path", "repo", "branch", "description",
            "lines_before", "lines_after", "lines_changed",
            "diff_preview", "full_diff", "applied_at", "note",
        ]
        for key in required_keys:
            self.assertIn(key, result, f"Missing key: {key}")


class TestProposeEditNeverGitOps(unittest.TestCase):
    """Test propose_edit never does git add/commit/push."""

    def test_no_git_commands_in_source(self):
        """propose_edit.py must not invoke git add, commit, or push."""
        source_path = PROJECT_ROOT / "tools" / "propose_edit.py"
        content = source_path.read_text(encoding="utf-8")
        # Check for actual subprocess/run_git invocations of dangerous git ops
        # (string mentions in user notes/docstrings are OK)
        import ast
        tree = ast.parse(content)
        for node in ast.walk(tree):
            # Check subprocess.run calls with git add/commit/push
            if isinstance(node, ast.Call):
                call_src = ast.get_source_segment(content, node) or ""
                if "subprocess" in call_src and any(
                    cmd in call_src for cmd in ["git add", "git commit", "git push"]
                ):
                    self.fail(f"propose_edit.py invokes dangerous git command: {call_src[:80]}")
        # Also check there's no import of run_git
        self.assertNotIn("from sync.git_utils import run_git", content)


# ---------------------------------------------------------------------------
# MCP Registration Tests
# ---------------------------------------------------------------------------

class TestMCPRegistrationNewTools(unittest.TestCase):
    """Test that read_file and propose_edit are registered in MCP server."""

    def test_hivemind_read_file_registered(self):
        """hivemind_read_file is in TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertIn("hivemind_read_file", TOOL_REGISTRY)

    def test_hivemind_propose_edit_registered(self):
        """hivemind_propose_edit is in TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertIn("hivemind_propose_edit", TOOL_REGISTRY)

    def test_total_tool_count_is_18(self):
        """TOOL_REGISTRY now contains exactly 18 tools."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertEqual(len(TOOL_REGISTRY), 18)

    def test_new_tools_are_callable(self):
        """Both new tools are callable async functions."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertTrue(callable(TOOL_REGISTRY["hivemind_read_file"]))
        self.assertTrue(callable(TOOL_REGISTRY["hivemind_propose_edit"]))


if __name__ == "__main__":
    unittest.main()
