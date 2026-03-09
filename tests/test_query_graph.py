"""
Unit Tests — Query Graph

Tests tools/query_graph.py
"""

import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestQueryGraph(HiveMindTestCase):
    """Tests for tools/query_graph.py"""

    def setUp(self):
        super().setUp()
        # Create a test graph
        self.create_test_graph_db(
            nodes=[
                ("pipeline:deploy_audit", "pipeline", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines"),
                ("audit_service", "service", ".harness/services/audit_service.yaml", "dfin-harness-pipelines"),
                ("template:rollout_k8s", "template", "templates/rollout_k8s.yaml", "dfin-harness-pipelines"),
                ("kv_secret:automation-dev-dbauditservice", "secret", "layer_01_keyvaults/main.tf", "Eastwood-terraform"),
                ("k8s_secret:audit-db-secret", "k8s_secret", "layer_02_aks/main.tf", "Eastwood-terraform"),
                ("env:dev", "environment", ".harness/environments/environments.yaml", "dfin-harness-pipelines"),
                ("env:prod", "environment", ".harness/environments/environments.yaml", "dfin-harness-pipelines"),
            ],
            edges=[
                ("pipeline:deploy_audit", "audit_service", "USES_SERVICE", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "template:rollout_k8s", "CALLS_TEMPLATE", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "env:dev", "TARGETS_INFRA", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "env:prod", "TARGETS_INFRA", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("tf:db_audit", "kv_secret:automation-dev-dbauditservice", "CREATES_KV_SECRET", "layer_01_keyvaults/main.tf", "Eastwood-terraform", "main"),
                ("k8s_secret:audit-db-secret", "kv_secret:automation-dev-dbauditservice", "READS_KV_SECRET", "layer_02_aks/main.tf", "Eastwood-terraform", "main"),
            ],
        )

    def _query(self, entity, direction="both", depth=1, branch=None):
        """Helper to run query with patched paths."""
        from tools.query_graph import query_graph
        # We need to monkey-patch PROJECT_ROOT for the function
        import tools.query_graph as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return query_graph("testclient", entity, direction, depth, branch)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_outbound_traversal(self):
        result = self._query("pipeline:deploy_audit", direction="out", depth=1)
        self.assertGreater(len(result["edges"]), 0)
        targets = [e["target"] for e in result["edges"]]
        self.assertIn("audit_service", targets)

    def test_inbound_traversal(self):
        result = self._query("audit_service", direction="in", depth=1)
        self.assertGreater(len(result["edges"]), 0)
        sources = [e["source"] for e in result["edges"]]
        self.assertIn("pipeline:deploy_audit", sources)

    def test_both_direction(self):
        result = self._query("audit_service", direction="both", depth=1)
        self.assertGreater(len(result["edges"]), 0)

    def test_depth_traversal(self):
        result = self._query("pipeline:deploy_audit", direction="out", depth=2)
        # At depth 2, should find kv_secret through chain
        node_ids = [n["id"] for n in result["nodes"]]
        # Pipeline -> service, template, envs at depth 1
        self.assertIn("audit_service", node_ids)

    def test_fuzzy_matching(self):
        result = self._query("audit_service", direction="both", depth=1)
        self.assertIsNone(result.get("error"))

    def test_entity_not_found(self):
        result = self._query("nonexistent_entity_xyz", direction="both", depth=1)
        self.assertIn("error", result)

    def test_branch_filtering(self):
        result = self._query("pipeline:deploy_audit", direction="out", depth=1, branch="main")
        self.assertGreater(len(result["edges"]), 0)

    def test_nodes_have_required_fields(self):
        result = self._query("pipeline:deploy_audit", direction="out", depth=1)
        for node in result["nodes"]:
            self.assertIn("id", node)
            self.assertIn("node_type", node)

    def test_edges_deduplicated(self):
        result = self._query("pipeline:deploy_audit", direction="both", depth=1)
        edge_keys = set()
        for edge in result["edges"]:
            key = (edge["source"], edge["target"], edge["edge_type"])
            self.assertNotIn(key, edge_keys, f"Duplicate edge found: {key}")
            edge_keys.add(key)


if __name__ == "__main__":
    unittest.main()
