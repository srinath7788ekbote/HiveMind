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
import os
import re
import sys
import threading
import time
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
            text, file_path, repo, branch, relevance_pct, chunk_index, file_type
    """
    mem_dir = PROJECT_ROOT / "memory" / client

    # Try ChromaDB first
    try:
        import chromadb
        client_db = chromadb.PersistentClient(path=str(mem_dir / "vectors"))
        collections = client_db.list_collections()

        all_results = []
        for col_info in collections:
            col_name = col_info.name if hasattr(col_info, 'name') else str(col_info)
            collection = client_db.get_collection(col_name)

            # Build where filter
            where_filter = {}
            if branch:
                where_filter["branch"] = branch
            if filter_type:
                where_filter["file_type"] = filter_type

            try:
                results = collection.query(
                    query_texts=[query],
                    n_results=top_k,
                    where=where_filter if where_filter else None,
                )

                if results and results.get("documents"):
                    docs = results["documents"][0]
                    metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(docs)
                    distances = results["distances"][0] if results.get("distances") else [0] * len(docs)

                    for doc, meta, dist in zip(docs, metas, distances):
                        relevance = max(0, 1.0 - dist) * 100
                        all_results.append({
                            "text": doc,
                            "file_path": meta.get("file_path", ""),
                            "repo": meta.get("repo", ""),
                            "branch": meta.get("branch", "default"),
                            "relevance_pct": round(relevance, 1),
                            "chunk_index": meta.get("chunk_index", 0),
                            "file_type": meta.get("file_type", "unknown"),
                        })
            except Exception:
                continue

        # Sort by relevance and return top_k
        all_results.sort(key=lambda r: r["relevance_pct"], reverse=True)
        return all_results[:top_k]

    except ImportError:
        pass

    # ------------------------------------------------------------------
    # Fallback: JSON-based search  (optimised)
    # ------------------------------------------------------------------
    vectors_dir = mem_dir / "vectors"
    if not vectors_dir.exists():
        return []

    # 1. Enumerate vector JSON files and pre-filter by branch
    json_files = list(vectors_dir.glob("*.json"))
    json_files = _filter_vector_files_by_branch(json_files, branch)

    all_chunks: list[dict] = []
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                chunks = json.load(f)
                if isinstance(chunks, list):
                    all_chunks.extend(chunks)
        except (json.JSONDecodeError, OSError):
            continue

    # 2. Apply metadata filters
    if branch:
        all_chunks = [c for c in all_chunks if c.get("metadata", {}).get("branch") == branch]
    if filter_type:
        all_chunks = [c for c in all_chunks if c.get("metadata", {}).get("file_type") == filter_type]

    # 3. Score and rank — with early exit and hard timeout
    scored: list[dict] = []
    high_quality_count = 0
    start_time = time.monotonic()
    timed_out = False

    for chunk in all_chunks:
        # Hard timeout check (Windows-compatible, no signal)
        elapsed = time.monotonic() - start_time
        if elapsed >= JSON_SCORING_TIMEOUT_SECS:
            timed_out = True
            break

        text = chunk.get("text", "")
        meta = chunk.get("metadata", {})
        file_path = meta.get("file_path", "")
        score = _simple_relevance(query, text, file_path)
        if score > 0:
            scored.append({
                "text": text,
                "file_path": meta.get("file_path", ""),
                "repo": meta.get("repo", ""),
                "branch": meta.get("branch", "default"),
                "relevance_pct": round(score * 100, 1),
                "chunk_index": meta.get("chunk_index", 0),
                "file_type": meta.get("file_type", "unknown"),
            })
            if score >= HIGH_RELEVANCE_THRESHOLD:
                high_quality_count += 1

        # Early exit: enough high-quality results — no need to score all chunks
        if high_quality_count >= top_k * 2:
            break

    scored.sort(key=lambda r: r["relevance_pct"], reverse=True)
    results = scored[:top_k]

    # Attach a warning if the search was cut short by timeout
    if timed_out and results:
        results[0]["_warning"] = (
            f"JSON scoring timed out after {JSON_SCORING_TIMEOUT_SECS}s. "
            "Results may be incomplete. Use a narrower branch or query."
        )

    return results


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

