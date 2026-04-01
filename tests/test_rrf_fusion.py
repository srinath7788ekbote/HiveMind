"""
Unit Tests — Reciprocal Rank Fusion (RRF)

Tests the _reciprocal_rank_fusion() helper and its integration
with query_memory().
"""

import json
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.query_memory import _reciprocal_rank_fusion


def _make_result(file_path, repo="test-repo", branch="main", chunk_index=0,
                 file_type="pipeline", text="sample text"):
    """Helper to build a result dict matching query_memory output format."""
    return {
        "text": text,
        "file_path": file_path,
        "repo": repo,
        "branch": branch,
        "relevance": 0.9,
        "relevance_pct": 90.0,
        "chunk_index": chunk_index,
        "file_type": file_type,
        "source_citation": f"[Source: {file_path} | repo: {repo} | branch: {branch} | relevance: 90.0%]",
    }


class TestRRFBasicFusion(unittest.TestCase):
    """test_rrf_basic_fusion: doc in both lists ranks higher than doc in one."""

    def test_rrf_basic_fusion(self):
        list_a = [
            _make_result("fileA.yaml"),
            _make_result("fileC.yaml"),
            _make_result("fileB.yaml"),
        ]
        list_b = [
            _make_result("fileB.yaml"),
            _make_result("fileA.yaml"),
            _make_result("fileD.yaml"),
        ]

        fused = _reciprocal_rank_fusion([list_a, list_b])

        # fileA and fileB appear in both lists — they must rank above
        # fileC and fileD which appear in only one list
        fused_paths = [r["file_path"] for r in fused]
        overlap = {"fileA.yaml", "fileB.yaml"}
        single = {"fileC.yaml", "fileD.yaml"}

        for ov in overlap:
            for sg in single:
                idx_ov = fused_paths.index(ov)
                idx_sg = fused_paths.index(sg)
                self.assertLess(idx_ov, idx_sg,
                                f"{ov} (in both) should rank above {sg} (in one)")


class TestRRFK60Formula(unittest.TestCase):
    """test_rrf_k60_formula: exact arithmetic check."""

    def test_rrf_k60_formula(self):
        list_a = [_make_result("docX.yaml")]  # rank 0 in list A
        list_b = [
            _make_result("other.yaml"),
            _make_result("docX.yaml"),          # rank 1 in list B
        ]

        fused = _reciprocal_rank_fusion([list_a, list_b])
        doc_x = next(r for r in fused if r["file_path"] == "docX.yaml")

        # rank 0 in list A => 1/(60+0+1) = 1/61
        # rank 1 in list B => 1/(60+1+1) = 1/62
        expected = round(1.0 / 61 + 1.0 / 62, 6)
        self.assertAlmostEqual(doc_x["rrf_score"], expected, places=6)


class TestRRFDisjointLists(unittest.TestCase):
    """test_rrf_disjoint_lists: no overlap — interleaved by rank position."""

    def test_rrf_disjoint_lists(self):
        list_a = [
            _make_result("a1.yaml"),
            _make_result("a2.yaml"),
        ]
        list_b = [
            _make_result("b1.yaml"),
            _make_result("b2.yaml"),
        ]

        fused = _reciprocal_rank_fusion([list_a, list_b])
        paths = [r["file_path"] for r in fused]

        # rank-0 items from both lists have score 1/61, so they tie;
        # rank-1 items both have 1/62 and also tie. Within a tie the
        # order depends on dict iteration (insertion order in Python 3.7+).
        # Verify all 4 are present and rank-0 items precede rank-1 items.
        self.assertEqual(len(paths), 4)
        rank0 = {"a1.yaml", "b1.yaml"}
        rank1 = {"a2.yaml", "b2.yaml"}
        for r0 in rank0:
            for r1 in rank1:
                self.assertLess(paths.index(r0), paths.index(r1))


class TestRRFEmptyListGraceful(unittest.TestCase):
    """test_rrf_empty_list_graceful: one empty list → other list returned."""

    def test_rrf_empty_list_graceful(self):
        non_empty = [
            _make_result("file1.yaml"),
            _make_result("file2.yaml"),
        ]

        fused = _reciprocal_rank_fusion([non_empty, []])
        self.assertEqual(len(fused), 2)
        self.assertEqual(fused[0]["file_path"], "file1.yaml")

    def test_rrf_empty_first_list(self):
        non_empty = [_make_result("file1.yaml")]
        fused = _reciprocal_rank_fusion([[], non_empty])
        self.assertEqual(len(fused), 1)
        self.assertEqual(fused[0]["file_path"], "file1.yaml")


class TestRRFBothEmpty(unittest.TestCase):
    """test_rrf_both_empty: both lists empty → empty result, no crash."""

    def test_rrf_both_empty(self):
        fused = _reciprocal_rank_fusion([[], []])
        self.assertEqual(fused, [])

    def test_rrf_no_lists(self):
        fused = _reciprocal_rank_fusion([])
        self.assertEqual(fused, [])


class TestRRFPreservesMetadata(unittest.TestCase):
    """test_rrf_preserves_metadata: all original fields survive fusion."""

    def test_rrf_preserves_metadata(self):
        results = [
            _make_result(
                "charts/svc/values.yaml",
                repo="my-repo",
                branch="release_26_3",
                file_type="helm",
            ),
        ]

        fused = _reciprocal_rank_fusion([results, []])
        r = fused[0]
        self.assertEqual(r["file_path"], "charts/svc/values.yaml")
        self.assertEqual(r["repo"], "my-repo")
        self.assertEqual(r["branch"], "release_26_3")
        self.assertIn("source_citation", r)
        self.assertIn("my-repo", r["source_citation"])


class TestRRFScoreFieldPresent(unittest.TestCase):
    """test_rrf_score_field_present: rrf_score is a float on all results."""

    def test_rrf_score_field_present(self):
        list_a = [_make_result("a.yaml"), _make_result("b.yaml")]
        list_b = [_make_result("c.yaml")]

        fused = _reciprocal_rank_fusion([list_a, list_b])
        for r in fused:
            self.assertIn("rrf_score", r)
            self.assertIsInstance(r["rrf_score"], float)
            self.assertGreater(r["rrf_score"], 0)


class TestRRFRetrievalMethodField(unittest.TestCase):
    """test_rrf_retrieval_method_field: all results say 'hybrid_rrf'."""

    def test_rrf_retrieval_method_field(self):
        list_a = [_make_result("a.yaml")]
        list_b = [_make_result("b.yaml")]

        fused = _reciprocal_rank_fusion([list_a, list_b])
        for r in fused:
            self.assertIn("retrieval_method", r)
            self.assertEqual(r["retrieval_method"], "hybrid_rrf")


# -----------------------------------------------------------------------
# Integration tests: query_memory with mocked retrieval paths
# -----------------------------------------------------------------------

class TestQueryMemoryUsesRRF(unittest.TestCase):
    """test_query_memory_uses_rrf: end-to-end with both paths mocked."""

    def test_query_memory_uses_rrf(self):
        import tools.query_memory as qm

        # Set up BM25 test data
        client_name = "testclient_rrf"
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
                "text": "terraform keyvault secrets for database connections",
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
                "text": "audit service helm chart values configuration deploy",
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

            # Clear BM25 cache so it picks up our test data
            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()

            # Make ChromaDB return no collections (empty DB) so only BM25
            # produces results. This avoids patching sys.modules.
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
                self.assertIn("rrf_score", r)
                self.assertIsInstance(r["rrf_score"], float)
                self.assertIn(r["retrieval_method"],
                              ("hybrid_rrf", "hybrid_rrf_reranked", "hybrid_rrf_no_rerank"))
        finally:
            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()
            cleanup_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)


class TestQueryMemoryChromaFailsGracefully(unittest.TestCase):
    """test_query_memory_chroma_fails_gracefully: ChromaDB error → BM25 results."""

    def test_query_memory_chroma_fails_gracefully(self):
        import tools.query_memory as qm

        client_name = "testclient_rrf_chroma_fail"
        mem_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name / "vectors"
        mem_dir.mkdir(parents=True, exist_ok=True)

        chunks = [
            {
                "id": "c1",
                "text": "pipeline deploy audit service to dev environment",
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

            # Patch PersistentClient at the chromadb package level so the
            # try/except inside query_memory catches the failure gracefully.
            try:
                import chromadb
                has_chromadb = True
            except ImportError:
                has_chromadb = False

            if has_chromadb:
                with patch.object(chromadb, "PersistentClient",
                                  side_effect=Exception("ChromaDB failure")):
                    results = qm.query_memory(client_name, "deploy audit")
            else:
                # chromadb not installed — it'll skip to BM25 automatically
                results = qm.query_memory(client_name, "deploy audit")

            # Should still get BM25 results despite ChromaDB failure
            self.assertGreater(len(results), 0)
            self.assertIn("rrf_score", results[0])
        finally:
            qm._bm25_cache.clear()
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()
            cleanup_dir = Path(qm.PROJECT_ROOT) / "memory" / client_name
            if cleanup_dir.exists():
                shutil.rmtree(str(cleanup_dir), ignore_errors=True)


class TestQueryMemoryBM25FailsGracefully(unittest.TestCase):
    """test_query_memory_bm25_fails_gracefully: BM25 error → ChromaDB results."""

    def test_query_memory_bm25_fails_gracefully(self):
        import tools.query_memory as qm

        client_name = "testclient_rrf_bm25_fail"

        # Patch _get_bm25_index to return None (simulating failure)
        # and patch chromadb to return None so we test pure fallback
        with patch.object(qm, '_get_bm25_index', return_value=(None, [])):
            with patch.dict("sys.modules", {"chromadb": None}):
                results = qm.query_memory(client_name, "deploy audit")

        # Both paths failed — should return empty list gracefully
        self.assertEqual(results, [])

    def test_bm25_fails_chroma_works(self):
        """When BM25 fails but ChromaDB works, results should still come back."""
        import tools.query_memory as qm

        try:
            import chromadb
            has_chromadb = True
        except ImportError:
            has_chromadb = False

        if not has_chromadb:
            self.skipTest("chromadb not installed")

        # Create a mock ChromaDB collection that returns results
        mock_collection = MagicMock()
        mock_collection.query.return_value = {
            "documents": [["deploy audit service pipeline"]],
            "metadatas": [[{
                "file_path": "pipelines/deploy.yaml",
                "repo": "test-repo",
                "branch": "main",
                "chunk_index": 0,
                "file_type": "pipeline",
            }]],
            "distances": [[0.15]],
        }

        mock_client_db = MagicMock()
        col_mock = MagicMock(name="test_col")
        mock_client_db.list_collections.return_value = [col_mock]
        mock_client_db.get_collection.return_value = mock_collection

        client_name = "testclient_rrf_bm25_fail2"

        # Mock embed_texts to return a dummy embedding
        mock_embed = MagicMock(return_value=[[0.1] * 384])
        mock_ef = MagicMock()

        qm._chromadb_clients.clear()
        qm._chromadb_collections.clear()

        try:
            with patch.object(chromadb, "PersistentClient",
                              return_value=mock_client_db):
                with patch("ingest.fast_embed.get_chromadb_ef", return_value=mock_ef):
                    with patch("ingest.fast_embed.embed_texts", mock_embed):
                        with patch.object(qm, '_get_bm25_index',
                                          return_value=(None, [])):
                            results = qm.query_memory(
                                client_name, "deploy audit")

            self.assertGreater(len(results), 0)
            self.assertIn("rrf_score", results[0])
            self.assertIn(results[0]["retrieval_method"],
                          ("hybrid_rrf", "hybrid_rrf_reranked", "hybrid_rrf_no_rerank"))
        finally:
            qm._chromadb_clients.clear()
            qm._chromadb_collections.clear()


if __name__ == "__main__":
    unittest.main()
