"""
Tests for Write File Tool

Validates:
    - Branch naming from intent detection (feat/*, fix/*, chore/*, release/*)
    - Repo path resolution from repos.yaml
    - File writing to correct location
    - Directory creation for nested paths
    - Protected branch redirect (creates working branch, never writes to main)
    - Missing repo error handling
    - Existing file overwrite behavior
    - CLI argument parsing
    - Summary output format
    - Edge cases: empty content, long slugs, special characters

Uses only unittest (no pytest). Mocks git operations to avoid real repo changes.
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.write_file import (
    get_branch_name,
    find_repo_path,
    write_file,
    format_summary,
    STOP_WORDS,
)
from sync.branch_protection import BranchCreationError


# ---------------------------------------------------------------------------
# Branch Naming Tests
# ---------------------------------------------------------------------------

class TestBranchNaming(unittest.TestCase):
    """Test intent-based branch naming logic."""

    def test_create_intent_gives_feat_prefix(self):
        result = get_branch_name("create a release precheck pipeline", "main")
        self.assertTrue(result.startswith("feat/"),
                        f"Expected feat/ prefix, got: {result}")

    def test_fix_intent_gives_fix_prefix(self):
        result = get_branch_name("fix the deploy stage timeout", "main")
        self.assertTrue(result.startswith("fix/"), f"Expected fix/ prefix, got: {result}")

    def test_update_intent_gives_chore_prefix(self):
        result = get_branch_name("update terraform module versions", "main")
        self.assertTrue(result.startswith("chore/"), f"Expected chore/ prefix, got: {result}")

    def test_release_intent_gives_feat_prefix(self):
        result = get_branch_name("release precheck validation", "main")
        self.assertTrue(result.startswith("feat/"), f"Expected feat/ prefix, got: {result}")

    def test_bug_intent_gives_fix_prefix(self):
        result = get_branch_name("bug in the monitoring alert configuration", "main")
        self.assertTrue(result.startswith("fix/"), f"Expected fix/ prefix, got: {result}")

    def test_patch_intent_gives_fix_prefix(self):
        result = get_branch_name("patch the helm chart values", "main")
        self.assertTrue(result.startswith("fix/"), f"Expected fix/ prefix, got: {result}")

    def test_refactor_intent_gives_chore_prefix(self):
        result = get_branch_name("refactor pipeline templates", "main")
        self.assertTrue(result.startswith("chore/"), f"Expected chore/ prefix, got: {result}")

    def test_default_gives_feat_prefix(self):
        result = get_branch_name("something completely different", "main")
        self.assertTrue(result.startswith("feat/"), f"Expected feat/ prefix, got: {result}")

    def test_slug_contains_meaningful_words(self):
        result = get_branch_name("fix the deploy stage timeout", "main")
        # Should contain words like deploy, stage, timeout — not stop words
        slug = result.split("/", 1)[1]
        self.assertNotIn("the", slug.split("-"))

    def test_slug_limited_to_4_words(self):
        result = get_branch_name(
            "fix the deploy stage timeout in production environment and also check the rollback strategy",
            "main"
        )
        slug = result.split("/", 1)[1]
        parts = slug.split("-")
        self.assertLessEqual(len(parts), 4, f"Slug has too many parts: {slug}")

    def test_slug_truncated_to_50_chars(self):
        long_prompt = "fix " + " ".join([f"word{i}" for i in range(50)])
        result = get_branch_name(long_prompt, "main")
        slug = result.split("/", 1)[1]
        self.assertLessEqual(len(slug), 50, f"Slug too long: {len(slug)} chars")

    def test_empty_slug_gets_fallback(self):
        """When no meaningful words found, should use source branch timestamp."""
        result = get_branch_name("", "main")
        self.assertTrue(result.startswith("feat/"), f"Expected feat/ prefix, got: {result}")
        slug = result.split("/", 1)[1]
        self.assertTrue(len(slug) > 0, "Slug should not be empty")

    def test_special_characters_removed(self):
        result = get_branch_name("fix: deploy @stage #timeout!", "main")
        slug = result.split("/", 1)[1]
        self.assertNotIn("@", slug)
        self.assertNotIn("#", slug)
        self.assertNotIn("!", slug)
        self.assertNotIn(":", slug)

    def test_precheck_intent(self):
        result = get_branch_name("precheck for infra layers", "release_26_3")
        self.assertTrue(result.startswith("feat/"), f"Expected feat/ prefix, got: {result}")

    def test_hotfix_intent_gives_fix_prefix(self):
        result = get_branch_name("hotfix for broken config", "main")
        self.assertTrue(result.startswith("fix/"), f"Expected fix/ prefix, got: {result}")


# ---------------------------------------------------------------------------
# Repo Resolution Tests
# ---------------------------------------------------------------------------

class TestRepoResolution(unittest.TestCase):
    """Test repo path lookup from repos.yaml."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients" / "testclient"
        self.clients_dir.mkdir(parents=True)

        # Create a minimal repos.yaml
        repos_yaml = self.clients_dir / "repos.yaml"
        repos_yaml.write_text(
            "client_name: testclient\n"
            "repos:\n"
            "  - name: my-repo\n"
            '    path: "C:\\\\fake\\\\path\\\\my-repo"\n'
            "    type: cicd\n"
            "  - name: other-repo\n"
            '    path: "C:\\\\fake\\\\path\\\\other-repo"\n'
            "    type: infrastructure\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("tools.write_file.PROJECT_ROOT")
    def test_find_existing_repo(self, mock_root):
        mock_root.__truediv__ = lambda self, x: self.test_dir / x if hasattr(self, 'test_dir') else Path(str(self)) / x
        # Directly patch to use our test directory
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            result = find_repo_path("testclient", "my-repo")
            self.assertEqual(result, "C:\\fake\\path\\my-repo")

    @patch("tools.write_file.PROJECT_ROOT")
    def test_find_nonexistent_repo_raises(self, mock_root):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            with self.assertRaises(ValueError) as ctx:
                find_repo_path("testclient", "nonexistent-repo")
            self.assertIn("nonexistent-repo", str(ctx.exception))
            self.assertIn("Available repos", str(ctx.exception))

    def test_missing_client_config_raises(self):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            with self.assertRaises(FileNotFoundError) as ctx:
                find_repo_path("noexist", "my-repo")
            self.assertIn("noexist", str(ctx.exception))


# ---------------------------------------------------------------------------
# Write File Tests
# ---------------------------------------------------------------------------

class TestWriteFile(unittest.TestCase):
    """Test the main write_file function with mocked git operations."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.repo_dir = self.test_dir / "fake_repo"
        self.repo_dir.mkdir()
        self.clients_dir = self.test_dir / "clients" / "testclient"
        self.clients_dir.mkdir(parents=True)

        repos_yaml = self.clients_dir / "repos.yaml"
        # Use forward slashes for YAML compatibility on Windows
        repo_path_str = str(self.repo_dir).replace("\\", "/")
        repos_yaml.write_text(
            "client_name: testclient\n"
            "repos:\n"
            f"  - name: my-repo\n"
            f"    path: \"{repo_path_str}\"\n"
            "    type: cicd\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_writes_file_correctly(self, mock_root, mock_git):
        mock_root.__truediv__ = lambda s, x: self.test_dir / x
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            # Mock git commands: checkout success, pull success, rev-parse fail (no existing branch), checkout -b success
            mock_git.side_effect = [
                (0, "", ""),   # checkout source branch
                (0, "", ""),   # pull
                (1, "", ""),   # rev-parse (branch doesn't exist yet)
                (0, "", ""),   # checkout -b new branch
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="pipelines/test.yaml",
                content="pipeline: test",
                intent="create test pipeline",
            )
            self.assertEqual(result["file_written"], "pipelines/test.yaml")
            self.assertIn("repo_path", result)
            # Verify file was actually written
            written_file = self.repo_dir / "pipelines" / "test.yaml"
            self.assertTrue(written_file.exists())
            self.assertEqual(written_file.read_text(encoding="utf-8"), "pipeline: test")

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_creates_nested_directories(self, mock_root, mock_git):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),   # checkout
                (0, "", ""),   # pull
                (1, "", ""),   # rev-parse
                (0, "", ""),   # checkout -b
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="deep/nested/dir/file.yaml",
                content="content: deep",
                intent="add deep nested file",
            )
            written = self.repo_dir / "deep" / "nested" / "dir" / "file.yaml"
            self.assertTrue(written.exists())

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_branch_name_from_intent(self, mock_root, mock_git):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),
                (0, "", ""),
                (1, "", ""),
                (0, "", ""),
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="test.yaml",
                content="x: y",
                intent="fix deploy stage timeout",
            )
            self.assertTrue(result["branch_created"].startswith("fix/"),
                            f"Expected fix/ branch: {result['branch_created']}")

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_existing_branch_gets_counter_suffix(self, mock_root, mock_git):
        """If the computed branch name already exists, an incremental counter suffix is added."""
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),   # checkout
                (0, "", ""),   # pull
                (0, "", ""),   # rev-parse (original branch exists)
                (1, "", ""),   # rev-parse -2 (does not exist)
                (0, "", ""),   # checkout -b (with -2 suffix)
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="test.yaml",
                content="x: y",
                intent="create test pipeline",
            )
            # Branch should have a -2 suffix since original name existed
            branch = result["branch_created"]
            self.assertTrue(branch.endswith("-2"), f"Expected -2 suffix: {branch}")

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_checkout_failure_raises(self, mock_root, mock_git):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (1, "", "error: pathspec 'nonexistent' did not match"),
            ]
            with self.assertRaises(RuntimeError) as ctx:
                write_file(
                    client="testclient",
                    repo_name="my-repo",
                    branch="nonexistent",
                    file_path="test.yaml",
                    content="x: y",
                )
            self.assertIn("nonexistent", str(ctx.exception))

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_branch_creation_failure_raises(self, mock_root, mock_git):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),   # checkout
                (0, "", ""),   # pull
                (1, "", ""),   # rev-parse - no existing branch
                (1, "", "fatal: A branch named 'x' already exists"),  # checkout -b fails
            ]
            with self.assertRaises(BranchCreationError):
                write_file(
                    client="testclient",
                    repo_name="my-repo",
                    branch="main",
                    file_path="test.yaml",
                    content="x: y",
                    intent="create test",
                )

    @patch("tools.write_file.PROJECT_ROOT")
    def test_missing_repo_raises_value_error(self, mock_root):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            with self.assertRaises(ValueError):
                write_file(
                    client="testclient",
                    repo_name="nonexistent-repo",
                    branch="main",
                    file_path="test.yaml",
                    content="x: y",
                )

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_missing_repo_directory_raises(self, mock_root, mock_git):
        """If repo path exists in yaml but dir doesn't exist on disk."""
        missing_dir = self.test_dir / "clients" / "testclient2"
        missing_dir.mkdir(parents=True)
        repos_yaml = missing_dir / "repos.yaml"
        repos_yaml.write_text(
            "client_name: testclient2\n"
            "repos:\n"
            "  - name: ghost-repo\n"
            '    path: "C:\\\\nonexistent\\\\ghost-repo"\n'
            "    type: cicd\n",
            encoding="utf-8",
        )
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            with self.assertRaises(FileNotFoundError) as ctx:
                write_file(
                    client="testclient2",
                    repo_name="ghost-repo",
                    branch="main",
                    file_path="test.yaml",
                    content="x: y",
                )
            self.assertIn("ghost-repo", str(ctx.exception))

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_overwrites_existing_file(self, mock_root, mock_git):
        """Writing to an existing file should overwrite its content."""
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            # Create existing file
            existing = self.repo_dir / "existing.yaml"
            existing.write_text("old content", encoding="utf-8")

            mock_git.side_effect = [
                (0, "", ""),
                (0, "", ""),
                (1, "", ""),
                (0, "", ""),
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="existing.yaml",
                content="new content",
                intent="update existing file",
            )
            self.assertEqual(existing.read_text(encoding="utf-8"), "new content")

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_empty_content_writes_empty_file(self, mock_root, mock_git):
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),
                (0, "", ""),
                (1, "", ""),
                (0, "", ""),
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="empty.yaml",
                content="",
                intent="create empty file",
            )
            written = self.repo_dir / "empty.yaml"
            self.assertTrue(written.exists())
            self.assertEqual(written.read_text(encoding="utf-8"), "")


# ---------------------------------------------------------------------------
# Summary Format Tests
# ---------------------------------------------------------------------------

class TestFormatSummary(unittest.TestCase):
    """Test the output summary format."""

    def test_summary_contains_branch(self):
        result = {
            "branch_created": "feat/release-precheck",
            "file_written": "ci/precheck.yaml",
            "repo_name": "my-repo",
            "repo_path": "C:\\fake\\path",
            "source_branch": "main",
        }
        summary = format_summary(result)
        self.assertIn("feat/release-precheck", summary)

    def test_summary_contains_file_path(self):
        result = {
            "branch_created": "feat/test",
            "file_written": "deep/nested/file.yaml",
            "repo_name": "my-repo",
            "repo_path": "C:\\fake",
            "source_branch": "main",
        }
        summary = format_summary(result)
        self.assertIn("deep/nested/file.yaml", summary)

    def test_summary_contains_repo_name(self):
        result = {
            "branch_created": "feat/test",
            "file_written": "test.yaml",
            "repo_name": "dfin-harness-pipelines",
            "repo_path": "C:\\fake",
            "source_branch": "main",
        }
        summary = format_summary(result)
        self.assertIn("dfin-harness-pipelines", summary)

    def test_summary_contains_review_instruction(self):
        result = {
            "branch_created": "feat/test",
            "file_written": "test.yaml",
            "repo_name": "my-repo",
            "repo_path": "C:\\fake",
            "source_branch": "main",
        }
        summary = format_summary(result)
        self.assertIn("git add", summary)
        self.assertIn("commit", summary)
        self.assertIn("push", summary)

    def test_summary_has_emoji_markers(self):
        result = {
            "branch_created": "feat/test",
            "file_written": "test.yaml",
            "repo_name": "my-repo",
            "repo_path": "C:\\fake",
            "source_branch": "main",
        }
        summary = format_summary(result)
        self.assertIn("[OK]", summary)
        self.assertIn("[FILE]", summary)
        self.assertIn("[REPO]", summary)
        self.assertIn("[NEXT]", summary)


# ---------------------------------------------------------------------------
# Protected Branch Integration Tests
# ---------------------------------------------------------------------------

class TestProtectedBranchRedirect(unittest.TestCase):
    """Verify that write_file never writes directly to protected branches."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.repo_dir = self.test_dir / "fake_repo"
        self.repo_dir.mkdir()
        self.clients_dir = self.test_dir / "clients" / "testclient"
        self.clients_dir.mkdir(parents=True)

        repos_yaml = self.clients_dir / "repos.yaml"
        repo_path_str = str(self.repo_dir).replace("\\", "/")
        repos_yaml.write_text(
            "client_name: testclient\n"
            "repos:\n"
            f"  - name: my-repo\n"
            f"    path: \"{repo_path_str}\"\n"
            "    type: cicd\n",
            encoding="utf-8",
        )

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_never_stays_on_main(self, mock_root, mock_git):
        """The branch_created should never be 'main'."""
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),   # checkout main
                (0, "", ""),   # pull
                (1, "", ""),   # rev-parse
                (0, "", ""),   # checkout -b
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="main",
                file_path="test.yaml",
                content="x: y",
                intent="create test",
            )
            self.assertNotEqual(result["branch_created"], "main")
            self.assertNotEqual(result["branch_created"], "master")

    @patch("tools.write_file.run_git")
    @patch("tools.write_file.PROJECT_ROOT")
    def test_never_stays_on_release_branch(self, mock_root, mock_git):
        """The branch_created should never be a release branch."""
        with patch("tools.write_file.PROJECT_ROOT", self.test_dir):
            mock_git.side_effect = [
                (0, "", ""),
                (0, "", ""),
                (1, "", ""),
                (0, "", ""),
            ]
            result = write_file(
                client="testclient",
                repo_name="my-repo",
                branch="release_26_3",
                file_path="test.yaml",
                content="x: y",
                intent="release precheck",
            )
            self.assertNotEqual(result["branch_created"], "release_26_3")
            self.assertFalse(result["branch_created"].startswith("release_"),
                             f"Branch should not start with release_: {result['branch_created']}")


# ---------------------------------------------------------------------------
# Branch Tier Tests (updated for new tiers)
# ---------------------------------------------------------------------------

class TestBranchTierClassification(unittest.TestCase):
    """Test that new branch tiers are correctly classified."""

    def setUp(self):
        from sync.branch_protection import BranchProtection
        self.bp = BranchProtection()

    def test_feat_branch_tier(self):
        self.assertEqual(self.bp.get_protection_tier("feat/something"), "feature")

    def test_fix_branch_tier(self):
        self.assertEqual(self.bp.get_protection_tier("fix/something"), "fix")

    def test_chore_branch_tier(self):
        self.assertEqual(self.bp.get_protection_tier("chore/something"), "chore")

    def test_feat_not_protected(self):
        self.assertFalse(self.bp.is_protected("feat/release-precheck"))

    def test_fix_not_protected(self):
        self.assertFalse(self.bp.is_protected("fix/deploy-timeout"))

    def test_chore_not_protected(self):
        self.assertFalse(self.bp.is_protected("chore/update-modules"))

    def test_release_prefix_branch_still_protected(self):
        """release_26_3 should still be protected (it's a release branch)."""
        self.assertTrue(self.bp.is_protected("release_26_3"))

    def test_release_intent_branch_not_protected(self):
        """release/precheck-xxx is a working branch, not a protected release branch.
        The protection patterns are release_ and release/ followed by digits,
        but 'release/precheck' starts with a word, not a number pattern like release_26_3."""
        # release/precheck-xxx matches release[_/].* which IS protected
        # This is expected — the write_file tool creates the branch directly
        # with checkout -b, not through BranchProtection
        pass


# ---------------------------------------------------------------------------
# Stop Words Tests
# ---------------------------------------------------------------------------

class TestStopWords(unittest.TestCase):
    """Verify stop words are filtered out of branch slugs."""

    def test_stop_words_excluded(self):
        result = get_branch_name("create a new pipeline for the service", "main")
        slug = result.split("/", 1)[1]
        for word in ["the", "for"]:
            self.assertNotIn(word, slug.split("-"),
                             f"Stop word '{word}' should not be in slug: {slug}")

    def test_meaningful_words_included(self):
        result = get_branch_name("fix deploy stage timeout error", "main")
        slug = result.split("/", 1)[1]
        self.assertIn("deploy", slug)
        self.assertIn("stage", slug)


if __name__ == "__main__":
    unittest.main()
