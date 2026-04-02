# HiveMind Makefile — Windows (.venv\Scripts\python)
# Run 'make' with no target for help.

.DEFAULT_GOAL := help

CLIENT ?=
FORCE ?=
WORKERS ?=

# ── help ──────────────────────────────────────────────────
help:
	@echo.
	@echo  ============================================
	@echo           HIVEMIND - SRE Knowledge Base
	@echo  ============================================
	@echo.
	@echo  Available commands:
	@echo.
	@echo    make setup              First time setup
	@echo    make crawl-all          Index all clients from scratch
	@echo    make crawl CLIENT=xxx   Index single client
	@echo    make sync               Sync all changed files (daily)
	@echo    make sync CLIENT=xxx    Sync single client
	@echo    make sync WORKERS=4     Sync with parallel workers
	@echo    make full-sync           Fetch remotes + sync + ChromaDB + HTI
	@echo    make full-sync CLIENT=xxx  Full sync for one client
	@echo    make bootstrap-state    Seed sync baseline (fix stuck sync)
	@echo    make bootstrap-embed             Seed embed state (run once after full-sync)
	@echo    make bootstrap-embed CLIENT=xxx  Seed embed state for specific client
	@echo    make chromadb           Populate ChromaDB (all clients)
	@echo    make chromadb CLIENT=xxx Populate ChromaDB (one client)
	@echo    make chromadb-all       Populate ChromaDB for all discovered clients
	@echo    make status             Show KB status (all clients)
	@echo    make status CLIENT=xxx  Show KB status (one client)
	@echo    make test               Run test suite
	@echo    make server             Start MCP server
	@echo    make start              Start HiveMind background watcher
	@echo    make stop               Stop HiveMind background watcher
	@echo    make add-client         Add new client (interactive)
	@echo    make docs               Open the usage guide
	@echo    make verify             Run tests + KB status + ChromaDB check
	@echo    make recall             Search past investigations
	@echo    make save-investigation Show how to save investigations
	@echo    make check-freshness    Check branch freshness vs remote
	@echo    make check-freshness CLIENT=xxx  Check freshness for one client
	@echo.
	@echo  HTI (Structural Search):
	@echo.
	@echo    make hti-setup CLIENT=xxx  Full HTI setup for new client
	@echo    make hti-index CLIENT=xxx  Index repos into HTI (structural search)
	@echo    make hti-index             Index all clients into HTI
	@echo    make hti-index WORKERS=4   Index HTI with parallel workers
	@echo    make hti-status            Show HTI index status
	@echo    make hti-status CLIENT=xxx Show HTI index status (one client)
	@echo    make hti-migrate CLIENT=xxx Run HTI schema migration
	@echo.
	@echo  Benchmark:
	@echo.
	@echo    make benchmark             Run v2 benchmark (30 hard questions)
	@echo    make benchmark-v1          Run v1 benchmark (30 original questions)
	@echo    make benchmark-quick       Run one category (A=structural)
	@echo    make benchmark-report      Run v2 + save report to file
	@echo.
	@echo  Quick start for new users:
	@echo    1. make setup
	@echo    2. make add-client
	@echo    3. make crawl CLIENT=your-client
	@echo    4. make chromadb CLIENT=your-client
	@echo    5. make hti-setup CLIENT=your-client
	@echo    6. make server
	@echo.

# ── setup ─────────────────────────────────────────────────
setup:
	py -3.12 -m venv .venv
	.venv\Scripts\pip install --upgrade pip
	.venv\Scripts\pip install -r requirements.txt
	@echo.
	@echo  HTI setup: run 'make hti-setup CLIENT=xxx' for each client after crawling.

# ── crawl-all ─────────────────────────────────────────────
crawl-all:
	@.venv\Scripts\python scripts\crawl_all.py --verbose
	@echo Running HTI indexing for all clients...
ifdef WORKERS
	@.venv\Scripts\python scripts\hti_index_all.py --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\hti_index_all.py
endif

# ── crawl ─────────────────────────────────────────────────
crawl:
ifndef CLIENT
	@echo ERROR: CLIENT is required. Usage: make crawl CLIENT=dfin
	@exit /b 1
else
	@.venv\Scripts\python ingest\crawl_repos.py --client $(CLIENT) --config clients\$(CLIENT)\repos.yaml --verbose
	@echo Running HTI indexing...
	@.venv\Scripts\python hivemind_mcp\hti\indexer.py --client $(CLIENT)
endif

# ── sync ──────────────────────────────────────────────────
# Use WORKERS=N to parallelize repo/branch syncing (default: auto-detect).
sync:
ifdef CLIENT
ifdef WORKERS
	@.venv\Scripts\python scripts\sync_kb.py --client $(CLIENT) --auto-yes --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\sync_kb.py --client $(CLIENT) --auto-yes
endif
	@echo Syncing HTI index...
	@.venv\Scripts\python hivemind_mcp\hti\indexer.py --client $(CLIENT) 2>nul || echo HTI: skipped (not set up for $(CLIENT))
else
ifdef WORKERS
	@.venv\Scripts\python scripts\sync_kb.py --auto-yes --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\sync_kb.py --auto-yes
endif
	@echo Syncing HTI index for all clients...
ifdef WORKERS
	@.venv\Scripts\python scripts\hti_index_all.py --workers $(WORKERS) 2>nul || echo HTI: skipped (run make hti-setup first)
else
	@.venv\Scripts\python scripts\hti_index_all.py 2>nul || echo HTI: skipped (run make hti-setup first)
endif
endif

# ── full-sync ─────────────────────────────────────────────
# Fetches from all remotes, syncs KB, rebuilds ChromaDB, and re-indexes HTI.
# NOTE: After merging feat/rrf-reranker, run make full-sync
# to re-index YAML/HCL files with structural chunk boundaries.
full-sync:
ifdef CLIENT
	@echo.
	@echo ============================================
	@echo  FULL SYNC: $(CLIENT)
	@echo ============================================
	@echo.
	@echo [1/3] Fetching remotes + syncing KB...
ifdef WORKERS
	@.venv\Scripts\python scripts\sync_kb.py --client $(CLIENT) --auto-yes --fetch --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\sync_kb.py --client $(CLIENT) --auto-yes --fetch
endif
	@echo.
	@echo [2/3] Populating ChromaDB...
	@.venv\Scripts\python scripts\populate_chromadb.py --client $(CLIENT)
	@echo.
	@echo [3/3] Indexing HTI...
	@.venv\Scripts\python hivemind_mcp\hti\indexer.py --client $(CLIENT) 2>nul || echo HTI: skipped (not set up for $(CLIENT))
	@echo.
	@echo ============================================
	@echo  FULL SYNC COMPLETE: $(CLIENT)
	@echo ============================================
else
	@echo.
	@echo ============================================
	@echo  FULL SYNC: ALL CLIENTS
	@echo ============================================
	@echo.
	@echo [1/3] Fetching remotes + syncing KB...
ifdef WORKERS
	@.venv\Scripts\python scripts\sync_kb.py --auto-yes --fetch --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\sync_kb.py --auto-yes --fetch
endif
	@echo.
	@echo [2/3] Populating ChromaDB...
	@.venv\Scripts\python scripts\populate_all_chromadb.py
	@echo.
	@echo [3/3] Indexing HTI...
ifdef WORKERS
	@.venv\Scripts\python scripts\hti_index_all.py --workers $(WORKERS) 2>nul || echo HTI: skipped (run make hti-setup first)
else
	@.venv\Scripts\python scripts\hti_index_all.py 2>nul || echo HTI: skipped (run make hti-setup first)
endif
	@echo.
	@echo ============================================
	@echo  FULL SYNC COMPLETE: ALL CLIENTS
	@echo ============================================
endif

# ── bootstrap-state ──────────────────────────────────────
# Seed sync_state.json from current HEAD commits so 'make sync' has a baseline.
# Use this if sync keeps showing all files as changed.
bootstrap-state:
ifdef CLIENT
	@.venv\Scripts\python scripts\sync_kb.py --bootstrap --client $(CLIENT)
else
	@.venv\Scripts\python scripts\sync_kb.py --bootstrap
endif

# ── bootstrap-embed ──────────────────────────────────────
# Seed embed state from existing ChromaDB data so 'make sync' skips unchanged files.
bootstrap-embed:
	@echo Bootstrapping embed state from current ChromaDB data...
ifdef CLIENT
	@.venv\Scripts\python scripts\sync_kb.py --bootstrap-embed --client $(CLIENT)
else
	@.venv\Scripts\python scripts\sync_kb.py --bootstrap-embed
endif
	@echo Done. Future syncs will only re-embed changed files.

# ── chromadb ──────────────────────────────────────────────
chromadb:
ifdef CLIENT
	@.venv\Scripts\python scripts\populate_chromadb.py --client $(CLIENT)
else
	@.venv\Scripts\python scripts\populate_chromadb.py
endif

# ── status ────────────────────────────────────────────────
status:
ifdef CLIENT
	@.venv\Scripts\python scripts\sync_kb.py --status --client $(CLIENT)
else
	@.venv\Scripts\python scripts\sync_kb.py --status
endif

# ── test ──────────────────────────────────────────────────
test:
	@.venv\Scripts\python -m pytest tests\ -v

# ── server ────────────────────────────────────────────────
server:
	@.venv\Scripts\python hivemind_mcp\hivemind_server.py

# ── add-client ────────────────────────────────────────────
add-client:
	@.venv\Scripts\python scripts\add_client.py

# ── docs ─────────────────────────────────────────────────
docs:
	@code USAGE_GUIDE.md

# ── verify ───────────────────────────────────────────────
verify:
	@.venv\Scripts\python -m pytest tests\ -q
	@.venv\Scripts\python scripts\sync_kb.py --status
	@.venv\Scripts\python scripts\populate_chromadb.py --verify
	@echo.
	@echo HTI Status:
	@.venv\Scripts\python -c "import sqlite3; from pathlib import Path; clients=[d.name for d in Path('clients').iterdir() if d.is_dir() and not d.name.startswith('_') and (d/'repos.yaml').exists()]; [print(f'  {c}: {sqlite3.connect(str(Path(f\"memory/{c}/hti.sqlite\"))).execute(\"SELECT COUNT(*) FROM hti_skeletons\").fetchone()[0]:,} skeletons, ' + str(sqlite3.connect(str(Path(f\"memory/{c}/hti.sqlite\"))).execute(\"SELECT COUNT(*) FROM hti_nodes\").fetchone()[0]) + ' nodes') if Path(f'memory/{c}/hti.sqlite').exists() else print(f'  {c}: HTI not indexed (run make hti-setup CLIENT={c})') for c in clients]"

# ── recall ───────────────────────────────────────────────
QUERY ?=
recall:
ifndef CLIENT
	@echo ERROR: CLIENT is required. Usage: make recall CLIENT=dfin QUERY="tagging-service"
	@exit /b 1
else
ifndef QUERY
	@echo ERROR: QUERY is required. Usage: make recall CLIENT=dfin QUERY="tagging-service"
	@exit /b 1
else
	@.venv\Scripts\python tools\recall_investigation.py --client $(CLIENT) --query "$(QUERY)"
endif
endif

# ── save-investigation ───────────────────────────────────
save-investigation:
	@echo.
	@echo  To save an investigation, use Copilot Chat or Claude Agent:
	@echo.
	@echo    "Save this investigation"
	@echo    OR: @hivemind-team-lead save this investigation
	@echo.

# ── chromadb-all ─────────────────────────────────────────
chromadb-all:
	@.venv\Scripts\python scripts\populate_all_chromadb.py

# ── start ────────────────────────────────────────────────
start:
	@start_hivemind.bat

# ── stop ─────────────────────────────────────────────────
stop:
	@stop_hivemind.bat

# ── hti-migrate ──────────────────────────────────────────
hti-migrate:
ifndef CLIENT
	@echo ERROR: CLIENT is required. Usage: make hti-migrate CLIENT=dfin
	@exit /b 1
else
	@.venv\Scripts\python hivemind_mcp\hti\migrate.py --client $(CLIENT)
endif

# ── hti-index ────────────────────────────────────────────
# Use WORKERS=N to index branches in parallel (default: auto-detect).
hti-index:
ifdef CLIENT
ifdef FORCE
	@.venv\Scripts\python hivemind_mcp\hti\indexer.py --client $(CLIENT) --force
else
	@.venv\Scripts\python hivemind_mcp\hti\indexer.py --client $(CLIENT)
endif
else
ifdef WORKERS
	@.venv\Scripts\python scripts\hti_index_all.py --workers $(WORKERS)
else
	@.venv\Scripts\python scripts\hti_index_all.py
endif
endif

# ── hti-status ───────────────────────────────────────────
hti-status:
	@.venv\Scripts\python -c "import sqlite3; from pathlib import Path; client='$(CLIENT)'; clients=[client] if client else [d.name for d in Path('clients').iterdir() if d.is_dir() and not d.name.startswith('_') and (d/'repos.yaml').exists()]; [print(f'{c}: {sqlite3.connect(str(Path(f\"memory/{c}/hti.sqlite\"))).execute(\"SELECT COUNT(*) FROM hti_skeletons\").fetchone()[0]:,} skeletons, ' + str(sqlite3.connect(str(Path(f\"memory/{c}/hti.sqlite\"))).execute(\"SELECT COUNT(*) FROM hti_nodes\").fetchone()[0]) + ' nodes') if Path(f'memory/{c}/hti.sqlite').exists() else print(f'{c}: HTI not indexed (run make hti-migrate hti-index CLIENT={c})') for c in clients]"

# ── hti-setup ────────────────────────────────────────────
hti-setup:
ifndef CLIENT
	@echo ERROR: CLIENT is required. Usage: make hti-setup CLIENT=dfin
	@exit /b 1
else
	@$(MAKE) hti-migrate CLIENT=$(CLIENT)
	@$(MAKE) hti-index CLIENT=$(CLIENT)
endif

# ── benchmark ────────────────────────────────────────────
benchmark:
	@.venv\Scripts\python benchmarks\run_benchmark.py --version v2 --verbose

benchmark-v1:
	@.venv\Scripts\python benchmarks\run_benchmark.py --version v1 --verbose

benchmark-quick:
	@.venv\Scripts\python benchmarks\run_benchmark.py --version v2 --verbose --category A

benchmark-report:
	@.venv\Scripts\python benchmarks\run_benchmark.py --version v2 --verbose --output benchmarks\results.md
	@echo.
	@echo  Report saved to benchmarks\results.md

# ── check-freshness ──────────────────────────────────────
check-freshness:
	@echo Checking branch freshness...
ifdef CLIENT
ifdef REPO
	@.venv\Scripts\python scripts\sync_kb.py --check-freshness --client $(CLIENT) --repo $(REPO)
else
	@.venv\Scripts\python scripts\sync_kb.py --check-freshness --client $(CLIENT)
endif
else
	@.venv\Scripts\python scripts\sync_kb.py --check-freshness
endif

.PHONY: help setup crawl-all crawl sync full-sync bootstrap-embed chromadb chromadb-all status test server add-client docs verify recall save-investigation start stop hti-migrate hti-index hti-status hti-setup benchmark benchmark-v1 benchmark-quick benchmark-report check-freshness
