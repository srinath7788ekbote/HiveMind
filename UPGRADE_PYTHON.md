# Upgrading to Python 3.12 for ChromaDB Support

HiveMind works best with **Python 3.12 or 3.13**. ChromaDB (the fast vector
search engine) does not support Python 3.14+. Without ChromaDB, HiveMind
falls back to a JSON-based keyword search that is **significantly slower**
on large knowledge bases (95 MB+, 135K+ chunks).

## Symptoms of running on Python 3.14+

- `query_memory` calls take 30+ seconds or hang indefinitely
- `pip install chromadb` fails with build errors
- MCP server prints: `WARNING: ChromaDB not available. Using JSON fallback`

## Migration Steps

1. **Install Python 3.12** from https://www.python.org/downloads/release/python-3120/
   - On the installer, check "Add python.exe to PATH"
   - You can keep Python 3.14 installed side-by-side

2. **Delete the existing virtual environment:**
   ```bat
   rmdir /s /q .venv
   ```

3. **Create a new venv using Python 3.12:**
   ```bat
   py -3.12 -m venv .venv
   ```

4. **Activate the new venv:**
   ```bat
   .venv\Scripts\activate
   ```

5. **Install dependencies (including ChromaDB):**
   ```bat
   pip install -r requirements.txt
   pip install chromadb
   ```

6. **Verify ChromaDB is available:**
   ```bat
   python -c "import chromadb; print('ChromaDB OK:', chromadb.__version__)"
   ```

7. **Re-index to build ChromaDB vectors:**
   ```bat
   python ingest/crawl_repos.py --client dfin
   ```

> **Note:** Your existing `memory/dfin/` JSON chunks still work — re-indexing
> adds ChromaDB on top for faster search. You don't lose anything.

## Verifying the Fix

After upgrading, run:

```bat
python hivemind_mcp/hivemind_server.py --test
```

You should see all 13 tools listed as `[OK]` and **no** ChromaDB warning.

Then time a query:

```bat
python tools/query_memory.py --client dfin --query "config-service hikari" --branch release_26_2 --top_k 5
```

This should complete in **under 2 seconds** with ChromaDB (vs 30+ seconds on
the JSON fallback).
