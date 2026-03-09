"""
Unit Tests — Relationship Extraction

Tests ingest/extract_relationships.py
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO, FAKE_TERRAFORM_REPO, FAKE_HELM_REPO
from ingest.extract_relationships import (
    extract_relationships,
    save_to_graph_db,
    CALLS_TEMPLATE,
    USES_SERVICE,
    TARGETS_INFRA,
    MOUNTS_SECRET,
    CREATES_KV_SECRET,
    CREATES_K8S_SECRET,
    READS_KV_SECRET,
    DEPENDS_ON,
    OUTPUTS_TO,
    REFERENCES,
)


class TestEdgeTypeConstants(unittest.TestCase):
    """Tests for edge type constants."""

    def test_expected_edge_types_exist(self):
        # Edge types are individual module-level constants (not a collection)
        self.assertEqual(CALLS_TEMPLATE, "CALLS_TEMPLATE")
        self.assertEqual(USES_SERVICE, "USES_SERVICE")
        self.assertEqual(TARGETS_INFRA, "TARGETS_INFRA")
        self.assertEqual(MOUNTS_SECRET, "MOUNTS_SECRET")
        self.assertEqual(CREATES_KV_SECRET, "CREATES_KV_SECRET")
        self.assertEqual(CREATES_K8S_SECRET, "CREATES_K8S_SECRET")
        self.assertEqual(READS_KV_SECRET, "READS_KV_SECRET")
        self.assertEqual(DEPENDS_ON, "DEPENDS_ON")


class TestExtractRelationships(HiveMindTestCase):
    """Tests for extract_relationships() — the main API."""

    def test_extracts_from_harness_repo(self):
        edges = extract_relationships(str(FAKE_HARNESS_REPO))
        self.assertGreater(len(edges), 0)

    def test_pipeline_template_ref(self):
        """pipeline.yaml has templateRef: rollout_k8s -> CALLS_TEMPLATE edge."""
        edges = extract_relationships(str(FAKE_HARNESS_REPO))
        template_edges = [e for e in edges if e["edge_type"] == CALLS_TEMPLATE]
        self.assertGreater(len(template_edges), 0, "Should find templateRef in pipeline.yaml")
        targets = [e["target"] for e in template_edges]
        self.assertIn("rollout_k8s", targets)

    def test_pipeline_service_ref(self):
        """pipeline.yaml has serviceRef: audit_service -> USES_SERVICE edge."""
        edges = extract_relationships(str(FAKE_HARNESS_REPO))
        service_edges = [e for e in edges if e["edge_type"] == USES_SERVICE]
        targets = [e["target"] for e in service_edges]
        self.assertIn("audit_service", targets)

    def test_terraform_kv_secret(self):
        edges = extract_relationships(str(FAKE_TERRAFORM_REPO))
        kv_edges = [e for e in edges if e["edge_type"] == CREATES_KV_SECRET]
        self.assertGreater(len(kv_edges), 0, "Should find azurerm_key_vault_secret resources")

    def test_terraform_reads_kv_secret(self):
        edges = extract_relationships(str(FAKE_TERRAFORM_REPO))
        read_edges = [e for e in edges if e["edge_type"] == READS_KV_SECRET]
        self.assertGreater(len(read_edges), 0, "Should find data.azurerm_key_vault_secret")

    def test_helm_mounts_secret(self):
        edges = extract_relationships(str(FAKE_HELM_REPO))
        mount_edges = [e for e in edges if e["edge_type"] == MOUNTS_SECRET]
        self.assertGreater(len(mount_edges), 0, "Should find secretKeyRef in helm templates")

    def test_extracts_from_terraform_repo(self):
        edges = extract_relationships(str(FAKE_TERRAFORM_REPO))
        self.assertGreater(len(edges), 0)

    def test_edges_have_required_keys(self):
        edges = extract_relationships(str(FAKE_HARNESS_REPO))
        for edge in edges:
            self.assertIn("source", edge)
            self.assertIn("target", edge)
            self.assertIn("edge_type", edge)
            self.assertIn("file", edge)

    def test_empty_dir_returns_empty(self):
        edges = extract_relationships(str(self.test_dir))
        self.assertEqual(edges, [])


class TestSaveToGraphDb(HiveMindTestCase):
    """Tests for save_to_graph_db()"""

    def test_creates_database(self):
        edges = [
            {
                "source": "pipeline:deploy_audit",
                "target": "audit_service",
                "edge_type": "USES_SERVICE",
                "file": "pipelines/deploy_audit.yaml",
                "repo": "dfin-harness-pipelines",
                "branch": "main",
            }
        ]
        db_path = self.memory_dir / "graph.sqlite"
        save_to_graph_db(edges, str(db_path))
        self.assertTrue(db_path.exists())

    def test_stores_edges(self):
        edges = [
            {
                "source": "pipeline:deploy_audit",
                "target": "audit_service",
                "edge_type": "USES_SERVICE",
                "file": "pipelines/deploy_audit.yaml",
                "repo": "dfin-harness-pipelines",
                "branch": "main",
            },
            {
                "source": "tf:db_audit_service",
                "target": "kv_secret:automation-dev-dbauditservice",
                "edge_type": "CREATES_KV_SECRET",
                "file": "layer_01_keyvaults/main.tf",
                "repo": "Eastwood-terraform",
                "branch": "main",
            },
        ]
        db_path = self.memory_dir / "graph.sqlite"
        save_to_graph_db(edges, str(db_path))

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM edges")
        count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(count, 2)

    def test_creates_indexes(self):
        edges = [
            {
                "source": "a",
                "target": "b",
                "edge_type": "DEPENDS_ON",
                "file": "test.yaml",
                "repo": "test",
                "branch": "main",
            }
        ]
        db_path = self.memory_dir / "graph.sqlite"
        save_to_graph_db(edges, str(db_path))

        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = [row[0] for row in cursor.fetchall()]
        conn.close()

        self.assertTrue(any("source" in idx for idx in indexes))
        self.assertTrue(any("target" in idx for idx in indexes))


if __name__ == "__main__":
    unittest.main()
