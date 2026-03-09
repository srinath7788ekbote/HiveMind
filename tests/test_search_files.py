"""
Unit Tests — Search Files

Tests tools/search_files.py

Covers:
    - search_files() with list-format entities.json (real format)
    - search_files() with dict-format entities.json (legacy format)
    - Filtering by query, type, repo, branch
    - Limit enforcement
    - Missing entities.json graceful fallback
    - _load_config() YAML parsing
    - search_files_in_repos() with real fixture dirs
"""

import json
import os
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO


class TestSearchFilesListFormat(HiveMindTestCase):
    """Tests for search_files() when entities.json is a flat list (production format)."""

    def setUp(self):
        super().setUp()
        # Real-world format: entities.json is a flat JSON array
        self.entities = [
            {"name": "pipeline", "type": "pipeline", "file": "pipelines/deploy_audit.yaml", "repo": "dfin-harness-pipelines", "branch": "main"},
            {"name": "pipeline", "type": "pipeline", "file": "pipelines/deploy_payment.yaml", "repo": "dfin-harness-pipelines", "branch": "main"},
            {"name": "terraform", "type": "terraform", "file": "layer_01_keyvaults/main.tf", "repo": "Eastwood-terraform", "branch": "main"},
            {"name": "terraform", "type": "terraform", "file": "layer_02_aks/main.tf", "repo": "Eastwood-terraform", "branch": "develop"},
            {"name": "helm_values", "type": "helm_values", "file": "charts/audit-service/values.yaml", "repo": "Eastwood-helm", "branch": "main"},
            {"name": "template", "type": "template", "file": "templates/rollout_k8s.yaml", "repo": "dfin-harness-pipelines", "branch": "main"},
            {"name": "harness_svc", "type": "harness_svc", "file": ".harness/services/audit_service.yaml", "repo": "dfin-harness-pipelines", "branch": "main"},
            {"name": "readme", "type": "readme", "file": "README.md", "repo": "dfin-harness-pipelines", "branch": "main"},
        ]
        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(self.entities, f, indent=2)

    def _search(self, **kwargs):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.search_files(client="testclient", **kwargs)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_no_filters_returns_all(self):
        results = self._search()
        self.assertEqual(len(results), len(self.entities))

    def test_filter_by_type_pipeline(self):
        results = self._search(file_type="pipeline")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["type"], "pipeline")

    def test_filter_by_type_terraform(self):
        results = self._search(file_type="terraform")
        self.assertEqual(len(results), 2)

    def test_filter_by_repo(self):
        results = self._search(repo="Eastwood-terraform")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["repo"], "Eastwood-terraform")

    def test_filter_by_branch(self):
        results = self._search(branch="develop")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["branch"], "develop")

    def test_query_matches_file_path(self):
        results = self._search(query="audit")
        files = [r.get("file", r.get("path", "")) for r in results]
        for f in files:
            self.assertIn("audit", f.lower())

    def test_query_case_insensitive(self):
        results_lower = self._search(query="readme")
        results_upper = self._search(query="README")
        self.assertEqual(len(results_lower), len(results_upper))

    def test_combined_filters(self):
        results = self._search(file_type="pipeline", repo="dfin-harness-pipelines", branch="main")
        self.assertEqual(len(results), 2)

    def test_combined_filters_no_match(self):
        results = self._search(file_type="pipeline", branch="develop")
        self.assertEqual(len(results), 0)

    def test_limit_enforced(self):
        results = self._search(limit=3)
        self.assertLessEqual(len(results), 3)

    def test_limit_one(self):
        results = self._search(limit=1)
        self.assertEqual(len(results), 1)

    def test_query_no_match(self):
        results = self._search(query="nonexistent_xyz_123")
        self.assertEqual(len(results), 0)

    def test_type_no_match(self):
        results = self._search(file_type="dockerfile")
        self.assertEqual(len(results), 0)


class TestSearchFilesDictFormat(HiveMindTestCase):
    """Tests for search_files() when entities.json is a dict with 'files' key (legacy)."""

    def setUp(self):
        super().setUp()
        entities_dict = {
            "files": [
                {"path": "pipelines/deploy_audit.yaml", "type": "pipeline", "repo": "dfin-harness-pipelines", "branch": "main"},
                {"path": "layer_01_keyvaults/main.tf", "type": "terraform", "repo": "Eastwood-terraform", "branch": "main"},
            ],
            "secrets": [],
        }
        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(entities_dict, f, indent=2)

    def _search(self, **kwargs):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.search_files(client="testclient", **kwargs)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_dict_format_returns_files(self):
        results = self._search()
        self.assertEqual(len(results), 2)

    def test_dict_format_query_works(self):
        results = self._search(query="pipeline")
        self.assertEqual(len(results), 1)

    def test_dict_format_type_filter(self):
        results = self._search(file_type="terraform")
        self.assertEqual(len(results), 1)


class TestSearchFilesMissing(HiveMindTestCase):
    """Tests for search_files() when entities.json is missing."""

    def _search(self, **kwargs):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.search_files(client="testclient", **kwargs)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_missing_entities_returns_empty(self):
        results = self._search()
        self.assertEqual(results, [])

    def test_missing_client_returns_empty(self):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            results = mod.search_files(client="nonexistent_client")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(results, [])


class TestLoadConfig(HiveMindTestCase):
    """Tests for _load_config() YAML parsing."""

    def _load(self, client):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod._load_config(client)
        finally:
            mod.PROJECT_ROOT = original_root

    def setUp(self):
        super().setUp()
        # Create a fake client config
        client_dir = self.test_dir / "clients" / "testclient"
        client_dir.mkdir(parents=True, exist_ok=True)
        repos_yaml = client_dir / "repos.yaml"
        repos_yaml.write_text(
            "repos:\n"
            "  - name: my-repo\n"
            "    path: /tmp/my-repo\n"
            "    type: cicd/harness\n"
            "  - name: infra-repo\n"
            "    path: /tmp/infra-repo\n"
            "    type: infrastructure/terraform\n",
            encoding="utf-8",
        )

    def test_loads_repos(self):
        config = self._load("testclient")
        repos = config.get("repos", [])
        self.assertEqual(len(repos), 2)

    def test_repo_names(self):
        config = self._load("testclient")
        names = [r["name"] for r in config["repos"]]
        self.assertIn("my-repo", names)
        self.assertIn("infra-repo", names)

    def test_missing_config_returns_empty(self):
        config = self._load("nonexistent_client")
        self.assertEqual(config, {})


class TestSearchFilesInRepos(HiveMindTestCase):
    """Tests for search_files_in_repos() using real fixture directories."""

    def setUp(self):
        super().setUp()
        # Create a fake client config pointing to our test fixtures
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

    def _search_repos(self, **kwargs):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.search_files_in_repos(client="testclient", **kwargs)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_finds_files_in_fixture(self):
        results = self._search_repos()
        self.assertGreater(len(results), 0)

    def test_results_have_required_keys(self):
        results = self._search_repos()
        for r in results:
            self.assertIn("path", r)
            self.assertIn("repo", r)

    def test_query_filter(self):
        results = self._search_repos(query="deploy_audit")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("deploy_audit", r["path"].lower())

    def test_repo_filter(self):
        results = self._search_repos(repo="fake-harness")
        self.assertGreater(len(results), 0)

    def test_repo_filter_no_match(self):
        results = self._search_repos(repo="nonexistent-repo")
        self.assertEqual(len(results), 0)

    def test_limit_enforced(self):
        results = self._search_repos(limit=2)
        self.assertLessEqual(len(results), 2)

    def test_no_config_returns_empty(self):
        import tools.search_files as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            results = mod.search_files_in_repos(client="nonexistent")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
