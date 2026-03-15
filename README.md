# HiveMind — Local-First Multi-Agent SRE Assistant

A local-first SRE knowledge assistant powered by GitHub Copilot Chat and Claude Agent. Index your infrastructure repos (Terraform, Harness, Helm, NewRelic) and query them through 7 specialist AI agents, 16 MCP tools, and 10 slash-command skills — no external APIs, no cloud dependencies, zero data leaving your machine.

Works with any client — multi-tenant architecture discovers and indexes all configured clients automatically.

> **New to HiveMind?** See the complete [Usage Guide](docs/USAGE_GUIDE.md) for detailed setup instructions, example prompts, and daily workflows.

---

## Architecture

```
  Your Repos (Terraform, Harness, Helm, K8s, NewRelic)
       │
       ▼
  ┌─────────────┐
  │  Crawler     │  crawl → classify → extract relationships → embed
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Memory      │  JSON chunks + Entity graph (SQLite) + ChromaDB vectors
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  MCP Server  │  16 tools: query, search, trace, diff, impact, write
  └──────┬──────┘
         ▼
  ┌─────────────────┐
  │  Copilot Chat /  │  7 agents + 10 skills → answers grounded in YOUR infra
  │  Claude Agent    │  (Claude Agent adds parallel subagents + handoffs)
  └─────────────────┘
```

**Key idea:** You ask a question in Copilot Chat or Claude Agent. The Team Lead agent routes it to the right specialist. The specialist queries indexed memory using MCP tools and returns an answer grounded in your actual infrastructure — not generic training data. Claude Agent adds parallel subagent investigation for faster incident resolution.

### Agents

| Agent | Role | Hands off to |
|-------|------|-------------|
| **hivemind-team-lead** | Orchestrator / Router | All specialists |
| **hivemind-devops** | CI/CD, Helm, deployments | Security, Architect |
| **hivemind-architect** | Terraform, IaC layers | Security, DevOps |
| **hivemind-security** | RBAC, secrets, Key Vault | Architect, DevOps |
| **hivemind-investigator** | Root cause analysis | DevOps, Security |
| **hivemind-analyst** | Impact / blast radius | Planner |
| **hivemind-planner** | Runbooks / procedures | DevOps, Architect |

### Skills

| Skill | Trigger | Description |
|-------|---------|-------------|
| incident-triage | `/incident-triage` | Structured incident investigation |
| k8s-debug | `/k8s-debug` | Kubernetes pod/deployment debugging |
| secret-audit | `/secret-audit` | Secret lifecycle audit |
| postmortem | `/postmortem` | Post-incident review generator |
| investigation-memory | `/investigation-memory` | Save/recall past investigations |
| cert-audit | `/cert-audit` | TLS/certificate chain investigation |
| db-debug | `/db` | Database and messaging investigation |
| perf-debug | `/perf` | Performance degradation investigation |
| diff-branches | `/diff-branches` | Structured branch diff by file type |
| get-entity | `/get-entity` | Full entity profile lookup |

### Copilot Chat vs Claude Agent

HiveMind works with both GitHub Copilot Chat and Claude Agent in VS Code. Both have full access to all 16 MCP tools and 7 agents.

| Feature | Copilot Chat | Claude Agent |
|---------|-------------|--------------|
| HiveMind KB access | Yes | Yes |
| All 16 MCP tools | Yes | Yes |
| Sequential agent handoffs | Yes | Yes |
| Parallel subagent investigation | No | Yes |
| Handoff chain buttons | No | Yes |
| /memory command (CLAUDE.md) | No | Yes |
| Direct file read (local) | No | Yes |
| Terminal command execution | No | Yes |

**Claude Agent setup:** Enable `github.copilot.chat.claudeAgent.enabled` in VS Code settings, verify `CLAUDE.md` exists at project root, then start a Claude session from the Chat view. See the [Usage Guide](docs/USAGE_GUIDE.md#using-hivemind-with-claude-agent-in-vs-code) for detailed instructions.

---

## Quick Start

### Prerequisites

- **Python 3.12** — `py -3.12 --version` (NOT 3.14+; ChromaDB requires < 3.14)
- **Git** in PATH
- **GitHub Copilot** (Enterprise or Individual with agent mode)
- Your infrastructure repos cloned locally

### Setup

```bash
git clone <your-hivemind-repo-url>
cd HiveMind
make setup
make add-client
make crawl CLIENT=<your-client>
make chromadb CLIENT=<your-client>
make server
```

Then open VS Code → Copilot Chat → Ask anything about your infrastructure.

---

## MCP Tools

All 16 tools are exposed via the MCP server and callable from both Copilot Chat and Claude Agent.

| Tool | Description |
|------|-------------|
| `query_memory` | Semantic search over indexed infrastructure files |
| `query_graph` | Traverse entity relationship graph (BFS) |
| `get_entity` | Look up a specific entity by name |
| `search_files` | Search indexed files by name, type, or repo |
| `get_pipeline` | Deep-parse a Harness pipeline YAML |
| `get_secret_flow` | Trace secret lifecycle (Key Vault → K8s → pod) |
| `impact_analysis` | Assess blast radius of a change |
| `diff_branches` | Compare two branches of a repository |
| `list_branches` | List indexed branches with tier classification |
| `set_client` | Switch active client context |
| `write_file` | Write file with branch protection enforcement |
| `check_branch` | Pre-flight check: is branch indexed / exists? |
| `save_investigation` | Save investigation to memory for future recall |
| `recall_investigation` | Search past investigations for similar incidents |
| `get_active_client` | Get currently active client name |
| `get_active_branch` | Get currently active branch |

---

## Daily Workflow

```bash
make sync                    # sync all clients (runs at 7am via Task Scheduler)
make sync CLIENT=dfin        # sync one client manually
make status                  # check what's indexed
```

- `make sync` detects changed files and re-indexes only what changed (~5 min)
- New release branch? Sync detects it and asks to add
- Full re-crawl: `make crawl-all` (slow — ~2 hours for large codebases)

---

## Adding a New Client

```bash
make add-client
```

The interactive wizard prompts for:
- Client name and display name
- Repos: name, local path, type, platform, branches
- Auto-detects repo type from file patterns (`.tf`, `pipeline.yaml`, `Chart.yaml`)
- Validates that each repo path exists on disk
- Offers to run initial crawl immediately

---

## Project Structure

```
HiveMind/
├── .github/
│   ├── copilot-instructions.md     # Auto-loaded system prompt
│   ├── agents/                     # 7 Copilot Enterprise agents
│   └── skills/                     # 10 skills (triage, k8s, secrets, postmortem, investigation-memory, cert-audit, db-debug, perf-debug, diff-branches, get-entity)
├── clients/                        # Client configurations (gitignored)
│   ├── _example/repos.yaml         # Template — copy to get started
│   └── <client>/repos.yaml         # Your client config
├── hivemind_mcp/
│   └── hivemind_server.py          # MCP server (16 tools)
├── tools/                          # Python tools (called by MCP server)
│   ├── query_memory.py             #   Semantic search (ChromaDB/BM25)
│   ├── query_graph.py              #   Graph traversal (SQLite)
│   ├── get_entity.py               #   Entity lookup
│   ├── search_files.py             #   File search
│   ├── get_pipeline.py             #   Pipeline parser
│   ├── get_secret_flow.py          #   Secret tracer
│   ├── impact_analysis.py          #   Blast radius
│   ├── diff_branches.py            #   Branch diff
│   ├── list_branches.py            #   Branch listing
│   ├── set_client.py               #   Client context
│   ├── write_file.py               #   File writer (branch-safe)
│   ├── check_branch.py             #   Branch validation
│   ├── save_investigation.py       #   Investigation persistence
│   └── recall_investigation.py     #   Investigation recall
├── ingest/                         # Ingest pipeline
│   ├── crawl_repos.py              #   Main orchestrator
│   ├── classify_files.py           #   File type classification
│   ├── extract_relationships.py    #   Relationship extraction
│   ├── embed_chunks.py             #   Chunk embedding
│   ├── branch_indexer.py           #   Branch tier tracking
│   ├── fast_embed.py               #   ONNX embedding function
│   └── discovery/                  #   Auto-discovery modules
├── scripts/                        # Operational scripts
│   ├── sync_kb.py                  #   Incremental sync (multi-client)
│   ├── populate_chromadb.py        #   ChromaDB population (multi-client)
│   ├── crawl_all.py                #   Crawl all clients
│   ├── populate_all_chromadb.py    #   Populate all clients
│   ├── add_client.py               #   New client wizard
│   └── sync_kb_scheduled.bat       #   Scheduled Task entry point
├── sync/                           # Sync utilities
│   ├── branch_protection.py        #   Branch protection engine
│   ├── incremental_sync.py         #   Incremental re-indexing
│   └── git_utils.py                #   Git operations
├── tests/                          # Test suite (637+ tests)
├── memory/                         # Runtime data (gitignored)
├── Makefile                        # Build targets
├── CLAUDE.md                       # Claude Agent configuration
├── docs/
│   └── USAGE_GUIDE.md              # Complete usage guide
└── requirements.txt
```

---

## Make Targets

| Target | Description |
|--------|-------------|
| `make setup` | Create venv with Python 3.12 and install dependencies |
| `make crawl-all` | Full re-index of all clients (slow) |
| `make crawl CLIENT=xxx` | Index a single client |
| `make sync` | Sync changed files — fast daily update (all clients) |
| `make sync CLIENT=xxx` | Sync changed files — one client |
| `make chromadb` | Populate ChromaDB vector store (all clients) |
| `make chromadb CLIENT=xxx` | Populate ChromaDB — one client |
| `make chromadb-all` | Populate ChromaDB for all discovered clients |
| `make status` | Show sync status for all repos and branches |
| `make test` | Run all 637+ tests |
| `make server` | Start MCP server (Copilot/Claude connects to this) |
| `make start` | Start HiveMind background watcher daemon |
| `make stop` | Stop HiveMind background watcher daemon |
| `make add-client` | Add a new client interactively |
| `make docs` | Open the usage guide in VS Code |
| `make verify` | Run tests + check KB status + verify ChromaDB |
| `make recall CLIENT=x QUERY=y` | Search past investigations |

---

## Performance

| Metric | Value |
|--------|-------|
| Query time (BM25) | ~350ms |
| Query time (ChromaDB) | ~370ms |
| Full crawl | ~2 hours |
| Incremental sync | ~5 minutes |
| Test suite | 637+ tests |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| ChromaDB empty / slow queries | Run `make chromadb CLIENT=<client>` |
| New branch not found | Run `make sync CLIENT=<client>` |
| MCP server not connecting | Check `.vscode/mcp.json` path matches `hivemind_mcp/hivemind_server.py` |
| `ModuleNotFoundError` | Run `make setup` to install dependencies |
| ChromaDB import error | Use Python 3.12 or 3.13 (not 3.14+) |

---

## Requirements

- **Python 3.12 or 3.13** (NOT 3.14+ — ChromaDB requires < 3.14)
- **Git** in PATH
- **VS Code** with GitHub Copilot Chat

Optional (graceful fallbacks exist):
- **ChromaDB** — vector search (fallback: BM25/JSON keyword search)
- **PyYAML** — YAML parsing (fallback: built-in regex parser)

---

## Design Principles

1. **Local-first** — No cloud APIs, no paid services, no telemetry
2. **Copilot + Claude** — GitHub Copilot Chat and Claude Agent are the AI interfaces
3. **Multi-tenant** — Any number of clients, dynamically discovered
4. **Branch-aware** — All queries respect branch context and tier classification
5. **Branch-protected** — Protected branches require working branch + PR
6. **Graceful degradation** — ChromaDB → BM25, PyYAML → regex, Git → file scan
7. **Zero-config** — `make setup` + `make add-client` and you're running
