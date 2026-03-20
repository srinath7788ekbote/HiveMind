"""
Embedding functions using ChromaDB's built-in ONNX model (all-MiniLM-L6-v2).

Used by both embed_chunks.py (ingest) and query_memory.py (search)
to ensure consistent embeddings.

At ingest: pre-computes embeddings for all chunks (one-time batch cost).
At query: embeds a single query string (~200ms after warmup).

The ONNX model is downloaded once automatically, then runs fully offline.
"""

import logging

logger = logging.getLogger(__name__)

DIMENSION = 384  # all-MiniLM-L6-v2 output dimension

_default_ef = None


def get_chromadb_ef():
    """Return ChromaDB's default embedding function (ONNX all-MiniLM-L6-v2).

    Cached as a singleton so the model loads only once per process.
    """
    global _default_ef
    if _default_ef is None:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
        _default_ef = DefaultEmbeddingFunction()
    return _default_ef


def embed_texts(texts: list[str], batch_size: int = 256, verbose: bool = False) -> list[list[float]]:
    """
    Compute embeddings for a list of texts using the ONNX model.

    Batches internally to avoid memory pressure and provide progress.
    """
    if not texts:
        return []
    ef = get_chromadb_ef()

    # Small list — embed in one shot
    if len(texts) <= batch_size:
        return ef(texts)

    # Large list — batch with progress
    all_embeddings = []
    total = len(texts)
    for i in range(0, total, batch_size):
        batch = texts[i:i + batch_size]
        all_embeddings.extend(ef(batch))
        done = min(i + batch_size, total)
        if verbose:
            print(f"             Embedded {done}/{total} chunks...", flush=True)
    return all_embeddings
