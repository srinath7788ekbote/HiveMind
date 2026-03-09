"""
Unit Tests — Set Client

Tests tools/set_client.py

Covers:
    - get_active_client() with and without marker file
    - set_active_client() success and error paths
    - list_clients() with multiple clients
    - Memory directory creation
    - Client validation (missing dir, missing repos.yaml)
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestGetActiveClient(HiveMindTestCase):
    """Tests for get_active_client()."""

    def _get(self):
        import tools.set_client as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.get_active_client()
        finally:
            mod.PROJECT_ROOT = original_root

    def test_no_marker_returns_empty(self):
        result = self._get()
        self.assertEqual(result, "")

    def test_reads_marker(self):
        marker = self.test_dir / "memory" / "active_client.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("testclient", encoding="utf-8")
        result = self._get()
        self.assertEqual(result, "testclient")

    def test_strips_whitespace(self):
        marker = self.test_dir / "memory" / "active_client.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("  testclient  \n", encoding="utf-8")
        result = self._get()
        self.assertEqual(result, "testclient")


class TestSetActiveClient(HiveMindTestCase):
    """Tests for set_active_client()."""

    def setUp(self):
        super().setUp()
        # Create a valid client directory with repos.yaml
        self.client_dir = self.test_dir / "clients" / "testclient"
        self.client_dir.mkdir(parents=True, exist_ok=True)
        (self.client_dir / "repos.yaml").write_text(
            "repos:\n  - name: my-repo\n    path: /tmp/repo\n    type: cicd/harness\n",
            encoding="utf-8",
        )

    def _set(self, client):
        import tools.set_client as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.set_active_client(client)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_set_valid_client(self):
        result = self._set("testclient")
        self.assertNotIn("error", result)
        self.assertEqual(result["client"], "testclient")
        self.assertEqual(result["status"], "active")

    def test_set_creates_marker(self):
        self._set("testclient")
        marker = self.test_dir / "memory" / "active_client.txt"
        self.assertTrue(marker.exists())
        self.assertEqual(marker.read_text(encoding="utf-8"), "testclient")

    def test_set_creates_memory_dir(self):
        self._set("testclient")
        client_memory = self.test_dir / "memory" / "testclient"
        self.assertTrue(client_memory.exists())

    def test_set_returns_repo_count(self):
        result = self._set("testclient")
        self.assertEqual(result["repos"], 1)

    def test_set_returns_config_path(self):
        result = self._set("testclient")
        self.assertIn("repos.yaml", result["config"])

    def test_set_nonexistent_client(self):
        result = self._set("nonexistent_client_xyz")
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_set_client_no_repos_yaml(self):
        """Client dir exists but repos.yaml is missing."""
        bad_client = self.test_dir / "clients" / "badclient"
        bad_client.mkdir(parents=True, exist_ok=True)
        result = self._set("badclient")
        self.assertIn("error", result)
        self.assertIn("repos.yaml", result["error"])

    def test_set_overwrites_previous(self):
        # Create a second client
        client2 = self.test_dir / "clients" / "client2"
        client2.mkdir(parents=True, exist_ok=True)
        (client2 / "repos.yaml").write_text("repos:\n", encoding="utf-8")

        self._set("testclient")
        self._set("client2")

        marker = self.test_dir / "memory" / "active_client.txt"
        self.assertEqual(marker.read_text(encoding="utf-8"), "client2")

    def test_multiple_repos_counted(self):
        """Client with multiple repos."""
        multi_client = self.test_dir / "clients" / "multi"
        multi_client.mkdir(parents=True, exist_ok=True)
        (multi_client / "repos.yaml").write_text(
            "repos:\n"
            "  - name: repo1\n    path: /tmp/r1\n"
            "  - name: repo2\n    path: /tmp/r2\n"
            "  - name: repo3\n    path: /tmp/r3\n",
            encoding="utf-8",
        )
        result = self._set("multi")
        self.assertEqual(result["repos"], 3)


class TestListClients(HiveMindTestCase):
    """Tests for list_clients()."""

    def setUp(self):
        super().setUp()
        # Create multiple client directories
        for name in ["alpha", "beta", "gamma"]:
            d = self.test_dir / "clients" / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "repos.yaml").write_text(f"repos:\n  - name: {name}-repo\n", encoding="utf-8")

        # Create a dir WITHOUT repos.yaml (should not appear)
        invalid = self.test_dir / "clients" / "invalid"
        invalid.mkdir(parents=True, exist_ok=True)

    def _list(self):
        import tools.set_client as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return mod.list_clients()
        finally:
            mod.PROJECT_ROOT = original_root

    def test_lists_valid_clients(self):
        clients = self._list()
        names = [c["name"] for c in clients]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)
        self.assertIn("gamma", names)

    def test_excludes_invalid_clients(self):
        clients = self._list()
        names = [c["name"] for c in clients]
        self.assertNotIn("invalid", names)

    def test_client_has_required_keys(self):
        clients = self._list()
        for c in clients:
            self.assertIn("name", c)
            self.assertIn("active", c)
            self.assertIn("config", c)

    def test_no_active_client(self):
        clients = self._list()
        active_flags = [c["active"] for c in clients]
        self.assertTrue(all(not a for a in active_flags))

    def test_active_client_flagged(self):
        # Set alpha as active
        marker = self.test_dir / "memory" / "active_client.txt"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("alpha", encoding="utf-8")

        clients = self._list()
        alpha = [c for c in clients if c["name"] == "alpha"][0]
        beta = [c for c in clients if c["name"] == "beta"][0]
        self.assertTrue(alpha["active"])
        self.assertFalse(beta["active"])

    def test_sorted_alphabetically(self):
        clients = self._list()
        names = [c["name"] for c in clients]
        self.assertEqual(names, sorted(names))

    def test_no_clients_dir(self):
        import tools.set_client as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir / "nonexistent"
        try:
            clients = mod.list_clients()
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertEqual(clients, [])


if __name__ == "__main__":
    unittest.main()
