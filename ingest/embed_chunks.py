"""
Embed Chunks

Splits files into chunks and stores them in a ChromaDB vector store
for semantic search. Uses sentence-transformers for local embeddings.

No API calls — all embedding happens locally.
"""

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


# Default chunk settings
DEFAULT_CHUNK_SIZE = 500  # characters
DEFAULT_CHUNK_OVERLAP = 50  # characters


def _chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping chunks.

    Args:
        text: The text to split.
        chunk_size: Maximum characters per chunk.
        overlap: Number of overlapping characters between chunks.

    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    # Try to split on natural boundaries (newlines, then spaces)
    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + chunk_size

        if end >= text_len:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Try to find a natural break point (newline or space)
        break_point = end
        newline_pos = text.rfind('\n', start + chunk_size // 2, end)
        if newline_pos > start:
            break_point = newline_pos + 1
        else:
            space_pos = text.rfind(' ', start + chunk_size // 2, end)
            if space_pos > start:
                break_point = space_pos + 1

        chunk = text[start:break_point].strip()
        if chunk:
            chunks.append(chunk)

        start = break_point - overlap
        if start < 0:
            start = 0
        # Avoid infinite loop
        if start >= break_point:
            start = break_point

    return chunks


def _compute_chunk_id(file_path: str, chunk_index: int, branch: str = "default") -> str:
    """Compute a stable ID for a chunk."""
    raw = f"{file_path}:{branch}:{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _file_to_chunks(
    file_path: str,
    repo_root: str,
    branch: str = "default",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[dict]:
    """
    Read a file and split it into chunks with metadata.

    Returns list of dicts with:
        id, text, metadata (file_path, repo, branch, chunk_index, file_type)
    """
    p = Path(file_path)
    if not p.exists() or not p.is_file():
        return []

    try:
        text = p.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []

    if not text.strip():
        return []

    chunks = _chunk_text(text, chunk_size, overlap)
    repo_name = Path(repo_root).name

    try:
        rel_path = str(p.relative_to(repo_root))
    except ValueError:
        rel_path = str(p)

    # Classify file type from extension/path
    suffix = p.suffix.lower()
    file_type = "unknown"
    if suffix == '.tf':
        file_type = "terraform"
    elif suffix in ('.yaml', '.yml'):
        if 'pipeline' in p.name.lower():
            file_type = "pipeline"
        elif 'chart' in p.name.lower():
            file_type = "helm_chart"
        elif 'values' in p.name.lower():
            file_type = "helm_values"
        elif 'templates' in str(p):
            file_type = "template"
        else:
            file_type = "yaml"
    elif suffix == '.md':
        file_type = "markdown"

    results = []
    for i, chunk_text in enumerate(chunks):
        chunk_id = _compute_chunk_id(rel_path, i, branch)
        results.append({
            "id": chunk_id,
            "text": chunk_text,
            "metadata": {
                "file_path": rel_path,
                "repo": repo_name,
                "branch": branch,
                "chunk_index": i,
                "file_type": file_type,
                "total_chunks": len(chunks),
            },
        })
    return results


def _write_json_chunks(mem: Path, collection_name: str, all_chunks: list[dict]):
    """Write chunks to JSON file for fallback search."""
    json_store = mem / "vectors" / f"{collection_name}.json"
    json_store.parent.mkdir(parents=True, exist_ok=True)

    existing = {}
    if json_store.exists():
        try:
            with open(json_store, 'r', encoding='utf-8') as f:
                existing_list = json.load(f)
                existing = {c["id"]: c for c in existing_list}
        except (json.JSONDecodeError, OSError):
            existing = {}

    for chunk in all_chunks:
        existing[chunk["id"]] = chunk

    with open(json_store, 'w', encoding='utf-8') as f:
        json.dump(list(existing.values()), f, indent=1)


def _load_embed_state(mem: Path, collection_name: str) -> dict:
    """Load the mtime checkpoint for a collection. {rel_path: mtime_epoch}."""
    state_file = mem / "vectors" / f".{collection_name}.state.json"
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_embed_state(mem: Path, collection_name: str, state: dict):
    """Persist the mtime checkpoint for a collection."""
    state_file = mem / "vectors" / f".{collection_name}.state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")


def embed_repo(
    repo_path: str,
    memory_dir: str,
    branch: str = "default",
    collection_name: Optional[str] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    file_extensions: Optional[set] = None,
    verbose: bool = False,
) -> dict:
    """
    Embed all relevant files from a repository into ChromaDB.

    Incremental: skips files whose mtime hasn't changed since last run.

    Args:
        repo_path: Absolute path to the repo.
        memory_dir: Directory for the ChromaDB persistent storage.
        branch: Branch being indexed.
        collection_name: ChromaDB collection name. Defaults to repo name.
        chunk_size: Characters per chunk.
        file_extensions: Set of file extensions to include. Defaults to common ones.

    Returns:
        dict with keys: chunk_count, file_count, collection_name, skipped_files
    """
    repo = Path(repo_path)
    mem = Path(memory_dir)
    mem.mkdir(parents=True, exist_ok=True)

    if file_extensions is None:
        file_extensions = {'.tf', '.yaml', '.yml', '.md', '.json', '.hcl', '.tfvars'}

    if collection_name is None:
        collection_name = repo.name

    # Skip binary/irrelevant extensions
    skip_extensions = {
        '.jar', '.class', '.png', '.jpg', '.gif', '.zip', '.tar',
        '.gz', '.exe', '.dll', '.bin', '.pyc', '.lock',
    }

    # Load mtime checkpoint for incremental embedding
    embed_state = _load_embed_state(mem, collection_name)

    all_chunks = []
    file_count = 0
    skipped_files = 0

    for file_path in repo.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() in skip_extensions:
            continue
        if file_path.suffix.lower() not in file_extensions:
            continue
        # Skip .git directory
        if '.git' in file_path.parts:
            continue

        # Incremental: skip files whose mtime hasn't changed
        try:
            rel_path = str(file_path.relative_to(repo)).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path)

        current_mtime = int(file_path.stat().st_mtime)
        prev_mtime = embed_state.get(rel_path)
        if prev_mtime is not None and prev_mtime >= current_mtime:
            skipped_files += 1
            continue

        chunks = _file_to_chunks(str(file_path), str(repo), branch, chunk_size)
        if chunks:
            all_chunks.extend(chunks)
            file_count += 1
            # Record mtime for this file (will be persisted at end)
            embed_state[rel_path] = current_mtime
            if verbose and file_count % 50 == 0:
                print(f"             {file_count} files chunked ({len(all_chunks)} chunks)...", flush=True)

    if verbose:
        if skipped_files:
            print(f"             {skipped_files} unchanged files skipped", flush=True)
        print(f"             {file_count} files -> {len(all_chunks)} chunks to embed", flush=True)

    if not all_chunks:
        # Still save state so skipped files stay cached
        _save_embed_state(mem, collection_name, embed_state)
        return {"chunk_count": 0, "file_count": 0, "collection_name": collection_name,
                "skipped_files": skipped_files}

    # Try to use ChromaDB for vector storage
    try:
        import chromadb
        from ingest.fast_embed import embed_texts, get_chromadb_ef

        ef = get_chromadb_ef()
        client = chromadb.PersistentClient(path=str(mem / "vectors"))

        all_texts = [c["text"] for c in all_chunks]

        # Pre-compute all embeddings (runs in seconds, not minutes)
        if verbose:
            print(f"             Computing embeddings for {len(all_texts)} chunks...", flush=True)
        all_embeddings = embed_texts(all_texts, verbose=verbose)

        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
        )

        # Upsert with pre-computed embeddings
        batch_size = 500
        total_batches = (len(all_chunks) + batch_size - 1) // batch_size
        for batch_num, i in enumerate(range(0, len(all_chunks), batch_size), 1):
            batch = all_chunks[i:i + batch_size]
            batch_embeds = all_embeddings[i:i + batch_size]
            collection.upsert(
                ids=[c["id"] for c in batch],
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
                embeddings=batch_embeds,
            )
            if verbose:
                print(f"             Upserted batch {batch_num}/{total_batches} ({min(i + batch_size, len(all_chunks))}/{len(all_chunks)} chunks)", flush=True)

        # Also write JSON for fallback / non-ChromaDB queries
        _write_json_chunks(mem, collection_name, all_chunks)

    except ImportError:
        # Fallback: store as JSON for basic search
        _write_json_chunks(mem, collection_name, all_chunks)

    # Persist mtime state so next run skips unchanged files
    _save_embed_state(mem, collection_name, embed_state)

    return {
        "chunk_count": len(all_chunks),
        "file_count": file_count,
        "skipped_files": skipped_files,
        "collection_name": collection_name,
    }
