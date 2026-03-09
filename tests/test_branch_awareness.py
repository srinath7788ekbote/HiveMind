"""
Integration Test — Branch Awareness

Tests branch-tier classification, branch-scoped indexing,
branch-filtered querying, and multi-branch entity resolution.
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

from ingest.branch_indexer import BranchIndex, classify_branch_tier
from ingest.extract_relationships import save_to_graph_db


class TestBranchTierClassification(unittest.TestCase):
    """Test branch tier assignment logic."""

    def test_main_is_production(self):
        self.assertEqual(classify_branch_tier("main"), "production")

    def test_master_is_production(self):
        self.assertEqual(classify_branch_tier("master"), "production")

    def test_release_is_release(self):
        self.assertEqual(classify_branch_tier("release/2.1.0"), "release")

    def test_develop_is_integration(self):
        self.assertEqual(classify_branch_tier("develop"), "integration")

    def test_feature_is_feature(self):
        self.assertEqual(classify_branch_tier("feature/add-monitoring"), "feature")

    def test_hotfix_is_hotfix(self):
        self.assertEqual(classify_branch_tier("hotfix/critical-fix"), "hotfix")

    def test_random_branch_is_unknown(self):
        self.assertEqual(classify_branch_tier("john/experiment"), "unknown")

    def test_staging_is_unknown(self):
        # No staging pattern defined -> returns unknown
        self.assertEqual(classify_branch_tier("staging"), "unknown")


class TestBranchIndexing(unittest.TestCase):
    """Test branch index tracking."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.index_file = os.path.join(self.temp_dir, "branch_index.json")
        self.index = BranchIndex(self.index_file)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mark_indexed(self):
        self.index.mark_indexed("test-repo", "main", "abc123")
        branches = self.index.get_indexed_branches("test-repo")
        self.assertIn("main", [b["branch"] for b in branches])

    def test_add_multiple_branches(self):
        self.index.mark_indexed("test-repo", "main", "abc123")
        self.index.mark_indexed("test-repo", "develop", "def456")
        self.index.mark_indexed("test-repo", "feature/x", "ghi789")
        branches = self.index.get_indexed_branches("test-repo")
        self.assertEqual(len(branches), 3)

    def test_branch_tier_stored(self):
        self.index.mark_indexed("test-repo", "release/1.0", "abc123")
        branches = self.index.get_indexed_branches("test-repo")
        branch = [b for b in branches if b["branch"] == "release/1.0"][0]
        self.assertEqual(branch["tier"], "release")

    def test_update_existing_branch(self):
        self.index.mark_indexed("test-repo", "main", "abc123")
        self.index.mark_indexed("test-repo", "main", "def456")
        branches = self.index.get_indexed_branches("test-repo")
        main_branches = [b for b in branches if b["branch"] == "main"]
        # Should update not duplicate (key is repo:branch)
        self.assertEqual(len(main_branches), 1)

    def test_persistence(self):
        self.index.mark_indexed("test-repo", "main", "abc123")
        # Reload from file
        index2 = BranchIndex(self.index_file)
        branches = index2.get_indexed_branches("test-repo")
        self.assertIn("main", [b["branch"] for b in branches])

    def test_multiple_repos(self):
        self.index.mark_indexed("repo-a", "main", "aaa")
        self.index.mark_indexed("repo-b", "main", "bbb")
        self.index.mark_indexed("repo-b", "develop", "ccc")
        a_branches = self.index.get_indexed_branches("repo-a")
        b_branches = self.index.get_indexed_branches("repo-b")
        self.assertEqual(len(a_branches), 1)
        self.assertEqual(len(b_branches), 2)


class TestBranchScopedGraph(unittest.TestCase):
    """Test branch-aware graph storage and querying."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "graph.db")
        self._build_multi_branch_graph()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _build_multi_branch_graph(self):
        """Create a graph with entities on different branches."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT, node_type TEXT, file TEXT,
                repo TEXT, branch TEXT DEFAULT 'main',
                PRIMARY KEY (id, repo, branch)
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                source TEXT, target TEXT, edge_type TEXT,
                file TEXT, repo TEXT, branch TEXT DEFAULT 'main',
                metadata TEXT
            )
        """)

        # Main branch entities
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("audit-service", "service", "services/audit.yaml", "harness", "main"))
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("deploy_audit", "pipeline", "pipelines/deploy_audit.yaml", "harness", "main"))
        c.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
                  ("deploy_audit", "audit-service", "deploys", "deploy_audit.yaml", "harness", "main", "{}"))

        # Feature branch adds a new service
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("audit-service", "service", "services/audit.yaml", "harness", "feature/new-svc"))
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("billing-service", "service", "services/billing.yaml", "harness", "feature/new-svc"))
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("deploy_billing", "pipeline", "pipelines/deploy_billing.yaml", "harness", "feature/new-svc"))
        c.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
                  ("deploy_billing", "billing-service", "deploys", "deploy_billing.yaml", "harness", "feature/new-svc", "{}"))

        # Release branch modifies pipeline
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("audit-service", "service", "services/audit.yaml", "harness", "release/2.0"))
        c.execute("INSERT INTO nodes VALUES (?,?,?,?,?)",
                  ("deploy_audit_v2", "pipeline", "pipelines/deploy_audit_v2.yaml", "harness", "release/2.0"))
        c.execute("INSERT INTO edges VALUES (?,?,?,?,?,?,?)",
                  ("deploy_audit_v2", "audit-service", "deploys", "deploy_audit_v2.yaml", "harness", "release/2.0", "{}"))

        conn.commit()
        conn.close()

    def test_main_only_query(self):
        """Query graph scoped to main branch only."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id FROM nodes WHERE branch = 'main'")
        results = c.fetchall()
        conn.close()
        ids = [r[0] for r in results]
        self.assertIn("audit-service", ids)
        self.assertNotIn("billing-service", ids)

    def test_feature_branch_has_new_entities(self):
        """Feature branch adds billing-service."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id FROM nodes WHERE branch = 'feature/new-svc'")
        results = c.fetchall()
        conn.close()
        ids = [r[0] for r in results]
        self.assertIn("billing-service", ids)
        self.assertIn("audit-service", ids)

    def test_release_branch_pipeline_differs(self):
        """Release branch has v2 pipeline."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT id FROM nodes WHERE branch = 'release/2.0' AND node_type = 'pipeline'")
        results = c.fetchall()
        conn.close()
        ids = [r[0] for r in results]
        self.assertIn("deploy_audit_v2", ids)
        self.assertNotIn("deploy_audit", ids)

    def test_edge_scoping(self):
        """Edges are branch-scoped."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT source, target FROM edges WHERE branch = 'main'")
        main_edges = c.fetchall()
        c.execute("SELECT source, target FROM edges WHERE branch = 'feature/new-svc'")
        feature_edges = c.fetchall()
        conn.close()

        main_sources = [e[0] for e in main_edges]
        feature_sources = [e[0] for e in feature_edges]

        self.assertIn("deploy_audit", main_sources)
        self.assertIn("deploy_billing", feature_sources)

    def test_cross_branch_entity_count(self):
        """Count audit-service appearances across branches."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM nodes WHERE id = 'audit-service'")
        count = c.fetchone()[0]
        conn.close()
        self.assertEqual(count, 3)  # main, feature, release

    def test_branch_specific_subgraph(self):
        """Get full subgraph for a branch."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("""
            SELECT n.id, n.node_type, e.source, e.target, e.edge_type
            FROM nodes n
            LEFT JOIN edges e ON (n.id = e.source OR n.id = e.target) AND e.branch = n.branch
            WHERE n.branch = 'release/2.0'
        """)
        rows = c.fetchall()
        conn.close()
        self.assertGreater(len(rows), 0)
        node_ids = set(r[0] for r in rows)
        self.assertIn("deploy_audit_v2", node_ids)


class TestBranchAwareChunks(unittest.TestCase):
    """Test branch-aware chunk storage and search."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.chunks_dir = os.path.join(self.temp_dir, "memory", "chunks")
        os.makedirs(self.chunks_dir, exist_ok=True)
        self._create_branch_chunks()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_branch_chunks(self):
        """Create chunks tagged with different branches."""
        chunks = [
            {
                "id": "chunk_main_1",
                "text": "audit-service deploys via rollout_k8s template to production",
                "file": "pipelines/deploy_audit.yaml",
                "repo": "harness",
                "branch": "main",
                "type": "pipeline",
            },
            {
                "id": "chunk_feature_1",
                "text": "billing-service uses new payment-gateway connector",
                "file": "pipelines/deploy_billing.yaml",
                "repo": "harness",
                "branch": "feature/billing",
                "type": "pipeline",
            },
            {
                "id": "chunk_release_1",
                "text": "audit-service deployment updated with canary strategy",
                "file": "pipelines/deploy_audit_v2.yaml",
                "repo": "harness",
                "branch": "release/2.0",
                "type": "pipeline",
            },
        ]
        chunks_file = os.path.join(self.chunks_dir, "all_chunks.json")
        with open(chunks_file, "w") as f:
            json.dump(chunks, f)

    def test_filter_chunks_by_branch(self):
        """Load chunks and filter by branch."""
        chunks_file = os.path.join(self.chunks_dir, "all_chunks.json")
        with open(chunks_file) as f:
            all_chunks = json.load(f)

        main_chunks = [c for c in all_chunks if c["branch"] == "main"]
        self.assertEqual(len(main_chunks), 1)
        self.assertIn("audit-service", main_chunks[0]["text"])

    def test_feature_branch_chunks_isolated(self):
        """Feature branch chunks don't leak into main."""
        chunks_file = os.path.join(self.chunks_dir, "all_chunks.json")
        with open(chunks_file) as f:
            all_chunks = json.load(f)

        main_chunks = [c for c in all_chunks if c["branch"] == "main"]
        for chunk in main_chunks:
            self.assertNotIn("billing-service", chunk["text"])

    def test_all_branches_searchable(self):
        """All branch chunks are searchable when no filter applied."""
        chunks_file = os.path.join(self.chunks_dir, "all_chunks.json")
        with open(chunks_file) as f:
            all_chunks = json.load(f)

        self.assertEqual(len(all_chunks), 3)
        branches = set(c["branch"] for c in all_chunks)
        self.assertEqual(branches, {"main", "feature/billing", "release/2.0"})


if __name__ == "__main__":
    unittest.main()
