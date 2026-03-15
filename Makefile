# HiveMind Makefile — Windows (.venv\Scripts\python)
# Run 'make' with no target for help.

.DEFAULT_GOAL := help

CLIENT ?=

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
	@echo.
	@echo  Quick start for new users:
	@echo    1. make setup
	@echo    2. make add-client
	@echo    3. make crawl CLIENT=your-client
	@echo    4. make chromadb CLIENT=your-client
	@echo    5. make server
	@echo.

# ── setup ─────────────────────────────────────────────────
setup:
	py -3.12 -m venv .venv
	.venv\Scripts\pip install --upgrade pip
	.venv\Scripts\pip install -r requirements.txt

# ── crawl-all ─────────────────────────────────────────────
crawl-all:
	@.venv\Scripts\python scripts\crawl_all.py --verbose

# ── crawl ─────────────────────────────────────────────────
crawl:
ifndef CLIENT
	@echo ERROR: CLIENT is required. Usage: make crawl CLIENT=dfin
	@exit /b 1
else
	@.venv\Scripts\python ingest\crawl_repos.py --client $(CLIENT) --config clients\$(CLIENT)\repos.yaml --verbose
endif

# ── sync ──────────────────────────────────────────────────
sync:
ifdef CLIENT
	@.venv\Scripts\python scripts\sync_kb.py --client $(CLIENT) --auto-yes
else
	@.venv\Scripts\python scripts\sync_kb.py --auto-yes
endif

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

.PHONY: help setup crawl-all crawl sync chromadb chromadb-all status test server add-client docs verify recall save-investigation start stop
