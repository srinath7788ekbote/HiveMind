"""
Unit Tests — Get Entity

Tests tools/get_entity.py

Covers:
    - Exact match entity lookup
    - Fuzzy (LIKE) match with single result
    - Multiple matches returning candidates
    - Entity not found
    - Outbound and inbound edge retrieval
    - Related files collection
    - Branch filtering on edges
    - Missing graph DB
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestGetEntity(HiveMindTestCase):
    """Tests for tools/get_entity.py"""

    def setUp(self):
        super().setUp()
        self.create_test_graph_db(
            nodes=[
                ("pipeline:deploy_audit", "pipeline", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines"),
                ("audit_service", "service", ".harness/services/audit_service.yaml", "dfin-harness-pipelines"),
                ("template:rollout_k8s", "template", "templates/rollout_k8s.yaml", "dfin-harness-pipelines"),
                ("kv_secret:automation-dev-dbauditservice", "secret", "layer_01_keyvaults/main.tf", "Eastwood-terraform"),
                ("env:dev", "environment", ".harness/environments/dev.yaml", "dfin-harness-pipelines"),
                ("env:prod", "environment", ".harness/environments/prod.yaml", "dfin-harness-pipelines"),
            ],
            edges=[
                ("pipeline:deploy_audit", "audit_service", "USES_SERVICE", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "template:rollout_k8s", "CALLS_TEMPLATE", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "env:dev", "TARGETS_INFRA", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("pipeline:deploy_audit", "env:prod", "TARGETS_INFRA", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "main"),
                ("audit_service", "kv_secret:automation-dev-dbauditservice", "MOUNTS_SECRET", "charts/audit-service/templates/deployment.yaml", "Eastwood-helm", "main"),
                ("pipeline:deploy_audit", "env:dev", "TARGETS_INFRA", "pipelines/deploy_audit.yaml", "dfin-harness-pipelines", "develop"),
            ],
        )

    def _get(self, name, branch=None):
        from tools.get_entity import get_entity
        import tools.get_entity as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return get_entity("testclient", name, branch)
        finally:
            mod.PROJECT_ROOT = original_root

    # --- Exact match ---

    def test_exact_match(self):
        result = self._get("audit_service")
        self.assertNotIn("error", result)
        self.assertEqual(result["entity"]["id"], "audit_service")

    def test_exact_match_returns_node_type(self):
        result = self._get("audit_service")
        self.assertEqual(result["entity"]["node_type"], "service")

    def test_exact_match_returns_file(self):
        result = self._get("audit_service")
        self.assertEqual(result["entity"]["file"], ".harness/services/audit_service.yaml")

    def test_exact_match_returns_repo(self):
        result = self._get("audit_service")
        self.assertEqual(result["entity"]["repo"], "dfin-harness-pipelines")

    # --- Outbound edges ---

    def test_outbound_edges(self):
        result = self._get("pipeline:deploy_audit")
        self.assertGreater(len(result["outbound"]), 0)
        targets = [e["target"] for e in result["outbound"]]
        self.assertIn("audit_service", targets)
        self.assertIn("template:rollout_k8s", targets)

    def test_outbound_edges_have_required_keys(self):
        result = self._get("pipeline:deploy_audit")
        for edge in result["outbound"]:
            self.assertIn("source", edge)
            self.assertIn("target", edge)
            self.assertIn("edge_type", edge)

    # --- Inbound edges ---

    def test_inbound_edges(self):
        result = self._get("audit_service")
        self.assertGreater(len(result["inbound"]), 0)
        sources = [e["source"] for e in result["inbound"]]
        self.assertIn("pipeline:deploy_audit", sources)

    def test_inbound_entity_with_outbound(self):
        """audit_service has inbound (pipeline uses it) and outbound (mounts secret)."""
        result = self._get("audit_service")
        self.assertGreater(len(result["inbound"]), 0)
        self.assertGreater(len(result["outbound"]), 0)

    # --- Related files ---

    def test_related_files(self):
        result = self._get("pipeline:deploy_audit")
        self.assertIsInstance(result["related_files"], list)
        self.assertGreater(len(result["related_files"]), 0)
        self.assertIn("pipelines/deploy_audit.yaml", result["related_files"])

    def test_related_files_includes_edge_files(self):
        result = self._get("audit_service")
        # Should include the entity's own file + edge files
        self.assertIn(".harness/services/audit_service.yaml", result["related_files"])

    def test_related_files_sorted(self):
        result = self._get("pipeline:deploy_audit")
        self.assertEqual(result["related_files"], sorted(result["related_files"]))

    # --- Fuzzy match ---

    def test_fuzzy_match_single(self):
        """LIKE match with unique substring."""
        result = self._get("rollout_k8s")
        self.assertNotIn("error", result)
        self.assertEqual(result["entity"]["id"], "template:rollout_k8s")

    def test_fuzzy_match_multiple_returns_candidates(self):
        """LIKE match with ambiguous substring returns candidates."""
        result = self._get("env:")
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Multiple matches")
        self.assertIn("candidates", result)
        self.assertGreaterEqual(len(result["candidates"]), 2)

    def test_candidates_have_id_and_type(self):
        result = self._get("env:")
        for c in result["candidates"]:
            self.assertIn("id", c)
            self.assertIn("node_type", c)

    # --- Not found ---

    def test_entity_not_found(self):
        result = self._get("completely_nonexistent_entity")
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    # --- Branch filtering ---

    def test_branch_filter_main(self):
        result = self._get("pipeline:deploy_audit", branch="main")
        self.assertNotIn("error", result)
        # All edges should be on main branch
        for edge in result["outbound"]:
            branch = edge.get("branch")
            self.assertTrue(branch == "main" or branch is None)

    def test_branch_filter_develop(self):
        result = self._get("pipeline:deploy_audit", branch="develop")
        self.assertNotIn("error", result)
        # Should find the develop edge
        branches = [e.get("branch") for e in result["outbound"]]
        self.assertTrue(any(b == "develop" or b is None for b in branches))

    # --- Missing DB ---

    def test_missing_graph_db(self):
        from tools.get_entity import get_entity
        import tools.get_entity as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir / "nonexistent"
        try:
            result = get_entity("testclient", "anything")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertIn("error", result)
        self.assertIn("Graph DB not found", result["error"])

    # --- Edge case: entity with no edges ---

    def test_entity_no_edges(self):
        result = self._get("kv_secret:automation-dev-dbauditservice")
        self.assertNotIn("error", result)
        self.assertEqual(result["entity"]["id"], "kv_secret:automation-dev-dbauditservice")
        # May or may not have edges depending on direction, but should not error
        self.assertIsInstance(result["outbound"], list)
        self.assertIsInstance(result["inbound"], list)


if __name__ == "__main__":
    unittest.main()
