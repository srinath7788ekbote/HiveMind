"""
Populate ChromaDB from existing JSON vector files.

Reads pre-chunked JSON files from memory/<client>/vectors/ and upserts
them into ChromaDB collections with rate limiting to prevent memory
pressure and CPU overload.

Supports multi-client operation: when no --client flag is given it
discovers all clients from the clients/ directory.

BM25 search continues working from the JSON files during population --
no downtime.  Once ChromaDB collections are populated, query_memory.py
automatically uses them as the primary search path.

Usage:
    python scripts/populate_chromadb.py                     # all clients
    python scripts/populate_chromadb.py --client dfin        # one client
    python scripts/populate_chromadb.py --verify             # check all
    python scripts/populate_chromadb.py --client dfin --verify
    python scripts/populate_chromadb.py --dry-run            # estimate only
    python scripts/populate_chromadb.py --batch-size 200 --sleep 10
"""

import argparse
import json
import signal
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration defaults (overridable via CLI flags)
# ---------------------------------------------------------------------------
BATCH_SIZE = 500               # chunks per ChromaDB upsert batch
SLEEP_BETWEEN_BATCHES = 5      # seconds to sleep between batches
MAX_MEMORY_PERCENT = 80        # pause if RAM exceeds this %
MEMORY_PAUSE_SECS = 30         # how long to pause when RAM is high

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Client discovery (shared pattern)
# ---------------------------------------------------------------------------


def discover_clients(project_root: Path | None = None) -> list[str]:
    """Return sorted list of client names that have a repos.yaml."""
    root = project_root or PROJECT_ROOT
    clients_dir = root / "clients"
    if not clients_dir.exists():
        return []
    return sorted(
        d.name
        for d in clients_dir.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "repos.yaml").exists()
    )


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
_shutdown_requested = False


def _signal_handler(sig, frame):
    global _shutdown_requested
    _shutdown_requested = True
    print("\n[!] Interrupt received -- finishing current batch before stopping...")


signal.signal(signal.SIGINT, _signal_handler)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_memory_percent() -> float:
    """Return current RAM usage percentage via psutil."""
    import psutil
    return psutil.virtual_memory().percent


def _wait_for_memory(max_pct: float, pause_secs: int) -> None:
    """Block until RAM drops below *max_pct*, sleeping *pause_secs* each loop."""
    while _get_memory_percent() > max_pct:
        pct = _get_memory_percent()
        print(f"  Memory: {pct:.0f}% -- PAUSING {pause_secs}s to let RAM recover...")
        time.sleep(pause_secs)
    pct = _get_memory_percent()
    print(f"  Memory: {pct:.0f}% -- OK")


def _load_json_files(vectors_dir: Path) -> list[tuple[str, list[dict]]]:
    """Load all *.json vector files, returning (collection_name, chunks) pairs."""
    results = []
    for jf in sorted(vectors_dir.glob("*.json")):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                continue
            collection_name = jf.stem  # filename without .json
            results.append((collection_name, data))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  WARNING: skipping {jf.name} -- {exc}")
    return results


def _estimate_time(total_chunks: int, batch_size: int, sleep_secs: int) -> str:
    """Return a human-readable estimated time string."""
    num_batches = (total_chunks + batch_size - 1) // batch_size
    # Rough estimate: ~2s per batch for ONNX embedding + sleep overhead
    embedding_time = num_batches * 2
    sleep_time = num_batches * sleep_secs
    total_secs = embedding_time + sleep_time
    hours, remainder = divmod(total_secs, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours > 0:
        return f"{int(hours)} hours {int(minutes)} minutes"
    return f"{int(minutes)} minutes"


def _is_db_locked(vectors_dir: Path) -> bool:
    """Check if the ChromaDB sqlite file is locked by another process."""
    db_file = vectors_dir / "chroma.sqlite3"
    if not db_file.exists():
        return False
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_file), timeout=1)
        conn.execute("SELECT 1")
        conn.close()
        return False
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Verify mode -- single client
# ---------------------------------------------------------------------------


def verify(client: str, project_root: Path | None = None) -> dict:
    """Check collection status without embedding anything. Returns summary dict."""
    root = project_root or PROJECT_ROOT
    vectors_dir = root / "memory" / client / "vectors"
    if not vectors_dir.exists():
        print(f"  No vectors directory found at {vectors_dir}")
        return {"client": client, "total_json": 0, "total_chroma": 0, "collections": 0}

    json_files = _load_json_files(vectors_dir)
    if not json_files:
        print("  No JSON vector files found.")
        return {"client": client, "total_json": 0, "total_chroma": 0, "collections": 0}

    import chromadb
    db = chromadb.PersistentClient(path=str(vectors_dir))
    existing_collections = {
        (c.name if hasattr(c, "name") else str(c)): c
        for c in db.list_collections()
    }

    print(f"\n{'Collection':<55} {'JSON chunks':>12} {'ChromaDB':>10} {'Status':>12}")
    print("-" * 95)

    total_json = 0
    total_chroma = 0
    missing = 0
    incomplete = 0

    for col_name, chunks in json_files:
        json_count = len(chunks)
        total_json += json_count

        if col_name in existing_collections:
            col = db.get_collection(col_name)
            chroma_count = col.count()
            total_chroma += chroma_count
            if chroma_count >= json_count:
                status = "[OK] OK"
            else:
                status = "[!] INCOMPLETE"
                incomplete += 1
        else:
            chroma_count = 0
            status = "[X] MISSING"
            missing += 1

        print(f"  {col_name:<53} {json_count:>12,} {chroma_count:>10,} {status:>12}")

    print("-" * 95)
    print(f"  {'TOTAL':<53} {total_json:>12,} {total_chroma:>10,}")
    print(f"\n  Collections: {len(json_files)} total, "
          f"{len(json_files) - missing - incomplete} complete, "
          f"{incomplete} incomplete, {missing} missing")

    if missing == 0 and incomplete == 0:
        print("\n  All collections are fully populated. [OK]")
    else:
        print(f"\n  Run without --verify to populate {missing + incomplete} collection(s).")

    return {
        "client": client,
        "total_json": total_json,
        "total_chroma": total_chroma,
        "collections": len(json_files),
    }


# ---------------------------------------------------------------------------
# Populate -- single client
# ---------------------------------------------------------------------------


def populate(
    client: str,
    batch_size: int,
    sleep_secs: int,
    max_mem_pct: float,
    dry_run: bool = False,
    project_root: Path | None = None,
) -> dict:
    """Load JSON vector files into ChromaDB with rate limiting. Returns summary dict."""
    root = project_root or PROJECT_ROOT
    vectors_dir = root / "memory" / client / "vectors"
    if not vectors_dir.exists():
        print(f"  No vectors directory found at {vectors_dir}")
        return {"client": client, "total_embedded": 0, "collections_done": 0}

    # Check for DB lock before starting
    if _is_db_locked(vectors_dir):
        print(f"  [!] {client} -- ChromaDB locked by another process, skipping")
        return {"client": client, "total_embedded": 0, "collections_done": 0, "skipped_lock": True}

    json_files = _load_json_files(vectors_dir)
    if not json_files:
        print("  No JSON vector files found.")
        return {"client": client, "total_embedded": 0, "collections_done": 0}

    total_chunks = sum(len(chunks) for _, chunks in json_files)
    est = _estimate_time(total_chunks, batch_size, sleep_secs)

    print(f"\n  Total chunks: {total_chunks:,}")
    print(f"  Estimated time: {est} (batch size {batch_size}, {sleep_secs}s sleep)")
    print(f"  Tip: Run overnight. BM25 search continues working during population.\n")

    if dry_run:
        return {"client": client, "total_embedded": 0, "collections_done": 0, "dry_run": True}

    import chromadb
    from ingest.fast_embed import get_chromadb_ef

    db = chromadb.PersistentClient(path=str(vectors_dir))
    ef = get_chromadb_ef()

    overall_start = time.time()
    total_embedded = 0
    collections_done = 0
    collections_skipped = 0

    for col_name, chunks in json_files:
        if _shutdown_requested:
            break

        chunk_count = len(chunks)

        # --- Resumability: skip collections already fully populated ---
        try:
            existing_col = db.get_collection(col_name)
            existing_count = existing_col.count()
            if existing_count >= chunk_count:
                print(f"  Skipping {col_name} -- already populated ({existing_count:,} chunks)")
                collections_skipped += 1
                total_embedded += existing_count
                continue
        except Exception:
            pass  # collection doesn't exist yet

        print(f"  Processing collection: {col_name} ({chunk_count:,} chunks)")
        col_start = time.time()

        collection = db.get_or_create_collection(
            name=col_name,
            metadata={"hnsw:space": "cosine"},
            embedding_function=ef,
        )

        num_batches = (chunk_count + batch_size - 1) // batch_size

        for batch_idx in range(num_batches):
            if _shutdown_requested:
                break

            start_i = batch_idx * batch_size
            end_i = min(start_i + batch_size, chunk_count)
            batch = chunks[start_i:end_i]

            # --- Memory check before each batch ---
            _wait_for_memory(max_mem_pct, MEMORY_PAUSE_SECS)

            batch_start = time.time()

            ids = [c["id"] for c in batch]
            documents = [c["text"] for c in batch]
            metadatas = [c["metadata"] for c in batch]

            # Let ChromaDB embed via the ONNX function (same as query time)
            collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas,
            )

            batch_elapsed = time.time() - batch_start
            print(f"    Batch {batch_idx + 1}/{num_batches}: "
                  f"chunks {start_i + 1}-{end_i} embedded ({batch_elapsed:.1f}s)")

            total_embedded += len(batch)

            # --- Rate limit sleep (skip after last batch of collection) ---
            if batch_idx < num_batches - 1 and not _shutdown_requested:
                time.sleep(sleep_secs)

        col_elapsed = time.time() - col_start
        collections_done += 1
        print(f"  Collection complete: {col_name} ({col_elapsed:.1f}s)\n")

    # --- Summary ---
    overall_elapsed = time.time() - overall_start
    hours, remainder = divmod(overall_elapsed, 3600)
    minutes, secs = divmod(remainder, 60)

    return {
        "client": client,
        "total_embedded": total_embedded,
        "collections_done": collections_done,
        "collections_skipped": collections_skipped,
        "elapsed": overall_elapsed,
        "elapsed_str": f"{int(hours)}h {int(minutes)}m {int(secs)}s",
        "interrupted": _shutdown_requested,
    }


# ---------------------------------------------------------------------------
# Multi-client orchestration
# ---------------------------------------------------------------------------


def run_all_verify(clients: list[str], project_root: Path | None = None):
    """Verify ChromaDB status for all given clients."""
    multi = len(clients) > 1
    if multi:
        print("=" * 60)
        print("HIVEMIND CHROMADB VERIFICATION -- ALL CLIENTS")
        print("=" * 60)
        print(f"Discovered clients: {', '.join(clients)}")

    summaries = []
    for client in clients:
        if multi:
            print(f"\n-- CLIENT: {client} " + "-" * (46 - len(client)))
        summary = verify(client, project_root)
        summaries.append(summary)

    if multi:
        print("\n" + "=" * 60)
        total_json = sum(s["total_json"] for s in summaries)
        total_chroma = sum(s["total_chroma"] for s in summaries)
        total_cols = sum(s["collections"] for s in summaries)
        for s in summaries:
            print(f"  {s['client']:<12} {s['total_chroma']:,} chunks across {s['collections']} collections")
        print(f"  {'Total':<12} {total_chroma:,} / {total_json:,} chunks, {total_cols} collections")
        print("=" * 60)


def run_all_populate(
    clients: list[str],
    batch_size: int,
    sleep_secs: int,
    max_mem_pct: float,
    dry_run: bool = False,
    project_root: Path | None = None,
):
    """Populate ChromaDB for all given clients."""
    multi = len(clients) > 1
    if multi:
        print("=" * 60)
        print("HIVEMIND CHROMADB POPULATION -- ALL CLIENTS")
        print("=" * 60)
        print(f"Discovered clients: {', '.join(clients)}")

    summaries = []
    total_start = time.time()

    for client in clients:
        if _shutdown_requested:
            break
        if multi:
            print(f"\n-- CLIENT: {client} " + "-" * (46 - len(client)))
        summary = populate(
            client=client,
            batch_size=batch_size,
            sleep_secs=sleep_secs,
            max_mem_pct=max_mem_pct,
            dry_run=dry_run,
            project_root=project_root,
        )
        summaries.append(summary)

    total_elapsed = time.time() - total_start

    if multi:
        hours, remainder = divmod(total_elapsed, 3600)
        minutes, secs = divmod(remainder, 60)
        print("\n" + "=" * 60)
        if _shutdown_requested:
            print("INTERRUPTED -- run again to continue")
        else:
            print("POPULATION COMPLETE -- ALL CLIENTS")
        print("=" * 60)
        total_embedded = sum(s["total_embedded"] for s in summaries)
        total_cols = sum(s["collections_done"] for s in summaries)
        for s in summaries:
            print(f"  {s['client']:<12} {s['total_embedded']:,} chunks, "
                  f"{s['collections_done']} collections")
        print(f"  {'Total':<12} {total_embedded:,} chunks, {total_cols} collections, "
              f"{int(hours)}h {int(minutes)}m {int(secs)}s")
        print("=" * 60)
    elif summaries:
        s = summaries[0]
        if not dry_run:
            print("=" * 60)
            if s.get("interrupted"):
                print("Interrupted -- run again to continue from next collection")
            else:
                print("Population complete!")
            print(f"  Collections processed: {s['collections_done']}")
            print(f"  Collections skipped (already done): {s.get('collections_skipped', 0)}")
            print(f"  Total chunks embedded: {s['total_embedded']:,}")
            print(f"  Total time: {s.get('elapsed_str', 'n/a')}")
            print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Populate ChromaDB from existing JSON vector files with rate limiting."
    )
    parser.add_argument("--client", default=None,
                        help="Client name (default: all discovered clients)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                        help="Chunks per batch (default: %(default)s)")
    parser.add_argument("--sleep", type=int, default=SLEEP_BETWEEN_BATCHES,
                        help="Seconds to sleep between batches (default: %(default)s)")
    parser.add_argument("--max-memory", type=float, default=MAX_MEMORY_PERCENT,
                        help="Pause if RAM exceeds this %% (default: %(default)s)")
    parser.add_argument("--verify", action="store_true",
                        help="Check collection status without embedding")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show estimated time and exit without embedding")

    args = parser.parse_args()

    # Determine client list
    if args.client:
        clients = [args.client]
    else:
        clients = discover_clients(PROJECT_ROOT)
        if not clients:
            print("No clients found in clients/ directory.")
            print("Run: make add-client  (or create clients/<name>/repos.yaml)")
            sys.exit(0)

    if args.verify:
        run_all_verify(clients, PROJECT_ROOT)
    else:
        run_all_populate(
            clients=clients,
            batch_size=args.batch_size,
            sleep_secs=args.sleep,
            max_mem_pct=args.max_memory,
            dry_run=args.dry_run,
            project_root=PROJECT_ROOT,
        )


if __name__ == "__main__":
    main()
