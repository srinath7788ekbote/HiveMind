"""
Unit Tests — Query Memory (semantic search)

Tests tools/query_memory.py
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.conftest import HiveMindTestCase


class TestSimpleRelevance(unittest.TestCase):
    """Tests for the _simple_relevance() scoring function."""

    def test_positive_match(self):
        from tools.query_memory import _simple_relevance
        score = _simple_relevance("audit service", "pipeline deploy audit service to dev")
        self.assertGreater(score, 0)

    def test_no_overlap_scores_zero(self):
        from tools.query_memory import _simple_relevance
        score = _simple_relevance("xyz123", "pipeline deploy audit service")
        self.assertEqual(score, 0.0)

    def test_case_insensitive(self):
        from tools.query_memory import _simple_relevance
        score1 = _simple_relevance("AUDIT", "audit service deployment")
        score2 = _simple_relevance("audit", "audit service deployment")
        self.assertEqual(score1, score2)

    def test_exact_phrase_boost(self):
        from tools.query_memory import _simple_relevance
        # Exact phrase match gets a boost
        score_exact = _simple_relevance("audit service", "audit service deployment yaml")
        score_partial = _simple_relevance("audit gateway", "audit service deployment yaml")
        self.assertGreater(score_exact, score_partial)

    def test_full_overlap_is_high(self):
        from tools.query_memory import _simple_relevance
        score = _simple_relevance("deploy audit", "deploy audit service")
        # Both query words are in text -> score should be 1.0 (+ possible boost)
        self.assertGreaterEqual(score, 0.9)

    def test_partial_overlap(self):
        from tools.query_memory import _simple_relevance
        score = _simple_relevance("deploy payment", "deploy audit service")
        # Only "deploy" overlaps -> 0.5
        self.assertGreater(score, 0)
        self.assertLess(score, 1.0)

    def test_relevance_between_zero_and_one(self):
        from tools.query_memory import _simple_relevance
        score = _simple_relevance("terraform keyvault", "resource azurerm_key_vault main")
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)


class TestQueryMemory(HiveMindTestCase):
    """Tests for query_memory() function — requires proper memory directory setup."""

    def _setup_vector_chunks(self, chunks):
        """Write chunks to the JSON vector store."""
        vectors_dir = self.memory_dir / "vectors"
        vectors_dir.mkdir(parents=True, exist_ok=True)
        chunks_file = vectors_dir / "test-repo.json"
        with open(chunks_file, "w") as f:
            json.dump(chunks, f)

    def test_query_memory_returns_results(self):
        """Test that query_memory returns results from JSON fallback."""
        import tools.query_memory as qm

        chunks = [
            {
                "id": "c1",
                "text": "pipeline deploy audit service to dev environment",
                "metadata": {
                    "file_path": "pipelines/deploy_audit.yaml",
                    "repo": "test",
                    "file_type": "pipeline",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
            {
                "id": "c2",
                "text": "terraform azurerm_key_vault with secrets for database",
                "metadata": {
                    "file_path": "layer_01/main.tf",
                    "repo": "test",
                    "file_type": "terraform",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
        ]

        # Write chunks to the correct path: memory/<client>/vectors/<name>.json
        # query_memory uses PROJECT_ROOT / "memory" / client
        # For testing, patch the path
        client_name = "testclient"
        mem_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name / "vectors"
        mem_dir.mkdir(parents=True, exist_ok=True)
        chunks_file = mem_dir / "test-repo.json"
        try:
            with open(chunks_file, "w") as f:
                json.dump(chunks, f)

            results = qm.query_memory(client_name, "audit service")
            self.assertGreater(len(results), 0)
        finally:
            # Cleanup
            import shutil
            cleanup_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)

    def test_simple_relevance_scoring(self):
        """Test the word-overlap relevance function directly."""
        from tools.query_memory import _simple_relevance

        # Exact match should score high
        score = _simple_relevance("deploy audit", "pipeline deploy audit service")
        self.assertGreater(score, 0)

        # No overlap should score zero
        score_zero = _simple_relevance("xyz123", "pipeline deploy audit service")
        self.assertEqual(score_zero, 0.0)


if __name__ == "__main__":
    unittest.main()
