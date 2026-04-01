"""
Unit Tests — FlashRank Cross-Encoder Reranker

Tests the _rerank_with_flashrank() helper and its integration
with query_memory() as a second stage after RRF fusion.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.query_memory import (
    _get_flashrank_ranker,
    _rerank_with_flashrank,
)


def _make_result(file_path, repo="test-repo", branch="main", chunk_index=0,
                 file_type="pipeline", text="sample text", rrf_score=0.016):
    """Helper to build a result dict matching RRF fusion output format."""
    return {
        "text": text,
        "file_path": file_path,
        "repo": repo,
        "branch": branch,
        "relevance": 0.9,
        "relevance_pct": 90.0,
        "chunk_index": chunk_index,
        "file_type": file_type,
        "rrf_score": rrf_score,
        "retrieval_method": "hybrid_rrf",
        "source_citation": f"[Source: {file_path} | repo: {repo} | branch: {branch} | relevance: 90.0%]",
    }


class TestRerankReturnsTopN(unittest.TestCase):
    """test_rerank_returns_top_n: exactly top_n results returned."""

    def test_rerank_returns_top_n(self):
        results = [_make_result(f"file{i}.yaml") for i in range(10)]
        reranked = _rerank_with_flashrank("deploy audit", results, top_n=5)
        self.assertEqual(len(reranked), 5)


class TestRerankAddsFlashRankScore(unittest.TestCase):
    """test_rerank_adds_flashrank_score: all results have flashrank_score as float."""

    def test_rerank_adds_flashrank_score(self):
        results = [_make_result(f"file{i}.yaml", text=f"deploy audit service {i}")
                    for i in range(5)]
        reranked = _rerank_with_flashrank("deploy audit", results, top_n=5)
        for r in reranked:
            self.assertIn("flashrank_score", r)
            self.assertIsInstance(r["flashrank_score"], float)


class TestRerankSetsRetrievalMethod(unittest.TestCase):
    """test_rerank_sets_retrieval_method: method = hybrid_rrf_reranked."""

    def test_rerank_sets_retrieval_method(self):
        results = [_make_result(f"file{i}.yaml", text=f"terraform module {i}")
                    for i in range(3)]
        reranked = _rerank_with_flashrank("terraform module", results, top_n=3)
        for r in reranked:
            self.assertEqual(r["retrieval_method"], "hybrid_rrf_reranked")


class TestRerankEmptyInput(unittest.TestCase):
    """test_rerank_empty_input: returns empty list, no crash."""

    def test_rerank_empty_input(self):
        reranked = _rerank_with_flashrank("any query", [], top_n=5)
        self.assertEqual(reranked, [])


class TestRerankFlashRankUnavailable(unittest.TestCase):
    """test_rerank_flashrank_unavailable: falls back to original order."""

    def test_rerank_flashrank_unavailable(self):
        import tools.query_memory as qm

        results = [_make_result(f"file{i}.yaml") for i in range(5)]
        original_paths = [r["file_path"] for r in results]

        with patch.object(qm, '_get_flashrank_ranker', return_value=None):
            reranked = qm._rerank_with_flashrank("query", results, top_n=3)

        self.assertEqual(len(reranked), 3)
        # Should preserve original order (top 3 of original)
        reranked_paths = [r["file_path"] for r in reranked]
        self.assertEqual(reranked_paths, original_paths[:3])
        for r in reranked:
            self.assertEqual(r["retrieval_method"], "hybrid_rrf_no_rerank")


class TestRerankPreservesMetadata(unittest.TestCase):
    """test_rerank_preserves_metadata: source_file, repo, branch, rrf_score survive."""

    def test_rerank_preserves_metadata(self):
        results = [
            _make_result(
                "charts/svc/values.yaml",
                repo="my-repo",
                branch="release_26_3",
                file_type="helm",
                text="helm chart values for service deployment",
                rrf_score=0.03279,
            ),
        ]
        reranked = _rerank_with_flashrank("helm chart values", results, top_n=1)
        self.assertEqual(len(reranked), 1)
        r = reranked[0]
        self.assertEqual(r["file_path"], "charts/svc/values.yaml")
        self.assertEqual(r["repo"], "my-repo")
        self.assertEqual(r["branch"], "release_26_3")
        self.assertEqual(r["file_type"], "helm")
        self.assertIn("rrf_score", r)
        self.assertIn("source_citation", r)


class TestRerankTextCappedAt2000Chars(unittest.TestCase):
    """test_rerank_text_capped_at_2000_chars: large text truncated for FlashRank."""

    def test_rerank_text_capped_at_2000_chars(self):
        long_text = "x" * 5000
        results = [_make_result("big.yaml", text=long_text)]

        # Patch the Ranker to capture what passages it receives
        captured_passages = []

        class MockRanker:
            def rerank(self, request):
                captured_passages.extend(request.passages)
                return [{"id": 0, "score": 0.95, "meta": results[0]}]

        import tools.query_memory as qm
        with patch.object(qm, '_get_flashrank_ranker', return_value=MockRanker()):
            qm._rerank_with_flashrank("query", results, top_n=1)

        self.assertEqual(len(captured_passages), 1)
        self.assertLessEqual(len(captured_passages[0]["text"]), 2000)


class TestQueryMemoryUsesReranker(unittest.TestCase):
    """test_query_memory_uses_reranker: end-to-end with mocked FlashRank."""

    def test_query_memory_uses_reranker(self):
        import tools.query_memory as qm

        client_name = "testclient_flashrank"
        mem_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name / "vectors"
        mem_dir.mkdir(parents=True, exist_ok=True)

        chunks = [
            {
                "id": "c1",
                "text": "deploy audit service to dev environment pipeline",
                "metadata": {
                    "file_path": "pipelines/deploy_audit.yaml",
                    "repo": "test-repo",
                    "file_type": "pipeline",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
            {
                "id": "c2",
                "text": "terraform keyvault secrets for database",
                "metadata": {
                    "file_path": "layer_01/main.tf",
                    "repo": "test-repo",
                    "file_type": "terraform",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
            {
                "id": "c3",
                "text": "audit service helm chart values deploy",
                "metadata": {
                    "file_path": "charts/audit-service/values.yaml",
                    "repo": "test-repo",
                    "file_type": "helm",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
        ]

        chunks_file = mem_dir / "test-repo.json"
        try:
            with open(chunks_file, "w") as f:
                json.dump(chunks, f)

            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()

            try:
                import chromadb
                has_chromadb = True
            except ImportError:
                has_chromadb = False

            if has_chromadb:
                mock_client_db = MagicMock()
                mock_client_db.list_collections.return_value = []
                with patch.object(chromadb, "PersistentClient",
                                  return_value=mock_client_db):
                    results = qm.query_memory(client_name, "deploy audit service")
            else:
                results = qm.query_memory(client_name, "deploy audit service")

            self.assertGreater(len(results), 0)
            for r in results:
                self.assertIn("flashrank_score", r)
                self.assertIsInstance(r["flashrank_score"], float)
                self.assertEqual(r["retrieval_method"], "hybrid_rrf_reranked")
        finally:
            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()
            cleanup_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)


class TestQueryMemoryFlashRankFailureFallback(unittest.TestCase):
    """test_query_memory_flashrank_failure_fallback: FlashRank error → no crash."""

    def test_query_memory_flashrank_failure_fallback(self):
        import tools.query_memory as qm

        client_name = "testclient_flashrank_fail"
        mem_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name / "vectors"
        mem_dir.mkdir(parents=True, exist_ok=True)

        chunks = [
            {
                "id": "c1",
                "text": "deploy audit service to dev environment",
                "metadata": {
                    "file_path": "pipelines/deploy_audit.yaml",
                    "repo": "test-repo",
                    "file_type": "pipeline",
                    "branch": "main",
                    "chunk_index": 0,
                },
            },
        ]

        chunks_file = mem_dir / "test-repo.json"
        try:
            with open(chunks_file, "w") as f:
                json.dump(chunks, f)

            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()

            # Mock FlashRank ranker to raise exception on rerank
            mock_ranker = MagicMock()
            mock_ranker.rerank.side_effect = RuntimeError("FlashRank crash")

            try:
                import chromadb
                has_chromadb = True
            except ImportError:
                has_chromadb = False

            if has_chromadb:
                mock_client_db = MagicMock()
                mock_client_db.list_collections.return_value = []
                with patch.object(chromadb, "PersistentClient",
                                  return_value=mock_client_db):
                    with patch.object(qm, '_get_flashrank_ranker',
                                      return_value=mock_ranker):
                        results = qm.query_memory(client_name, "deploy audit")
            else:
                with patch.object(qm, '_get_flashrank_ranker',
                                  return_value=mock_ranker):
                    results = qm.query_memory(client_name, "deploy audit")

            # Should NOT crash — returns RRF fallback results
            self.assertGreater(len(results), 0)
            for r in results:
                self.assertEqual(r["retrieval_method"], "hybrid_rrf_no_rerank")
        finally:
            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()
            cleanup_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)


class TestLazyLoaderSingleton(unittest.TestCase):
    """test_lazy_loader_singleton: same object returned on multiple calls."""

    def test_lazy_loader_singleton(self):
        import tools.query_memory as qm

        # Reset the singleton
        qm._flashrank_ranker = None

        ranker1 = _get_flashrank_ranker()
        ranker2 = _get_flashrank_ranker()

        if ranker1 is not None:
            # FlashRank installed — verify same object
            self.assertIs(ranker1, ranker2)
        else:
            # FlashRank not installed — both should be None
            self.assertIsNone(ranker2)

        # Clean up
        qm._flashrank_ranker = None


if __name__ == "__main__":
    unittest.main()
