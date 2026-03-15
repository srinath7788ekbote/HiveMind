"""
Tests for multi-client scripts: sync_kb, populate_chromadb, crawl_all,
populate_all_chromadb, add_client.

Covers:
- Client discovery (discover_clients function)
- Multi-client sync output
- crawl_all.py client discovery
- add_client.py path validation
- populate_chromadb.py multi-client discovery
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


class TestClientDiscovery(unittest.TestCase):
    """Test discover_clients across all scripts that use it."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients"
        self.clients_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def _create_client(self, name: str):
        """Create a valid client dir with repos.yaml."""
        d = self.clients_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "repos.yaml").write_text(
            f"client_name: {name}\nrepos: []\n", encoding="utf-8"
        )

    def test_discover_no_clients_dir(self):
        """discover_clients returns [] when clients/ doesn't exist."""
        from scripts.sync_kb import discover_clients
        empty = Path(tempfile.mkdtemp(prefix="hivemind_empty_"))
        try:
            result = discover_clients(empty)
            self.assertEqual(result, [])
        finally:
            shutil.rmtree(str(empty), ignore_errors=True)

    def test_discover_empty_clients_dir(self):
        """discover_clients returns [] when clients/ has no valid clients."""
        from scripts.sync_kb import discover_clients
        result = discover_clients(self.test_dir)
        self.assertEqual(result, [])

    def test_discover_single_client(self):
        """discover_clients finds a single valid client."""
        from scripts.sync_kb import discover_clients
        self._create_client("acme")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["acme"])

    def test_discover_multiple_clients_sorted(self):
        """discover_clients returns clients sorted alphabetically."""
        from scripts.sync_kb import discover_clients
        self._create_client("zebra")
        self._create_client("alpha")
        self._create_client("mid")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["alpha", "mid", "zebra"])

    def test_discover_skips_underscore_dirs(self):
        """discover_clients skips directories starting with underscore."""
        from scripts.sync_kb import discover_clients
        self._create_client("_example")
        self._create_client("real")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["real"])

    def test_discover_skips_dirs_without_repos_yaml(self):
        """discover_clients skips directories without repos.yaml."""
        from scripts.sync_kb import discover_clients
        # Dir exists but no repos.yaml
        (self.clients_dir / "incomplete").mkdir()
        self._create_client("valid")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["valid"])


class TestPopulateChromaDBDiscovery(unittest.TestCase):
    """Test populate_chromadb.py's discover_clients independently."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients"
        self.clients_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def _create_client(self, name: str):
        d = self.clients_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "repos.yaml").write_text(
            f"client_name: {name}\nrepos: []\n", encoding="utf-8"
        )

    def test_populate_discover_clients(self):
        """populate_chromadb.discover_clients finds valid clients."""
        from scripts.populate_chromadb import discover_clients
        self._create_client("client1")
        self._create_client("client2")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["client1", "client2"])

    def test_populate_discover_empty(self):
        """populate_chromadb.discover_clients returns [] when empty."""
        from scripts.populate_chromadb import discover_clients
        result = discover_clients(self.test_dir)
        self.assertEqual(result, [])

    def test_populate_discover_skips_underscored(self):
        """populate_chromadb.discover_clients skips _prefixed dirs."""
        from scripts.populate_chromadb import discover_clients
        self._create_client("_template")
        self._create_client("real")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["real"])


class TestCrawlAllDiscovery(unittest.TestCase):
    """Test crawl_all.py's discover_clients."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients"
        self.clients_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def _create_client(self, name: str):
        d = self.clients_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "repos.yaml").write_text(
            f"client_name: {name}\nrepos: []\n", encoding="utf-8"
        )

    def test_crawl_all_discover(self):
        """crawl_all.discover_clients finds valid clients."""
        from scripts.crawl_all import discover_clients
        self._create_client("c1")
        self._create_client("c2")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["c1", "c2"])

    def test_crawl_all_discover_empty(self):
        """crawl_all.discover_clients returns [] when no clients."""
        from scripts.crawl_all import discover_clients
        result = discover_clients(self.test_dir)
        self.assertEqual(result, [])


class TestPopulateAllChromaDBDiscovery(unittest.TestCase):
    """Test populate_all_chromadb.py's discover_clients."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients"
        self.clients_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def _create_client(self, name: str):
        d = self.clients_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "repos.yaml").write_text(
            f"client_name: {name}\nrepos: []\n", encoding="utf-8"
        )

    def test_populate_all_discover(self):
        """populate_all_chromadb.discover_clients finds valid clients."""
        from scripts.populate_all_chromadb import discover_clients
        self._create_client("x")
        self._create_client("y")
        result = discover_clients(self.test_dir)
        self.assertEqual(result, ["x", "y"])


class TestSyncKBState(unittest.TestCase):
    """Test sync_kb.py state management."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_load_state_missing_file(self):
        """_load_state returns {} when state file doesn't exist."""
        from scripts.sync_kb import _load_state
        result = _load_state("testclient", self.test_dir)
        self.assertEqual(result, {})

    def test_save_and_load_state(self):
        """_save_state writes, _load_state reads back correctly."""
        from scripts.sync_kb import _save_state, _load_state
        state = {"repo/main": {"commit": "abc123", "synced_at": "2024-01-01"}}
        _save_state("testclient", state, self.test_dir)
        loaded = _load_state("testclient", self.test_dir)
        self.assertEqual(loaded, state)

    def test_save_state_creates_dir(self):
        """_save_state creates memory/<client>/ dir if missing."""
        from scripts.sync_kb import _save_state
        _save_state("newclient", {"a": 1}, self.test_dir)
        f = self.test_dir / "memory" / "newclient" / "sync_state.json"
        self.assertTrue(f.exists())

    def test_load_state_corrupt_json(self):
        """_load_state returns {} on corrupt JSON."""
        from scripts.sync_kb import _load_state
        f = self.test_dir / "memory" / "testclient" / "sync_state.json"
        f.write_text("not json!", encoding="utf-8")
        result = _load_state("testclient", self.test_dir)
        self.assertEqual(result, {})


class TestSyncKBConfig(unittest.TestCase):
    """Test sync_kb.py config loading."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_load_config_missing_file(self):
        """_load_config returns {} for missing file."""
        from scripts.sync_kb import _load_config
        result = _load_config(self.test_dir / "nope.yaml")
        self.assertEqual(result, {})

    def test_load_config_yaml(self):
        """_load_config parses basic YAML."""
        from scripts.sync_kb import _load_config
        cfg = self.test_dir / "repos.yaml"
        cfg.write_text(
            "client_name: test\nrepos:\n  - name: repo1\n    path: /tmp/repo1\n    type: cicd\n    branches:\n      - main\n",
            encoding="utf-8",
        )
        result = _load_config(cfg)
        self.assertEqual(result["client_name"], "test")
        self.assertTrue(len(result["repos"]) >= 1)


class TestSyncKBMultiClientOutput(unittest.TestCase):
    """Test multi-client sync output format."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.clients_dir = self.test_dir / "clients"
        self.clients_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def _create_client(self, name: str):
        d = self.clients_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "repos.yaml").write_text(
            f"client_name: {name}\nrepos: []\n", encoding="utf-8"
        )

    def test_show_status_no_repos(self):
        """show_status handles clients with no repos gracefully."""
        from scripts.sync_kb import show_status
        self._create_client("empty")
        # Should not raise
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            show_status(["empty"], self.test_dir)
        output = buf.getvalue()
        self.assertIn("empty", output)
        self.assertIn("no repos configured", output)

    def test_sync_all_no_repos(self):
        """sync_all handles clients with no repos gracefully."""
        from scripts.sync_kb import sync_all
        self._create_client("nope")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            sync_all(["nope"], project_root=self.test_dir, auto_yes=True)
        output = buf.getvalue()
        self.assertIn("nope", output)

    def test_multi_client_header(self):
        """sync_all with multiple clients shows 'ALL CLIENTS' header."""
        from scripts.sync_kb import sync_all
        self._create_client("a")
        self._create_client("b")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            sync_all(["a", "b"], project_root=self.test_dir, auto_yes=True)
        output = buf.getvalue()
        self.assertIn("ALL CLIENTS", output)
        self.assertIn("Discovered clients: a, b", output)


class TestAddClientPathValidation(unittest.TestCase):
    """Test add_client.py path validation and type detection."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_detect_terraform(self):
        """_detect_type_platform finds Terraform repos."""
        from scripts.add_client import _detect_type_platform
        repo = self.test_dir / "tf_repo"
        repo.mkdir()
        (repo / "main.tf").write_text("resource {}", encoding="utf-8")
        rtype, platform = _detect_type_platform(repo)
        self.assertEqual(rtype, "infrastructure")
        self.assertEqual(platform, "terraform")

    def test_detect_helm(self):
        """_detect_type_platform finds Helm repos."""
        from scripts.add_client import _detect_type_platform
        repo = self.test_dir / "helm_repo"
        repo.mkdir()
        (repo / "Chart.yaml").write_text("name: test", encoding="utf-8")
        rtype, platform = _detect_type_platform(repo)
        self.assertEqual(rtype, "mixed")
        self.assertEqual(platform, "helm")

    def test_detect_unknown(self):
        """_detect_type_platform returns mixed/unknown for empty repos."""
        from scripts.add_client import _detect_type_platform
        repo = self.test_dir / "empty_repo"
        repo.mkdir()
        rtype, platform = _detect_type_platform(repo)
        self.assertEqual(rtype, "mixed")
        self.assertEqual(platform, "unknown")


class TestPopulateChromaDBLockCheck(unittest.TestCase):
    """Test _is_db_locked helper."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_no_db_file_not_locked(self):
        """_is_db_locked returns False when file doesn't exist."""
        from scripts.populate_chromadb import _is_db_locked
        result = _is_db_locked(self.test_dir)
        self.assertFalse(result)

    def test_unlocked_db(self):
        """_is_db_locked returns False for an unlocked sqlite3 file."""
        from scripts.populate_chromadb import _is_db_locked
        import sqlite3
        db_path = self.test_dir / "chroma.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()
        result = _is_db_locked(self.test_dir)
        self.assertFalse(result)


class TestSyncKBFormatTime(unittest.TestCase):
    """Test _format_time helper."""

    def test_seconds_only(self):
        from scripts.sync_kb import _format_time
        self.assertEqual(_format_time(45), "45s")

    def test_minutes_and_seconds(self):
        from scripts.sync_kb import _format_time
        self.assertEqual(_format_time(125), "2m 5s")

    def test_zero(self):
        from scripts.sync_kb import _format_time
        self.assertEqual(_format_time(0), "0s")


if __name__ == "__main__":
    unittest.main()
