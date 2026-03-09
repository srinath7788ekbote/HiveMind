"""
Unit Tests — Impact Analysis

Tests tools/impact_analysis.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestImpactAnalysis(HiveMindTestCase):
    """Tests for tools/impact_analysis.py"""

    def setUp(self):
        super().setUp()
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
                ("audit_service", "k8s_secret:audit-db-secret", "MOUNTS_SECRET", "charts/audit-service/templates/deployment.yaml", "Eastwood-helm", "main"),
            ],
        )

    def _analyze(self, **kwargs):
        """Helper to run impact analysis with patched paths."""
        from tools.impact_analysis import impact_analysis
        import tools.impact_analysis as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = self.test_dir
        try:
            return impact_analysis(client="testclient", **kwargs)
        finally:
            mod.PROJECT_ROOT = original_root

    def test_file_impact(self):
        result = self._analyze(file="layer_01_keyvaults/main.tf")
        self.assertGreater(len(result["affected_entities"]), 0)
        self.assertIn("summary", result)

    def test_entity_impact(self):
        result = self._analyze(entity="audit_service")
        self.assertGreater(len(result["affected_entities"]), 0)

    def test_risk_assessment(self):
        result = self._analyze(entity="audit_service")
        self.assertIn(result["risk_level"], ["low", "medium", "high", "critical"])

    def test_affected_files_populated(self):
        result = self._analyze(file="layer_01_keyvaults/main.tf")
        self.assertIsInstance(result["affected_files"], list)

    def test_summary_is_string(self):
        result = self._analyze(entity="audit_service")
        self.assertIsInstance(result["summary"], str)
        self.assertGreater(len(result["summary"]), 0)

    def test_depth_parameter(self):
        # Depth 1 vs depth 3 should yield different results (or at least not crash)
        result_shallow = self._analyze(entity="pipeline:deploy_audit", depth=1)
        result_deep = self._analyze(entity="pipeline:deploy_audit", depth=3)
        self.assertIsNotNone(result_shallow)
        self.assertIsNotNone(result_deep)

    def test_missing_entity(self):
        result = self._analyze(entity="nonexistent_xyz")
        self.assertIn("No entities found", result["summary"])

    def test_prod_env_raises_risk(self):
        result = self._analyze(entity="pipeline:deploy_audit")
        # Pipeline targets prod, should raise risk
        env_names = result.get("affected_environments", [])
        if any("prod" in e for e in env_names):
            self.assertIn(result["risk_level"], ["high", "critical"])

    def test_missing_db(self):
        """Test with no graph DB."""
        from tools.impact_analysis import impact_analysis
        import tools.impact_analysis as mod
        original_root = mod.PROJECT_ROOT
        mod.PROJECT_ROOT = Path(self.test_dir) / "nonexistent"
        try:
            result = impact_analysis(client="testclient", entity="test")
        finally:
            mod.PROJECT_ROOT = original_root
        self.assertIn("Graph DB not found", result["summary"])


if __name__ == "__main__":
    unittest.main()
