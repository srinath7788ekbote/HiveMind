"""
Unit Tests — Secret Flow

Tests tools/get_secret_flow.py
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestGetSecretFlow(HiveMindTestCase):
    """Tests for tools/get_secret_flow.py"""

    def setUp(self):
        super().setUp()

        # Create graph DB with secret flow edges
        self.create_test_graph_db(
            nodes=[
                ("tf:db_audit_service", "terraform_resource", "layer_01_keyvaults/main.tf", "Eastwood-terraform"),
                ("kv_secret:automation-dev-dbauditservice", "kv_secret", "layer_01_keyvaults/main.tf", "Eastwood-terraform"),
                ("tf:data_db_audit", "terraform_data", "layer_02_aks/main.tf", "Eastwood-terraform"),
                ("k8s_secret:audit-db-secret", "k8s_secret", "layer_02_aks/main.tf", "Eastwood-terraform"),
                ("helm:audit-deployment", "helm_template", "charts/audit-service/templates/deployment.yaml", "Eastwood-helm"),
            ],
            edges=[
                ("tf:db_audit_service", "kv_secret:automation-dev-dbauditservice", "CREATES_KV_SECRET", "layer_01_keyvaults/main.tf", "Eastwood-terraform", "main"),
                ("tf:data_db_audit", "kv_secret:automation-dev-dbauditservice", "READS_KV_SECRET", "layer_02_aks/main.tf", "Eastwood-terraform", "main"),
                ("k8s_secret:audit-db-secret", "kv_secret:automation-dev-dbauditservice", "CREATES_K8S_SECRET", "layer_02_aks/main.tf", "Eastwood-terraform", "main"),
                ("helm:audit-deployment", "k8s_secret:audit-db-secret", "MOUNTS_SECRET", "charts/audit-service/templates/deployment.yaml", "Eastwood-helm", "main"),
            ],
        )

        # Create entities.json with secret info
        self.create_test_entities({
            "files": [],
            "secrets": [
                {"name": "automation-dev-dbauditservice", "service": "audit-service"},
            ],
        })

    def _trace(self, secret, branch=None):
        """Helper to trace secret flow with patched paths."""
        from tools.get_secret_flow import get_secret_flow
        import tools.get_secret_flow as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return get_secret_flow("testclient", secret, branch)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_traces_creation(self):
        result = self._trace("dbauditservice")
        self.assertGreater(len(result["creation"]), 0)

    def test_traces_reads(self):
        result = self._trace("dbauditservice")
        self.assertGreater(len(result["reads"]), 0)

    def test_traces_k8s_mounts(self):
        result = self._trace("dbauditservice")
        self.assertGreater(len(result["k8s_mounts"]), 0)

    def test_traces_helm_mounts(self):
        result = self._trace("audit-db-secret")
        self.assertGreater(len(result["helm_mounts"]), 0)

    def test_consuming_services(self):
        result = self._trace("dbauditservice")
        services = [s.get("service", "") for s in result["consuming_services"]]
        self.assertIn("audit-service", services)

    def test_flow_summary(self):
        result = self._trace("dbauditservice")
        self.assertIsInstance(result["flow_summary"], str)
        self.assertGreater(len(result["flow_summary"]), 0)
        self.assertNotIn("No flow trace found", result["flow_summary"])

    def test_unknown_secret(self):
        result = self._trace("completely_unknown_secret_xyz")
        self.assertIn("No flow trace found", result["flow_summary"])

    def test_branch_filter(self):
        result = self._trace("dbauditservice", branch="main")
        # Should still find results (our test data is on main)
        self.assertGreater(
            len(result["creation"]) + len(result["reads"]) + len(result["k8s_mounts"]),
            0,
        )

    def test_partial_name_match(self):
        """Test that partial secret name matching works."""
        result = self._trace("dbaudit")
        # Should match automation-dev-dbauditservice
        total = len(result["creation"]) + len(result["reads"]) + len(result["k8s_mounts"])
        self.assertGreater(total, 0)

    def test_result_structure(self):
        result = self._trace("dbauditservice")
        expected_keys = ["secret", "creation", "reads", "k8s_mounts", "helm_mounts", "consuming_services", "flow_summary"]
        for key in expected_keys:
            self.assertIn(key, result, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
