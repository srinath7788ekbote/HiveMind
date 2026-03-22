"""
Query Memory — Branch-aware semantic search

Searches the vector store (ChromaDB or JSON fallback) for chunks
semantically similar to the query.

Usage:
    python tools/query_memory.py --client dfin --query "deploy audit service"
    python tools/query_memory.py --client dfin --query "KV secret" --branch develop
    python tools/query_memory.py --client dfin --query "rollout" --filter_type terraform
    python tools/query_memory.py --client dfin --query "pipeline" --top_k 10
"""

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Performance constants
# ---------------------------------------------------------------------------
HIGH_RELEVANCE_THRESHOLD = 0.8   # Score (0-1) considered "high quality"
JSON_SCORING_TIMEOUT_SECS = 30   # Hard timeout for JSON fallback scoring


def _simple_relevance(query: str, text: str, file_path: str = "") -> float:
    """
    Compute a simple relevance score between query and text.
    Used when ChromaDB is not available.
    Returns a score between 0.0 and 1.0.
    """
    query_lower = query.lower()
    query_tokens = set(re.findall(r'\w+', query_lower))
    text_lower = text.lower()
    text_tokens = set(re.findall(r'\w+', text_lower))

    if not query_tokens:
        return 0.0

    # Jaccard-like overlap
    overlap = query_tokens & text_tokens
    score = len(overlap) / len(query_tokens)

    # Boost for exact phrase match in text
    if query_lower in text_lower:
        score = min(1.0, score + 0.3)

    # Boost for compound name match (e.g. "cd_deploy_env" as a whole)
    # Extract potential compound names from query (underscore/hyphen-joined)
    compound_names = re.findall(r'[a-z][a-z0-9]*(?:[_-][a-z0-9]+)+', query_lower)
    for name in compound_names:
        if name in text_lower:
            score = min(1.0, score + 0.4)
        if file_path and name in file_path.lower():
            score = min(1.0, score + 0.5)

    # Boost for file path match on any individual query token
    if file_path:
        fp_lower = file_path.lower()
        path_overlap = sum(1 for t in query_tokens if t in fp_lower and len(t) > 2)
        if path_overlap > 0:
            score = min(1.0, score + 0.15 * path_overlap)

    return round(min(1.0, score), 4)


def _filter_vector_files_by_branch(
    json_files: list[Path], branch: str | None
) -> list[Path]:
    """
    Pre-filter vector JSON files by branch name.

    Vector files follow the naming convention ``<repo>_<branch>.json``
    (e.g. ``dfin-harness-pipelines_release_26_2.json``).  When a branch
    is specified we can skip loading files that clearly belong to other
    branches — this avoids parsing tens of megabytes of irrelevant data.

    Falls back to all files when no branch match is found so callers
    never receive an empty list accidentally.
    """
    if not branch or branch == "all":
        return json_files

    # Normalise branch slug for filename matching
    branch_slug = branch.replace("/", "_").replace("-", "_").lower()

    filtered = [
        f for f in json_files if branch_slug in f.stem.replace("-", "_").lower()
    ]

    # Fall back to all files if nothing matched (branch may be encoded
    # differently or the naming convention is non-standard).
    return filtered if filtered else json_files


# ---------------------------------------------------------------------------
# BM25 search index (cached per client for process lifetime)
# ---------------------------------------------------------------------------
_bm25_cache: dict = {}  # client -> (bm25_index, all_chunks)


def _tokenize_bm25(text: str, file_path: str = "") -> list[str]:
    """Tokenize text for BM25 with infrastructure-aware splitting.

    Splits on word boundaries and also expands hyphenated/underscored
    compound names (e.g. "tagging-service" -> ["tagging-service", "tagging", "service"])
    so that both exact compound matches and partial matches score well.
    """
    combined = text + " " + file_path
    tokens = re.findall(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', combined.lower())
    expanded = []
    for t in tokens:
        expanded.append(t)
        parts = re.split(r'[-_]', t)
        if len(parts) > 1:
            expanded.extend(p for p in parts if len(p) > 1)
    return expanded


def _get_bm25_index(vectors_dir: Path):
    """Build or retrieve cached BM25 index for a vectors directory.

    On first call, loads all JSON vector files and builds a BM25Okapi
    index.  Subsequent calls return the cached index.

    Uses the full directory path as cache key so that test patches to
    PROJECT_ROOT produce isolated caches.
    """
    cache_key = str(vectors_dir)
    if cache_key in _bm25_cache:
        return _bm25_cache[cache_key]

    if not vectors_dir.exists():
        return None, []

    all_chunks = []
    for jf in sorted(vectors_dir.glob("*.json")):
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_chunks.extend(data)
        except (json.JSONDecodeError, OSError):
            continue

    if not all_chunks:
        return None, []

    tokenized = [
        _tokenize_bm25(
            c.get("text", ""),
            c.get("metadata", {}).get("file_path", ""),
        )
        for c in all_chunks
    ]

    from rank_bm25 import BM25Plus
    bm25 = BM25Plus(tokenized)
    _bm25_cache[cache_key] = (bm25, all_chunks)
    return bm25, all_chunks


# ---------------------------------------------------------------------------
# Reciprocal Rank Fusion (RRF)
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    result_lists: list[list[dict]],
    k: int = 60,
    id_field: str = "chunk_id",
) -> list[dict]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Each result in each list must have an id_field (e.g. chunk_id).
    The fused list preserves all metadata from the highest-ranked
    occurrence of each document across all lists.

    Args:
        result_lists: List of ranked result lists. Each list is a list
                      of result dicts (with chunk_id, text, metadata etc)
        k:            RRF constant. k=60 is the proven industry default.
        id_field:     Field to use as unique document identifier.

    Returns:
        Single fused list sorted by descending RRF score,
        with rrf_score added to each result dict.
    """
    scores: dict[str, float] = {}
    best_result: dict[str, dict] = {}  # id -> best result dict

    for result_list in result_lists:
        for rank, result in enumerate(result_list):
            doc_id = (
                result.get(id_field)
                or result.get("source_file")
                or result.get("file_path")
                or str(rank)
            )
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
            # Keep the result dict from the highest-ranked occurrence
            if doc_id not in best_result or rank == 0:
                best_result[doc_id] = result

    # Build fused result list sorted by RRF score descending
    fused = []
    for doc_id, score in sorted(scores.items(), key=lambda x: x[1], reverse=True):
        result = dict(best_result[doc_id])
        result["rrf_score"] = round(score, 6)
        result["retrieval_method"] = "hybrid_rrf"
        fused.append(result)

    return fused


# ---------------------------------------------------------------------------
# ChromaDB caches (avoids 250ms+ PersistentClient creation per query)
# ---------------------------------------------------------------------------
_chromadb_clients: dict = {}  # vectors_path -> chromadb.PersistentClient
_chromadb_collections: dict = {}  # vectors_path -> {col_name: Collection}


def query_memory(
    client: str,
    query: str,
    branch: str = None,
    filter_type: str = None,
    top_k: int = 5,
) -> list[dict]:
    """
    Search the vector store for chunks matching the query.

    Args:
        client: Client name.
        query: Search query text.
        branch: Optional branch filter.
        filter_type: Optional file type filter (e.g., "terraform", "pipeline").
        top_k: Number of results to return.

    Returns:
        List of result dicts with keys:
            text, file_path, repo, branch, relevance_pct, chunk_index, file_type,
            source_citation  (pre-formatted citation string for agent responses)
    """
    mem_dir = PROJECT_ROOT / "memory" / client

    # ------------------------------------------------------------------
    # Phase 1: ChromaDB semantic search
    # ------------------------------------------------------------------
    chroma_results = []
    try:
        import chromadb
    except ImportError:
        chromadb = None

    if chromadb is not None:
        try:
            vectors_path = str(mem_dir / "vectors")
            if vectors_path not in _chromadb_clients:
                _chromadb_clients[vectors_path] = chromadb.PersistentClient(path=vectors_path)
            client_db = _chromadb_clients[vectors_path]

            # Cache collection objects to avoid repeated get_collection overhead
            if vectors_path not in _chromadb_collections:
                from ingest.fast_embed import get_chromadb_ef
                ef = get_chromadb_ef()
                col_map = {}
                for col_info in client_db.list_collections():
                    col_name = col_info.name if hasattr(col_info, 'name') else str(col_info)
                    col_map[col_name] = client_db.get_collection(col_name, embedding_function=ef)
                _chromadb_collections[vectors_path] = col_map

            col_map = _chromadb_collections[vectors_path]
            col_names = list(col_map.keys())

            # Filter collections by branch name when a branch is specified
            if branch and col_names:
                branch_slug = branch.replace("/", "_").replace("-", "_").lower()
                filtered = [n for n in col_names if branch_slug in n.replace("-", "_").lower()]
                if filtered:
                    col_names = filtered

            if col_names:
                from ingest.fast_embed import embed_texts

                # Embed the query with the same function used at ingest
                query_embedding = embed_texts([query])[0]

                # Build where filter once — skip branch filter when collections
                # are already branch-specific (avoids redundant metadata scan)
                where_filter = {}
                if filter_type:
                    where_filter["file_type"] = filter_type

                query_args = where_filter if where_filter else None
                col_objects = [col_map[n] for n in col_names]

                def _query_one(collection):
                    """Query a single pre-fetched collection."""
                    try:
                        results = collection.query(
                            query_embeddings=[query_embedding],
                            n_results=max(top_k, 20),
                            where=query_args,
                        )
                    except Exception:
                        return []

                    hits = []
                    if results and results.get("documents"):
                        docs = results["documents"][0]
                        metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
                        distances = results["distances"][0] if results.get("distances") else [0] * len(docs)

                        for doc, meta, dist in zip(docs, metas, distances):
                            rel = max(0.0, 1.0 - dist)
                            fp = meta.get("file_path", "")
                            rp = meta.get("repo", "")
                            br = meta.get("branch", "default")
                            hits.append({
                                "text": doc,
                                "file_path": fp,
                                "repo": rp,
                                "branch": br,
                                "relevance": round(rel, 4),
                                "relevance_pct": round(rel * 100, 1),
                                "chunk_index": meta.get("chunk_index", 0),
                                "file_type": meta.get("file_type", "unknown"),
                                "source_citation": f"[Source: {fp} | repo: {rp} | branch: {br} | relevance: {round(rel * 100, 1)}%]",
                            })
                    return hits

                # Query all collections in parallel
                all_results = []
                with ThreadPoolExecutor(max_workers=min(len(col_objects), 16)) as pool:
                    for hits in pool.map(_query_one, col_objects):
                        all_results.extend(hits)

                # Sort by relevance and keep top-20 for RRF fusion
                all_results.sort(key=lambda r: r["relevance_pct"], reverse=True)
                chroma_results = all_results[:20]
        except Exception:
            chroma_results = []

    # ------------------------------------------------------------------
    # Phase 2: BM25 keyword search
    # ------------------------------------------------------------------
    bm25_results = []
    bm25, all_chunks = _get_bm25_index(mem_dir / "vectors")
    if bm25 is not None:
        query_tokens = _tokenize_bm25(query)
        scores = bm25.get_scores(query_tokens)

        # Build scored results with branch/type filtering
        scored: list[tuple] = []
        for i in range(len(all_chunks)):
            if scores[i] <= 0:
                continue
            meta = all_chunks[i].get("metadata", {})
            if branch and meta.get("branch") != branch:
                continue
            if filter_type and meta.get("file_type") != filter_type:
                continue
            scored.append((scores[i], i))

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = scored[:20]  # Keep top-20 for RRF fusion

            max_score = scored[0][0]
            for score, idx in scored:
                chunk = all_chunks[idx]
                meta = chunk.get("metadata", {})
                fp = meta.get("file_path", "")
                rp = meta.get("repo", "")
                br = meta.get("branch", "default")
                rel_pct = round((score / max_score) * 100, 1) if max_score > 0 else 0
                bm25_results.append({
                    "text": chunk.get("text", ""),
                    "file_path": fp,
                    "repo": rp,
                    "branch": br,
                    "relevance": round(rel_pct / 100, 4),
                    "relevance_pct": rel_pct,
                    "chunk_index": meta.get("chunk_index", 0),
                    "file_type": meta.get("file_type", "unknown"),
                    "source_citation": f"[Source: {fp} | repo: {rp} | branch: {br} | relevance: {rel_pct}%]",
                })

    # ------------------------------------------------------------------
    # Phase 3: Reciprocal Rank Fusion
    # ------------------------------------------------------------------
    if chroma_results and bm25_results:
        fused = _reciprocal_rank_fusion([chroma_results, bm25_results])
        return fused[:top_k]
    elif chroma_results:
        # BM25 unavailable — return ChromaDB results with RRF metadata
        for r in chroma_results:
            r["rrf_score"] = round(1.0 / (60 + chroma_results.index(r) + 1), 6)
            r["retrieval_method"] = "hybrid_rrf"
        return chroma_results[:top_k]
    elif bm25_results:
        # ChromaDB unavailable — return BM25 results with RRF metadata
        for r in bm25_results:
            r["rrf_score"] = round(1.0 / (60 + bm25_results.index(r) + 1), 6)
            r["retrieval_method"] = "hybrid_rrf"
        return bm25_results[:top_k]
    else:
        return []


def main():
    parser = argparse.ArgumentParser(description="HiveMind Memory Query — semantic search")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--branch", default=None, help="Branch filter")
    parser.add_argument("--filter_type", default=None, help="File type filter")
    parser.add_argument("--top_k", type=int, default=5, help="Number of results")
    args = parser.parse_args()

    results = query_memory(
        client=args.client,
        query=args.query,
        branch=args.branch,
        filter_type=args.filter_type,
        top_k=args.top_k,
    )

    if not results:
        print("No results found.")
        return

    # Print timeout warning if present
    if results and results[0].get("_warning"):
        print(f"⚠️  {results[0]['_warning']}\n")

    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"--- Result {i} (relevance: {r['relevance_pct']}%) ---")
        print(f"File: {r['file_path']}")
        print(f"Repo: {r['repo']} | Branch: {r['branch']} | Type: {r['file_type']}")
        print(f"Text: {r['text'][:200]}...")
        print()


if __name__ == "__main__":
    main()

