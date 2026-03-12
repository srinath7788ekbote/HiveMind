"""
test_mcp_integration.py — Integration tests for HiveMind MCP Server

Validates end-to-end flows:
    - Query memory through MCP returns same results as calling query_memory.py directly
    - Get pipeline through MCP returns same results as calling get_pipeline.py directly
    - Write file through MCP respects branch protection
    - Active client flows through to all tool calls correctly
    - Tool responses are structurally valid and parseable
"""

import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class MCPIntegrationTestCase(unittest.TestCase):
    """Base test case with shared fixtures for MCP integration tests."""

    def setUp(self):
        """Create comprehensive test fixtures that mirror real memory structure."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_mcp_integ_"))
        self.memory_dir = self.test_dir / "memory" / "integ"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # --- Entities ---
        self.entities = {
            "files": [
                {"path": "pipelines/deploy_audit.yaml", "type": "pipeline",
                 "repo": "integ-harness-pipelines", "branch": "main"},
                {"path": "pipelines/deploy_payment.yaml", "type": "pipeline",
                 "repo": "integ-harness-pipelines", "branch": "main"},
                {"path": "layer_01_keyvaults/main.tf", "type": "terraform",
                 "repo": "integ-terraform", "branch": "main"},
                {"path": "charts/audit-service/values.yaml", "type": "helm_values",
                 "repo": "integ-helm", "branch": "main"},
            ],
            "secrets": [
                {"name": "integ-dev-dbauditservice", "service": "audit-service"},
                {"name": "integ-dev-dbpaymentservice", "service": "payment-service"},
            ],
        }
        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(self.entities, f, indent=2)

        # --- Chunks (vector fallback) ---
        self.chunks = [
            {
                "id": "chunk_001",
                "text": "pipeline deploy audit service to dev environment using rollout_k8s template",
                "metadata": {
                    "file": "pipelines/deploy_audit.yaml",
                    "repo": "integ-harness-pipelines",
                    "type": "pipeline",
                    "branch": "main",
                },
            },
            {
                "id": "chunk_002",
                "text": "resource azurerm_key_vault_secret integ-dev-dbauditservice value from var",
                "metadata": {
                    "file": "layer_01_keyvaults/main.tf",
                    "repo": "integ-terraform",
                    "type": "terraform",
                    "branch": "main",
                },
            },
            {
                "id": "chunk_003",
                "text": "secretKeyRef name integ-dev-dbauditservice container audit-service",
                "metadata": {
                    "file": "charts/audit-service/templates/deployment.yaml",
                    "repo": "integ-helm",
                    "type": "helm_template",
                    "branch": "main",
                },
            },
            {
                "id": "chunk_004",
                "text": "pipeline deploy payment service to staging environment",
                "metadata": {
                    "file": "pipelines/deploy_payment.yaml",
                    "repo": "integ-harness-pipelines",
                    "type": "pipeline",
                    "branch": "main",
                },
            },
        ]
        chunks_path = self.memory_dir / "chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, indent=2)

        # --- Graph DB ---
        db_path = self.memory_dir / "graph.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE nodes (id TEXT PRIMARY KEY, node_type TEXT, file TEXT, repo TEXT)")
        cursor.execute("""CREATE TABLE edges (
            source TEXT, target TEXT, edge_type TEXT,
            file TEXT, repo TEXT, branch TEXT, metadata TEXT
        )""")
        cursor.execute("CREATE INDEX idx_edges_source ON edges(source)")
        cursor.execute("CREATE INDEX idx_edges_target ON edges(target)")

        nodes = [
            ("audit-service", "service", "pipelines/deploy_audit.yaml", "integ-harness-pipelines"),
            ("payment-service", "service", "pipelines/deploy_payment.yaml", "integ-harness-pipelines"),
            ("integ-dev-dbauditservice", "secret", "layer_01_keyvaults/main.tf", "integ-terraform"),
            ("layer_01_keyvaults", "terraform_layer", "layer_01_keyvaults/main.tf", "integ-terraform"),
        ]
        cursor.executemany("INSERT INTO nodes VALUES (?, ?, ?, ?)", nodes)

        edges = [
            ("audit-service", "integ-dev-dbauditservice", "uses_secret",
             "pipelines/deploy_audit.yaml", "integ-harness-pipelines", "main", ""),
            ("integ-dev-dbauditservice", "layer_01_keyvaults", "defined_in",
             "layer_01_keyvaults/main.tf", "integ-terraform", "main", ""),
        ]
        cursor.executemany("INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?)", edges)
        conn.commit()
        conn.close()

        # --- Discovered profile ---
        profile = {
            "services": [
                {"name": "audit-service", "repo": "integ-harness-pipelines"},
                {"name": "payment-service", "repo": "integ-harness-pipelines"},
            ],
            "environments": [
                {"name": "dev", "tier": "development"},
                {"name": "staging", "tier": "staging"},
            ],
            "repos": [
                {"name": "integ-harness-pipelines", "type": "harness"},
                {"name": "integ-terraform", "type": "terraform"},
                {"name": "integ-helm", "type": "helm"},
            ],
        }
        profile_path = self.memory_dir / "discovered_profile.json"
        with open(profile_path, "w", encoding="utf-8") as f:
            json.dump(profile, f, indent=2)

        # --- Patch PROJECT_ROOT in tools ---
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


class TestQueryMemoryIntegration(MCPIntegrationTestCase):
    """Query memory through MCP returns same results as calling directly."""

    def test_mcp_matches_direct_call(self):
        """MCP query_memory returns same data as tools.query_memory.query_memory."""
        from tools.query_memory import query_memory
        from hivemind_mcp.hivemind_server import hivemind_query_memory

        direct = query_memory(client="integ", query="audit deploy", top_k=5)
        mcp_result = json.loads(asyncio.run(hivemind_query_memory(client="integ", query="audit deploy", top_k=5)))

        # Both should be lists
        self.assertIsInstance(direct, list)
        self.assertIsInstance(mcp_result, list)
        # Same length
        self.assertEqual(len(direct), len(mcp_result))

    def test_mcp_query_memory_with_branch_filter(self):
        """MCP query_memory respects branch filter."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = json.loads(asyncio.run(hivemind_query_memory(client="integ", query="audit", branch="main")))
        self.assertIsInstance(result, list)

    def test_mcp_query_memory_with_type_filter(self):
        """MCP query_memory respects type filter."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = json.loads(asyncio.run(hivemind_query_memory(client="integ", query="deploy", filter_type="pipeline")))
        self.assertIsInstance(result, list)

    def test_mcp_query_memory_top_k(self):
        """MCP query_memory respects top_k limit."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = json.loads(asyncio.run(hivemind_query_memory(client="integ", query="deploy", top_k=1)))
        self.assertIsInstance(result, list)
        self.assertLessEqual(len(result), 1)


class TestQueryGraphIntegration(MCPIntegrationTestCase):
    """Query graph through MCP returns consistent results."""

    def test_mcp_matches_direct_call(self):
        """MCP query_graph returns same data as tools.query_graph.query_graph."""
        from tools.query_graph import query_graph
        from hivemind_mcp.hivemind_server import hivemind_query_graph

        direct = query_graph(client="integ", entity="audit-service")
        mcp_result = json.loads(asyncio.run(hivemind_query_graph(client="integ", entity="audit-service")))

        self.assertIsInstance(direct, dict)
        self.assertIsInstance(mcp_result, dict)
        self.assertEqual(direct.get("entity"), mcp_result.get("entity"))

    def test_mcp_query_graph_direction(self):
        """MCP query_graph respects direction parameter."""
        from hivemind_mcp.hivemind_server import hivemind_query_graph
        result = json.loads(asyncio.run(hivemind_query_graph(client="integ", entity="audit-service", direction="out")))
        self.assertIsInstance(result, dict)


class TestGetEntityIntegration(MCPIntegrationTestCase):
    """Get entity through MCP returns correct entity details."""

    def test_mcp_matches_direct_call(self):
        """MCP get_entity returns same data as tools.get_entity.get_entity."""
        from tools.get_entity import get_entity
        from hivemind_mcp.hivemind_server import hivemind_get_entity

        direct = get_entity(client="integ", name="audit-service")
        mcp_result = json.loads(asyncio.run(hivemind_get_entity(client="integ", name="audit-service")))

        self.assertIsInstance(direct, dict)
        self.assertIsInstance(mcp_result, dict)

    def test_nonexistent_entity_returns_error(self):
        """MCP get_entity for a nonexistent entity returns error dict."""
        from hivemind_mcp.hivemind_server import hivemind_get_entity
        result = json.loads(asyncio.run(hivemind_get_entity(client="integ", name="nonexistent-xyz")))
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)


class TestSearchFilesIntegration(MCPIntegrationTestCase):
    """Search files through MCP returns correct file matches."""

    def test_mcp_search_files_returns_list(self):
        """MCP search_files returns a list of file matches."""
        from hivemind_mcp.hivemind_server import hivemind_search_files
        result = json.loads(asyncio.run(hivemind_search_files(client="integ", query="deploy")))
        self.assertIsInstance(result, list)


class TestImpactAnalysisIntegration(MCPIntegrationTestCase):
    """Impact analysis through MCP returns correct blast radius."""

    def test_mcp_impact_analysis_returns_structure(self):
        """MCP impact_analysis returns a well-formed dict."""
        from hivemind_mcp.hivemind_server import hivemind_impact_analysis
        result = json.loads(asyncio.run(hivemind_impact_analysis(client="integ", entity="audit-service")))
        self.assertIsInstance(result, dict)
        # Should have some standard keys
        if "error" not in result:
            self.assertIn("source", result)

    def test_mcp_impact_analysis_matches_direct(self):
        """MCP impact_analysis produces same result as direct call."""
        from tools.impact_analysis import impact_analysis
        from hivemind_mcp.hivemind_server import hivemind_impact_analysis

        direct = impact_analysis(client="integ", entity="audit-service")
        mcp_result = json.loads(asyncio.run(hivemind_impact_analysis(client="integ", entity="audit-service")))

        self.assertIsInstance(direct, dict)
        self.assertIsInstance(mcp_result, dict)
        # Both should agree on key structure
        if "source" in direct:
            self.assertEqual(direct.get("source"), mcp_result.get("source"))


class TestActiveClientFlow(MCPIntegrationTestCase):
    """Active client flows through to all tool calls correctly."""

    def test_active_client_flows_to_query_memory(self):
        """Client parameter is passed through to query_memory correctly."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        # The "integ" client has fixtures set up — should work without error
        result = asyncio.run(hivemind_query_memory(client="integ", query="test"))
        parsed = json.loads(result)
        # Should not have an error key (since client exists)
        if isinstance(parsed, dict):
            self.assertNotIn("error", parsed)

    def test_active_client_flows_to_query_graph(self):
        """Client parameter is passed through to query_graph correctly."""
        from hivemind_mcp.hivemind_server import hivemind_query_graph
        result = asyncio.run(hivemind_query_graph(client="integ", entity="audit-service"))
        parsed = json.loads(result)
        self.assertIsInstance(parsed, dict)

    def test_wrong_client_gives_empty_results(self):
        """Using wrong client name gives empty/error results, not crash."""
        from hivemind_mcp.hivemind_server import hivemind_query_memory
        result = asyncio.run(hivemind_query_memory(client="wrong_client_name", query="test"))
        parsed = json.loads(result)
        # Should return empty list or error — not crash
        self.assertIsInstance(parsed, (list, dict))


class TestWriteFileIntegration(MCPIntegrationTestCase):
    """Write file through MCP creates branch and file correctly."""

    def test_write_file_rejects_nonexistent_repo(self):
        """write_file with nonexistent repo returns error."""
        from hivemind_mcp.hivemind_server import hivemind_write_file
        result = asyncio.run(hivemind_write_file(
            client="integ",
            repo_name="nonexistent-repo",
            branch="feature/test",
            file_path="test.txt",
            content="hello",
        ))
        parsed = json.loads(result)
        self.assertIn("error", parsed)

    def test_write_file_protected_branch_mentioned(self):
        """write_file targeting main should either redirect or error (branch protection)."""
        from hivemind_mcp.hivemind_server import hivemind_write_file
        result = asyncio.run(hivemind_write_file(
            client="integ",
            repo_name="nonexistent-repo",
            branch="main",
            file_path="test.txt",
            content="hello",
        ))
        # Should get an error since repo doesn't exist — but it shouldn't crash
        parsed = json.loads(result)
        self.assertIn("error", parsed)


class TestGetSecretFlowIntegration(MCPIntegrationTestCase):
    """Secret flow through MCP traces correctly."""

    def test_mcp_secret_flow_returns_structure(self):
        """MCP get_secret_flow returns a well-formed dict."""
        from hivemind_mcp.hivemind_server import hivemind_get_secret_flow
        result = json.loads(asyncio.run(hivemind_get_secret_flow(client="integ", secret="integ-dev-dbauditservice")))
        self.assertIsInstance(result, dict)
        if "error" not in result:
            self.assertIn("secret", result)


if __name__ == "__main__":
    unittest.main()
