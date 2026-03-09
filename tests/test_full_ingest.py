"""
Integration Test — Full Ingest Pipeline

End-to-end test: crawl fake repos -> classify -> extract -> embed -> profile
Validates the entire ingest pipeline works correctly.
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase, FAKE_HARNESS_REPO, FAKE_TERRAFORM_REPO, FAKE_HELM_REPO


class TestFullIngestPipeline(HiveMindTestCase):
    """Integration test: complete ingest pipeline from repos to memory."""

    def setUp(self):
        super().setUp()
        self.client_dir = self.test_dir / "clients" / "testclient"
        self.client_dir.mkdir(parents=True, exist_ok=True)

    def test_classify_all_repos(self):
        """Test classifying files across all fake repos."""
        from ingest.classify_files import classify_directory

        # Harness repo — results use "classification" key
        harness_results = classify_directory(str(FAKE_HARNESS_REPO))
        self.assertGreater(len(harness_results), 0)
        classifications = set(r["classification"] for r in harness_results)
        # Should find templates and harness services
        self.assertIn("template", classifications)
        self.assertIn("harness_svc", classifications)

        # Terraform repo
        tf_results = classify_directory(str(FAKE_TERRAFORM_REPO))
        self.assertGreater(len(tf_results), 0)
        classifications = set(r["classification"] for r in tf_results)
        self.assertIn("terraform", classifications)

        # Helm repo
        helm_results = classify_directory(str(FAKE_HELM_REPO))
        self.assertGreater(len(helm_results), 0)
        classifications = set(r["classification"] for r in helm_results)
        self.assertIn("helm_chart", classifications)

    def test_extract_relationships_all_repos(self):
        """Test extracting edges from all fake repos."""
        from ingest.extract_relationships import extract_relationships, save_to_graph_db

        all_edges = []

        edges = extract_relationships(str(FAKE_HARNESS_REPO))
        all_edges.extend(edges)

        edges = extract_relationships(str(FAKE_TERRAFORM_REPO))
        all_edges.extend(edges)

        edges = extract_relationships(str(FAKE_HELM_REPO))
        all_edges.extend(edges)

        self.assertGreater(len(all_edges), 0)

        # Save to graph DB
        db_path = self.memory_dir / "graph.sqlite"
        save_to_graph_db(all_edges, str(db_path))
        self.assertTrue(db_path.exists())

        # Verify data in DB
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM edges")
        edge_count = cursor.fetchone()[0]
        conn.close()
        self.assertGreater(edge_count, 0)

    def test_embed_chunks_all_repos(self):
        """Test embedding chunks from all fake repos."""
        from ingest.embed_chunks import embed_repo

        for repo_name, repo_path in [
            ("fake-harness", FAKE_HARNESS_REPO),
            ("fake-terraform", FAKE_TERRAFORM_REPO),
            ("fake-helm", FAKE_HELM_REPO),
        ]:
            # embed_repo(repo_path, memory_dir, branch=, collection_name=)
            result = embed_repo(
                repo_path=str(repo_path),
                memory_dir=str(self.memory_dir),
                branch="main",
                collection_name=repo_name,
            )
            self.assertIn("chunk_count", result)
            self.assertIn("file_count", result)

    def test_discovery_pipeline(self):
        """Test running all discovery modules."""
        from ingest.discovery.build_profile import build_profile

        # build_profile takes 3 args: client_name, repo_configs, output_dir
        repo_configs = [
            {"name": "fake-harness", "path": str(FAKE_HARNESS_REPO), "branches": ["main"]},
            {"name": "fake-terraform", "path": str(FAKE_TERRAFORM_REPO), "branches": ["main"]},
            {"name": "fake-helm", "path": str(FAKE_HELM_REPO), "branches": ["main"]},
        ]
        profile = build_profile("testclient", repo_configs, str(self.test_dir))
        self.assertIn("client", profile)
        self.assertIn("services", profile)
        self.assertIn("environments", profile)
        self.assertEqual(profile["client"], "testclient")

    def test_end_to_end_flow(self):
        """Test the complete flow: classify -> extract -> embed -> verify."""
        from ingest.classify_files import classify_directory
        from ingest.extract_relationships import extract_relationships, save_to_graph_db
        from ingest.embed_chunks import embed_repo

        # Step 1: Classify — results use "classification" key
        all_classified = []
        for repo_name, repo_path, repo_type in [
            ("fake-harness", FAKE_HARNESS_REPO, "cicd/harness"),
            ("fake-terraform", FAKE_TERRAFORM_REPO, "infrastructure/terraform"),
            ("fake-helm", FAKE_HELM_REPO, "helm"),
        ]:
            results = classify_directory(str(repo_path))
            for r in results:
                r["repo"] = repo_name
            all_classified.extend(results)

        self.assertGreater(len(all_classified), 0)

        # Step 2: Extract relationships using extract_relationships()
        all_edges = []
        for repo_name, repo_path in [
            ("fake-harness", FAKE_HARNESS_REPO),
            ("fake-terraform", FAKE_TERRAFORM_REPO),
            ("fake-helm", FAKE_HELM_REPO),
        ]:
            edges = extract_relationships(str(repo_path))
            all_edges.extend(edges)

        # Step 3: Save to graph
        db_path = self.memory_dir / "graph.sqlite"
        save_to_graph_db(all_edges, str(db_path))

        # Step 4: Embed — embed_repo(repo_path, memory_dir, branch=, collection_name=)
        for repo_name, repo_path in [
            ("fake-harness", FAKE_HARNESS_REPO),
            ("fake-terraform", FAKE_TERRAFORM_REPO),
            ("fake-helm", FAKE_HELM_REPO),
        ]:
            embed_repo(str(repo_path), str(self.memory_dir), "main", repo_name)

        # Step 5: Save entities
        entities = {
            "files": all_classified,
            "secrets": [],
        }
        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w") as f:
            json.dump(entities, f, indent=2)

        # Verify all outputs exist
        self.assertTrue(db_path.exists(), "graph.sqlite should exist")
        self.assertTrue(entities_path.exists(), "entities.json should exist")

        # Verify graph has service references
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM edges WHERE edge_type = 'USES_SERVICE'")
        svc_count = cursor.fetchone()[0]
        conn.close()
        self.assertGreater(svc_count, 0, "Should have USES_SERVICE edges")


class TestCrossRepoRelationships(HiveMindTestCase):
    """Test that relationships span across repos correctly."""

    def test_secret_flows_across_repos(self):
        """Verify secret lifecycle spans terraform -> k8s -> helm."""
        from ingest.extract_relationships import extract_relationships, save_to_graph_db

        all_edges = []
        for repo_path in [FAKE_TERRAFORM_REPO, FAKE_HELM_REPO]:
            edges = extract_relationships(str(repo_path))
            all_edges.extend(edges)

        # Should have creation (terraform) and mount (helm) edges
        edge_types = set(e["edge_type"] for e in all_edges)
        self.assertIn("CREATES_KV_SECRET", edge_types)
        self.assertIn("MOUNTS_SECRET", edge_types)


if __name__ == "__main__":
    unittest.main()
