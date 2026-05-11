"""
Unit Tests — Settings Extraction

Tests ingest/extract_relationships.py for Spring Cloud Config settings files
and ingest/classify_files.py for config file classification.
"""

import json
import sqlite3
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_SETTINGS_REPO
from ingest.extract_relationships import (
    _extract_from_settings,
    extract_relationships,
    save_to_graph_db,
    CONNECTS_TO,
    DEFINES_CONFIG,
    OVERRIDES_FOR_ENV,
)
from ingest.classify_files import classify_file


class TestSettingsExtraction(HiveMindTestCase):
    """Tests for _extract_from_settings() and settings-aware extract_relationships()."""

    def setUp(self):
        super().setUp()
        self.repo = FAKE_SETTINGS_REPO
        self.cs_base = self.repo / "client-service" / "client-service.yaml"
        self.cs_prod = self.repo / "client-service" / "client-service-prod.yaml"
        self.cs_proddr = self.repo / "client-service" / "client-service-proddr.yaml"
        self.audit_prod = self.repo / "audit-service" / "audit-service-prod.yaml"
        self.app_yaml = self.repo / "application.yaml"
        self.app_prod = self.repo / "application-prod.yaml"

    # --- Endpoint extraction ---

    def test_extracts_servicebus_endpoint(self):
        """Finds sb-dfin-eus2-prd-rman.servicebus.windows.net as CONNECTS_TO edge."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        sb_edges = [
            e for e in edges
            if e["edge_type"] == CONNECTS_TO
            and "sb-dfin-eus2-prd-rman.servicebus.windows.net" in e["target"]
        ]
        self.assertTrue(len(sb_edges) >= 1, f"Expected servicebus endpoint edge, got: {sb_edges}")
        self.assertEqual(sb_edges[0]["target"], "endpoint:sb-dfin-eus2-prd-rman.servicebus.windows.net")

    def test_extracts_salesforce_endpoint(self):
        """Finds login.salesforce.com."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        sf_edges = [
            e for e in edges
            if e["edge_type"] == CONNECTS_TO and "salesforce" in e.get("endpoint_type", "")
        ]
        self.assertTrue(len(sf_edges) >= 1, f"Expected salesforce endpoint edge, got: {sf_edges}")

    def test_extracts_auth0_endpoint(self):
        """Finds prod.dfin.auth0app.com."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        auth0_edges = [
            e for e in edges
            if e["edge_type"] == CONNECTS_TO and "auth0" in e.get("endpoint_type", "")
        ]
        self.assertTrue(len(auth0_edges) >= 1, f"Expected auth0 endpoint edge, got: {auth0_edges}")

    def test_extracts_eventhub_endpoint(self):
        """Finds dfs-secaas-prod-dedicated-ehnamespace.servicebus.windows.net."""
        edges = _extract_from_settings(self.audit_prod, self.repo)
        eh_edges = [
            e for e in edges
            if e["edge_type"] == CONNECTS_TO
            and "dfs-secaas-prod-dedicated-ehnamespace" in e["target"]
        ]
        self.assertTrue(len(eh_edges) >= 1, f"Expected eventhub endpoint edge, got: {eh_edges}")

    def test_extracts_mail_host(self):
        """Finds 10.198.52.37 as internal_endpoint."""
        edges = _extract_from_settings(self.cs_base, self.repo)
        mail_edges = [
            e for e in edges
            if e["edge_type"] == CONNECTS_TO and "10.198.52.37" in e["target"]
        ]
        self.assertTrue(len(mail_edges) >= 1, f"Expected mail host endpoint edge, got: {mail_edges}")

    # --- Overlay relationships ---

    def test_overlay_creates_overrides_edge(self):
        """client-service-prod.yaml → OVERRIDES_FOR_ENV → client-service.yaml."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        override_edges = [e for e in edges if e["edge_type"] == OVERRIDES_FOR_ENV]
        self.assertTrue(len(override_edges) >= 1, f"Expected override edge, got: {override_edges}")
        targets = [e["target"] for e in override_edges]
        self.assertTrue(
            any("client-service/client-service.yaml" in t.replace("\\", "/") for t in targets),
            f"Expected override to base file, got targets: {targets}",
        )

    def test_proddr_overlay_creates_overrides_edge(self):
        """client-service-proddr.yaml → OVERRIDES_FOR_ENV → client-service.yaml."""
        edges = _extract_from_settings(self.cs_proddr, self.repo)
        override_edges = [e for e in edges if e["edge_type"] == OVERRIDES_FOR_ENV]
        self.assertTrue(len(override_edges) >= 1, f"Expected override edge, got: {override_edges}")

    # --- Config property nodes ---

    def test_config_prop_node_created(self):
        """config_prop:consumer.filings-analysis-service.servicebus.endpoint exists."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        prop_edges = [
            e for e in edges
            if e["edge_type"] == DEFINES_CONFIG
            and e["target"].startswith("config_prop:")
            and "servicebus" in e["target"]
            and "endpoint" in e["target"]
        ]
        self.assertTrue(len(prop_edges) >= 1, f"Expected config_prop edge for servicebus endpoint, got: {prop_edges}")

    def test_edge_metadata_has_yaml_key_path(self):
        """Edge metadata contains the dotted YAML path."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        connects_edges = [e for e in edges if e["edge_type"] == CONNECTS_TO]
        has_key_path = any("yaml_key_path" in e for e in connects_edges)
        self.assertTrue(has_key_path, "Expected yaml_key_path in CONNECTS_TO edge metadata")

    # --- Node type detection in save_to_graph_db ---

    def test_endpoint_node_type_detected(self):
        """endpoint: prefix → node_type = 'external_endpoint'."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        db_path = str(self.memory_dir / "test_graph.sqlite")
        save_to_graph_db(edges, db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT node_type FROM nodes WHERE id LIKE 'endpoint:%'")
        rows = cursor.fetchall()
        conn.close()

        self.assertTrue(len(rows) >= 1, "Expected endpoint nodes in DB")
        for row in rows:
            self.assertEqual(row[0], "external_endpoint")

    def test_config_file_node_type_detected(self):
        """config: prefix → node_type = 'config_file'."""
        edges = _extract_from_settings(self.cs_prod, self.repo)
        db_path = str(self.memory_dir / "test_graph.sqlite")
        save_to_graph_db(edges, db_path)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT node_type FROM nodes WHERE id LIKE 'config:%'")
        rows = cursor.fetchall()
        conn.close()

        self.assertTrue(len(rows) >= 1, "Expected config_file nodes in DB")
        for row in rows:
            self.assertEqual(row[0], "config_file")

    # --- Edge cases ---

    def test_empty_yaml_returns_empty(self):
        """Empty file → no edges."""
        empty_file = self.test_dir / "empty.yaml"
        empty_file.write_text("", encoding="utf-8")
        edges = _extract_from_settings(empty_file, self.test_dir)
        self.assertEqual(edges, [])

    def test_malformed_yaml_returns_empty(self):
        """Invalid YAML → graceful failure, no crash."""
        bad_file = self.test_dir / "bad.yaml"
        bad_file.write_text("{{invalid: yaml: [unclosed", encoding="utf-8")
        edges = _extract_from_settings(bad_file, self.test_dir)
        self.assertEqual(edges, [])

    # --- Full repo extraction ---

    def test_full_repo_extraction(self):
        """extract_relationships(fake_settings_repo) returns edges from all services."""
        edges = extract_relationships(str(self.repo))
        # Should have edges from multiple service directories
        repos_in_edges = {e.get("repo", "") for e in edges}
        edge_types = {e["edge_type"] for e in edges}

        self.assertIn(CONNECTS_TO, edge_types, "Expected CONNECTS_TO edges from full repo scan")
        self.assertTrue(len(edges) >= 5, f"Expected at least 5 edges from full repo, got {len(edges)}")

        # Should find endpoints from both client-service and audit-service
        all_targets = [e["target"] for e in edges]
        has_servicebus = any("servicebus.windows.net" in t for t in all_targets)
        self.assertTrue(has_servicebus, "Expected servicebus endpoints in full repo extraction")


class TestClassifySettingsFile(HiveMindTestCase):
    """Tests for classify_file() with settings files."""

    def test_settings_file_classified_as_config(self):
        """client-service-prod.yaml in client-service/ dir → 'config'."""
        result = classify_file(
            "client-service/client-service-prod.yaml",
        )
        self.assertEqual(result, "config")

    def test_base_settings_file_classified_as_config(self):
        """client-service.yaml in client-service/ dir → 'config'."""
        result = classify_file(
            "client-service/client-service.yaml",
        )
        self.assertEqual(result, "config")

    def test_application_yaml_classified_as_config(self):
        """application.yaml at repo root → 'config'."""
        result = classify_file("application.yaml")
        self.assertEqual(result, "config")

    def test_application_prod_yaml_classified_as_config(self):
        """application-prod.yaml → 'config'."""
        result = classify_file("application-prod.yaml")
        self.assertEqual(result, "config")

    def test_non_settings_yaml_not_config(self):
        """Chart.yaml → NOT 'config' (should be helm_chart)."""
        result = classify_file("charts/myservice/Chart.yaml")
        self.assertNotEqual(result, "config")
        self.assertEqual(result, "helm_chart")

    def test_pipeline_yaml_not_config(self):
        """pipeline.yaml → NOT 'config' (should be pipeline)."""
        result = classify_file("pipelines/pipeline.yaml")
        self.assertNotEqual(result, "config")
        self.assertEqual(result, "pipeline")

    def test_values_yaml_not_config(self):
        """values.yaml should still be helm_values, not config."""
        result = classify_file("charts/myservice/values.yaml")
        self.assertNotEqual(result, "config")


if __name__ == "__main__":
    unittest.main()
