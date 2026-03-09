"""
Test Configuration — Shared fixtures and helpers for all tests

Provides:
    - Temporary directory management
    - Fake repository creation
    - Common assertions
    - Test data paths

Uses only unittest (no pytest).
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Paths to test fixtures
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
FAKE_HARNESS_REPO = FIXTURES_DIR / "fake_harness_repo"
FAKE_TERRAFORM_REPO = FIXTURES_DIR / "fake_terraform_repo"
FAKE_HELM_REPO = FIXTURES_DIR / "fake_helm_repo"


class HiveMindTestCase(unittest.TestCase):
    """Base test case with common setup and teardown."""

    def setUp(self):
        """Create a temp directory for test outputs."""
        self.test_dir = Path(tempfile.mkdtemp(prefix="hivemind_test_"))
        self.memory_dir = self.test_dir / "memory" / "testclient"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        """Clean up temp directory."""
        if self.test_dir.exists():
            shutil.rmtree(str(self.test_dir), ignore_errors=True)

    def create_test_graph_db(self, nodes=None, edges=None):
        """
        Create a test graph SQLite database.

        Args:
            nodes: list of (id, node_type, file, repo) tuples
            edges: list of (source, target, edge_type, file, repo, branch) tuples

        Returns:
            Path to the created database.
        """
        db_path = self.memory_dir / "graph.sqlite"
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                node_type TEXT,
                file TEXT,
                repo TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT,
                target TEXT,
                edge_type TEXT,
                file TEXT,
                repo TEXT,
                branch TEXT,
                metadata TEXT
            )
        """)

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)")

        if nodes:
            cursor.executemany(
                "INSERT INTO nodes (id, node_type, file, repo) VALUES (?, ?, ?, ?)",
                nodes,
            )

        if edges:
            for edge in edges:
                # Pad to 7 elements (source, target, edge_type, file, repo, branch, metadata)
                padded = list(edge) + [""] * (7 - len(edge))
                cursor.execute(
                    "INSERT INTO edges (source, target, edge_type, file, repo, branch, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    padded[:7],
                )

        conn.commit()
        conn.close()
        return db_path

    def create_test_entities(self, entities_dict=None):
        """
        Create a test entities.json file.

        Args:
            entities_dict: dict to write. If None, uses defaults.

        Returns:
            Path to the created file.
        """
        if entities_dict is None:
            entities_dict = {
                "files": [
                    {"path": "pipelines/deploy_audit.yaml", "type": "pipeline", "repo": "dfin-harness-pipelines", "branch": "main"},
                    {"path": "layer_01_keyvaults/main.tf", "type": "terraform", "repo": "Eastwood-terraform", "branch": "main"},
                    {"path": "charts/audit-service/values.yaml", "type": "helm_values", "repo": "Eastwood-helm", "branch": "main"},
                ],
                "secrets": [
                    {"name": "automation-dev-dbauditservice", "service": "audit-service"},
                    {"name": "automation-dev-dbpaymentservice", "service": "payment-service"},
                ],
            }

        entities_path = self.memory_dir / "entities.json"
        with open(entities_path, "w", encoding="utf-8") as f:
            json.dump(entities_dict, f, indent=2)

        return entities_path

    def create_test_chunks(self, chunks=None):
        """
        Create a test chunks JSON file (vector store fallback).

        Returns:
            Path to the created file.
        """
        if chunks is None:
            chunks = [
                {
                    "id": "chunk_001",
                    "text": "pipeline deploy audit service to dev environment using rollout_k8s template",
                    "metadata": {
                        "file": "pipelines/deploy_audit.yaml",
                        "repo": "dfin-harness-pipelines",
                        "type": "pipeline",
                        "branch": "main",
                    },
                },
                {
                    "id": "chunk_002",
                    "text": "resource azurerm_key_vault_secret automation-dev-dbauditservice value from var",
                    "metadata": {
                        "file": "layer_01_keyvaults/main.tf",
                        "repo": "Eastwood-terraform",
                        "type": "terraform",
                        "branch": "main",
                    },
                },
                {
                    "id": "chunk_003",
                    "text": "secretKeyRef name automation-dev-dbauditservice container audit-service",
                    "metadata": {
                        "file": "charts/audit-service/templates/deployment.yaml",
                        "repo": "Eastwood-helm",
                        "type": "helm_template",
                        "branch": "main",
                    },
                },
            ]

        chunks_path = self.memory_dir / "chunks.json"
        with open(chunks_path, "w", encoding="utf-8") as f:
            json.dump(chunks, f, indent=2)

        return chunks_path

    def assertFileExists(self, path):
        """Assert that a file exists."""
        self.assertTrue(Path(path).exists(), f"File does not exist: {path}")

    def assertContainsAll(self, collection, items):
        """Assert that all items are in the collection."""
        for item in items:
            self.assertIn(item, collection, f"Missing item: {item}")
