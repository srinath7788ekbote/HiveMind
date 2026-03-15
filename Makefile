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
	@echo    make status             Show KB status (all clients)
	@echo    make status CLIENT=xxx  Show KB status (one client)
	@echo    make test               Run test suite
	@echo    make server             Start MCP server
	@echo    make add-client         Add new client (interactive)
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

.PHONY: help setup crawl-all crawl sync chromadb status test server add-client
