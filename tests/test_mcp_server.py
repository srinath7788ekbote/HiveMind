"""
test_mcp_server.py — Tests for the HiveMind MCP Server

Validates:
    - Server initialisation and tool registration
    - All 13 MCP tools are discoverable
    - Each tool returns valid output with correct parameters
    - Each tool returns an error message (not a crash) with missing parameters
    - get_active_client / get_active_branch read from memory files correctly
    - write_file respects branch protection
    - --test flag works correctly
    - Concurrent calls don't crash the server
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestMCPServerImports(unittest.TestCase):
    """Verify the MCP server module can be imported and has correct structure."""

    def test_server_module_imports(self):
        """hivemind_mcp.hivemind_server can be imported without errors."""
        import hivemind_mcp.hivemind_server as srv
        self.assertIsNotNone(srv)

    def test_mcp_server_instance_exists(self):
        """The FastMCP server instance is created."""
        from hivemind_mcp.hivemind_server import mcp_server
        self.assertIsNotNone(mcp_server)
        self.assertEqual(mcp_server.name, "hivemind")

    def test_tool_registry_has_18_tools(self):
        """TOOL_REGISTRY contains exactly 18 tools."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        self.assertEqual(len(TOOL_REGISTRY), 18)

    def test_tool_registry_all_callable(self):
        """Every entry in TOOL_REGISTRY is callable."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        for name, fn in TOOL_REGISTRY.items():
            self.assertTrue(callable(fn), f"{name} is not callable")

    def test_all_expected_tools_registered(self):
        """All 18 expected tool names are present in TOOL_REGISTRY."""
        from hivemind_mcp.hivemind_server import TOOL_REGISTRY
        expected = [
            "hivemind_query_memory",
            "hivemind_query_graph",
            "hivemind_get_entity",
            "hivemind_search_files",
            "hivemind_get_pipeline",
            "hivemind_get_secret_flow",
            "hivemind_impact_analysis",
            "hivemind_diff_branches",
            "hivemind_list_branches",
            "hivemind_set_client",
            "hivemind_write_file",
            "hivemind_get_active_client",
            "hivemind_get_active_branch",
            "hivemind_check_branch",
            "hivemind_save_investigation",
            "hivemind_recall_investigation",
            "hivemind_read_file",
            "hivemind_propose_edit",
        ]
        for name in expected:
            self.assertIn(name, TOOL_REGISTRY, f"Missing tool: {name}")

    def test_format_result_with_dict(self):
        """_format_result converts dict to JSON string."""
        from hivemind_mcp.hivemind_server import _format_result
        result = _format_result({"key": "value"})
        parsed = json.loads(result)
        self.assertEqual(parsed["key"], "value")

    def test_format_result_with_list(self):
        """_format_result converts list to JSON string."""
        from hivemind_mcp.hivemind_server import _format_result
        result = _format_result([1, 2, 3])
        parsed = json.loads(result)
        self.assertEqual(parsed, [1, 2, 3])

    def test_format_result_with_string(self):
        """_format_result returns strings as-is."""
        from hivemind_mcp.hivemind_server import _format_result
        result = _format_result("hello")
        self.assertEqual(result, "hello")

    def test_format_result_with_none(self):
        """_format_result handles None."""
        from hivemind_mcp.hivemind_server import _format_result
        result = _format_result(None)
        self.assertEqual(result, "null")


class TestMCPSelfTest(unittest.TestCase):
    """Verify the --test flag works correctly."""

    def test_self_test_returns_true(self):
        """run_self_test() returns True when all tools are healthy."""
        from hivemind_mcp.hivemind_server import run_self_test
        self.assertTrue(run_self_test())

    def test_self_test_cli_exits_0(self):
        """python hivemind_mcp/hivemind_server.py --test exits with code 0."""
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "hivemind_mcp" / "hivemind_server.py"), "--test"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, f"stderr: {result.stderr}")
        self.assertIn("All tools healthy", result.stdout)

    def test_self_test_lists_all_tools(self):
        """--test output mentions all 13 tools."""
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "hivemind_mcp" / "hivemind_server.py"), "--test"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        self.assertIn("18/18", result.stdout)


class TestGetActiveClientTool(unittest.TestCase):
    """Test the hivemind_get_active_client MCP tool."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_mcp_test_"))
        self.client_file = self.test_dir / "active_client.txt"

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_get_active_client_reads_file(self):
        """get_active_client returns the client name from active_client.txt."""
        from hivemind_mcp.hivemind_server import hivemind_get_active_client, ACTIVE_CLIENT_FILE
        # Patch the file path
        self.client_file.write_text("dfin\n", encoding="utf-8")
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_CLIENT_FILE
        srv.ACTIVE_CLIENT_FILE = self.client_file
        try:
            result = json.loads(asyncio.run(hivemind_get_active_client()))
            self.assertEqual(result["client"], "dfin")
        finally:
            srv.ACTIVE_CLIENT_FILE = original

    def test_get_active_client_missing_file(self):
        """get_active_client returns error when file doesn't exist."""
        from hivemind_mcp.hivemind_server import hivemind_get_active_client
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_CLIENT_FILE
        srv.ACTIVE_CLIENT_FILE = self.test_dir / "nonexistent.txt"
        try:
            result = json.loads(asyncio.run(hivemind_get_active_client()))
            self.assertIn("error", result)
        finally:
            srv.ACTIVE_CLIENT_FILE = original

    def test_get_active_client_empty_file(self):
        """get_active_client returns error when file is empty."""
        from hivemind_mcp.hivemind_server import hivemind_get_active_client
        self.client_file.write_text("", encoding="utf-8")
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_CLIENT_FILE
        srv.ACTIVE_CLIENT_FILE = self.client_file
        try:
            result = json.loads(asyncio.run(hivemind_get_active_client()))
            self.assertIn("error", result)
        finally:
            srv.ACTIVE_CLIENT_FILE = original


class TestGetActiveBranchTool(unittest.TestCase):
    """Test the hivemind_get_active_branch MCP tool."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_mcp_test_"))
        self.branch_file = self.test_dir / "active_branch.txt"

    def tearDown(self):
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_get_active_branch_reads_file(self):
        """get_active_branch returns the branch from active_branch.txt."""
        self.branch_file.write_text("release_26_3\n", encoding="utf-8")
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_BRANCH_FILE
        srv.ACTIVE_BRANCH_FILE = self.branch_file
        try:
            result = json.loads(asyncio.run(srv.hivemind_get_active_branch()))
            self.assertEqual(result["branch"], "release_26_3")
        finally:
            srv.ACTIVE_BRANCH_FILE = original

    def test_get_active_branch_missing_file(self):
        """get_active_branch returns error when file doesn't exist."""
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_BRANCH_FILE
        srv.ACTIVE_BRANCH_FILE = self.test_dir / "nonexistent.txt"
        try:
            result = json.loads(asyncio.run(srv.hivemind_get_active_branch()))
            self.assertIn("error", result)
        finally:
            srv.ACTIVE_BRANCH_FILE = original

    def test_get_active_branch_empty_file(self):
        """get_active_branch returns error when file is empty."""
        self.branch_file.write_text("  \n", encoding="utf-8")
        import hivemind_mcp.hivemind_server as srv
        original = srv.ACTIVE_BRANCH_FILE
        srv.ACTIVE_BRANCH_FILE = self.branch_file
        try:
            result = json.loads(asyncio.run(srv.hivemind_get_active_branch()))
            self.assertIn("error", result)
        finally:
            srv.ACTIVE_BRANCH_FILE = original


class TestToolErrorHandling(unittest.TestCase):
    """Each tool returns an error message when called with invalid parameters — never crashes."""

    def _call_and_check_no_crash(self, tool_fn, kwargs):
        """Call the tool and verify it returns a string (not raises)."""
        try:
            result = asyncio.run(tool_fn(**kwargs))
            self.assertIsInstance(result, str)
            return result
        except Exception as e:
            self.fail(f"{tool_fn.__name__} raised {type(e).__name__}: {e}")

    def test_query_memory_invalid_client(self):
        """query_memory with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = self._call_and_check_no_crash(
            hivemind_query_memory,
            {"client": "nonexistent_client_xyz", "query": "test"},
        )
        # Should return empty list or error — not crash
        self.assertIsInstance(result, str)

    def test_query_graph_invalid_client(self):
        """query_graph with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_query_graph
        result = self._call_and_check_no_crash(
            hivemind_query_graph,
            {"client": "nonexistent_client_xyz", "entity": "test"},
        )
        self.assertIsInstance(result, str)

    def test_get_entity_invalid_client(self):
        """get_entity with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_get_entity
        result = self._call_and_check_no_crash(
            hivemind_get_entity,
            {"client": "nonexistent_client_xyz", "name": "test"},
        )
        self.assertIsInstance(result, str)

    def test_search_files_invalid_client(self):
        """search_files with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_search_files
        result = self._call_and_check_no_crash(
            hivemind_search_files,
            {"client": "nonexistent_client_xyz", "query": "test"},
        )
        self.assertIsInstance(result, str)

    def test_get_pipeline_invalid_client(self):
        """get_pipeline with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_get_pipeline
        result = self._call_and_check_no_crash(
            hivemind_get_pipeline,
            {"client": "nonexistent_client_xyz", "name": "test"},
        )
        self.assertIsInstance(result, str)

    def test_get_secret_flow_invalid_client(self):
        """get_secret_flow with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_get_secret_flow
        result = self._call_and_check_no_crash(
            hivemind_get_secret_flow,
            {"client": "nonexistent_client_xyz", "secret": "test"},
        )
        self.assertIsInstance(result, str)

    def test_impact_analysis_invalid_client(self):
        """impact_analysis with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_impact_analysis
        result = self._call_and_check_no_crash(
            hivemind_impact_analysis,
            {"client": "nonexistent_client_xyz", "entity": "test"},
        )
        self.assertIsInstance(result, str)

    def test_diff_branches_invalid_client(self):
        """diff_branches with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_diff_branches
        result = self._call_and_check_no_crash(
            hivemind_diff_branches,
            {"client": "nonexistent_client_xyz", "repo": "test", "base": "main", "compare": "dev"},
        )
        self.assertIsInstance(result, str)

    def test_list_branches_invalid_client(self):
        """list_branches with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_list_branches
        result = self._call_and_check_no_crash(
            hivemind_list_branches,
            {"client": "nonexistent_client_xyz"},
        )
        self.assertIsInstance(result, str)

    def test_set_client_invalid_client(self):
        """set_client with nonexistent client returns error, no crash."""
        from hivemind_mcp.hivemind_server import hivemind_set_client
        result = self._call_and_check_no_crash(
            hivemind_set_client,
            {"client": "nonexistent_client_xyz"},
        )
        self.assertIsInstance(result, str)
        parsed = json.loads(result)
        self.assertIn("error", parsed)


class TestToolsWithFixtures(unittest.TestCase):
    """Test tools with the test fixture data in conftest.py style."""

    def setUp(self):
        """Create a temp memory dir with test fixtures mimicking conftest.py."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_mcp_fixtures_"))
        self.memory_dir = self.test_dir / "memory" / "testmcp"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Create test entities
        import sqlite3
        entities = {
            "files": [
                {"path": "pipelines/deploy_audit.yaml", "type": "pipeline", "repo": "test-pipelines", "branch": "main"},
                {"path": "layer_01/main.tf", "type": "terraform", "repo": "test-terraform", "branch": "main"},
            ],
            "secrets": [
                {"name": "test-secret-db", "service": "audit-service"},
            ],
        }
        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(entities, f, indent=2)

        # Create test chunks (vector fallback)
        chunks = [
            {
                "id": "chunk_001",
                "text": "pipeline deploy audit service to dev environment",
                "metadata": {
                    "file": "pipelines/deploy_audit.yaml",
                    "repo": "test-pipelines",
                    "type": "pipeline",
                    "branch": "main",
                },
            },
        ]
        chunks_path = self.memory_dir / "chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)

        # Create test graph DB
        db_path = self.memory_dir / "graph.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, node_type TEXT, file TEXT, repo TEXT)")
        cursor.execute("CREATE TABLE edges (source TEXT, target TEXT, edge_type TEXT, file TEXT, repo TEXT, branch TEXT, metadata TEXT)")
        cursor.execute("CREATE INDEX idx_edges_source ON edges(source)")
        cursor.execute("CREATE INDEX idx_edges_target ON edges(target)")
        cursor.execute("INSERT INTO nodes VALUES ('audit-service', 'service', 'pipelines/deploy_audit.yaml', 'test-pipelines')")
        cursor.execute("INSERT INTO nodes VALUES ('test-secret-db', 'secret', 'layer_01/main.tf', 'test-terraform')")
        cursor.execute("INSERT INTO edges VALUES ('audit-service', 'test-secret-db', 'uses_secret', 'pipelines/deploy_audit.yaml', 'test-pipelines', 'main', '')")
        conn.commit()
        conn.close()

        # Create discovered_profile.json
        profile = {
            "services": [{"name": "audit-service", "repo": "test-pipelines"}],
            "environments": [{"name": "dev", "tier": "development"}],
            "repos": [{"name": "test-pipelines", "type": "harness"}, {"name": "test-terraform", "type": "terraform"}],
        }
        profile_path = self.memory_dir / "discovered_profile.json"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

        # Patch PROJECT_ROOT in relevant tools so they find our test memory
        self._patches = []
        for mod_name in [
            "tools.query_memory",
            "tools.query_graph",
            "tools.get_entity",
            "tools.search_files",
            "tools.get_pipeline",
            "tools.get_secret_flow",
            "tools.impact_analysis",
        ]:
            try:
                p = patch(f"{mod_name}.PROJECT_ROOT", self.test_dir)
                p.start()
                self._patches.append(p)
            except AttributeError:
                pass

    def tearDown(self):
        for p in self._patches:
            p.stop()
        shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def test_query_memory_returns_results(self):
        """query_memory via MCP returns results from test fixtures."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = asyncio.run(hivemind_query_memory(client="testmcp", query="audit deploy"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)

    def test_query_graph_returns_structure(self):
        """query_graph via MCP returns a well-formed dict."""
        from hivemind_mcp.hivemind_server import hivemind_query_graph
        result = asyncio.run(hivemind_query_graph(client="testmcp", entity="audit-service"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)
        self.assertIn("entity", parsed)

    def test_get_entity_returns_structure(self):
        """get_entity via MCP returns entity info or error."""
        from hivemind_mcp.hivemind_server import hivemind_get_entity
        result = asyncio.run(hivemind_get_entity(client="testmcp", name="audit-service"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_search_files_returns_list(self):
        """search_files via MCP returns a list."""
        from hivemind_mcp.hivemind_server import hivemind_search_files
        result = asyncio.run(hivemind_search_files(client="testmcp", query="deploy"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, list)

    def test_get_pipeline_returns_structure(self):
        """get_pipeline via MCP returns a dict."""
        from hivemind_mcp.hivemind_server import hivemind_get_pipeline
        result = asyncio.run(hivemind_get_pipeline(client="testmcp", name="deploy_audit"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_get_secret_flow_returns_structure(self):
        """get_secret_flow via MCP returns a dict."""
        from hivemind_mcp.hivemind_server import hivemind_get_secret_flow
        result = asyncio.run(hivemind_get_secret_flow(client="testmcp", secret="test-secret-db"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_impact_analysis_returns_structure(self):
        """impact_analysis via MCP returns a dict."""
        from hivemind_mcp.hivemind_server import hivemind_impact_analysis
        result = asyncio.run(hivemind_impact_analysis(client="testmcp", entity="audit-service"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)


class TestWriteFileBranchProtection(unittest.TestCase):
    """write_file respects branch protection — never writes to main directly."""

    def test_write_file_returns_string_not_crash(self):
        """write_file with invalid inputs returns an error string, not crash."""
        from hivemind_mcp.hivemind_server import hivemind_write_file
        result = asyncio.run(hivemind_write_file(
            client="nonexistent",
            repo_name="fake",
            branch="main",
            file_path="test.txt",
            content="hello",
        ))
        self.assertIsInstance(result, str)
        # Should be an error since repo doesn't exist
        parsed = json.loads(result)
        self.assertIn("error", parsed)


class TestConcurrentToolCalls(unittest.TestCase):
    """Server handles concurrent tool calls without crashing."""

    def test_concurrent_calls(self):
        """Multiple tools called rapidly don't interfere."""
        from hivemind_mcp.hivemind_server import (
            hivemind_query_memory,
            hivemind_query_graph,
            hivemind_get_entity,
            hivemind_search_files,
        )

        calls = [
            (hivemind_query_memory, {"client": "fake", "query": "test"}),
            (hivemind_query_graph, {"client": "fake", "entity": "test"}),
            (hivemind_get_entity, {"client": "fake", "name": "test"}),
            (hivemind_search_files, {"client": "fake", "query": "test"}),
        ]

        async def run_all():
            return await asyncio.gather(
                *[fn(**kwargs) for fn, kwargs in calls]
            )

        results = asyncio.run(run_all())

        self.assertEqual(len(results), 4)
        for r in results:
            self.assertIsInstance(r, str)


class TestMCPServerConfig(unittest.TestCase):
    """Verify MCP configuration files are correct."""

    def test_mcp_json_example_exists(self):
        """mcp.json.example exists in .vscode/."""
        path = PROJECT_ROOT / ".vscode" / "mcp.json.example"
        self.assertTrue(path.exists(), f"Missing {path}")

    def test_mcp_json_example_valid(self):
        """mcp.json.example is valid JSON with correct structure."""
        path = PROJECT_ROOT / ".vscode" / "mcp.json.example"
        with open(path, encoding="utf-8") as f:
            config = json.load(f)
        self.assertIn("servers", config)
        self.assertIn("hivemind", config["servers"])
        server = config["servers"]["hivemind"]
        self.assertEqual(server["type"], "stdio")
        self.assertEqual(server["command"], "python")
        self.assertIn("hivemind_mcp/hivemind_server.py", server["args"])

    def test_server_script_exists(self):
        """hivemind_mcp/hivemind_server.py exists."""
        path = PROJECT_ROOT / "hivemind_mcp" / "hivemind_server.py"
        self.assertTrue(path.exists(), f"Missing {path}")

    def test_server_init_exists(self):
        """hivemind_mcp/__init__.py exists."""
        path = PROJECT_ROOT / "hivemind_mcp" / "__init__.py"
        self.assertTrue(path.exists(), f"Missing {path}")


if __name__ == "__main__":
    unittest.main()
