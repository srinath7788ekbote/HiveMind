# HiveMind — Local SRE Assistant

A local-first SRE knowledge assistant powered by GitHub Copilot Chat. Index your infrastructure repos (Terraform, Harness, Helm) and query them through specialist AI agents — no external APIs, no cloud dependencies.

---

## How It Works

HiveMind sits between your repos and GitHub Copilot. It ingests your infrastructure code, builds a knowledge graph, and gives Copilot the context it needs to answer real questions about **your** environment.

```
  Your Repos (Terraform, Harness, Helm, K8s)
       │
       ▼
  ┌─────────────┐
  │  Ingest      │  crawl → classify → extract relationships → embed
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Memory      │  Entity graph (SQLite) + vector chunks (ChromaDB/JSON)
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Tools       │  10 Python tools: query, search, trace, diff, impact
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  Agents      │  7 specialist agents (Team Lead, DevOps, Architect, ...)
  └──────┬──────┘
         ▼
  ┌─────────────┐
  │  VS Code     │  @hivemind chat participant + Copilot Enterprise agents
  └─────────────┘
```

**Key idea:** You ask a question in Copilot Chat. The Team Lead agent routes it to the right specialist. The specialist queries indexe memory using Python tools and returns an answer grounded in your actual infrastructure — not generic training data.

## Requirements

- **Python 3.10+** (Windows)
- **Node.js 18+** (for VS Code extension)
- **VS Code** with GitHub Copilot Chat
- **Git** in PATH

Optional (graceful fallbacks exist):
- **PyYAML** — better YAML parsing (fallback: regex parser)
- **ChromaDB** — vector search (fallback: JSON keyword search)

## Quick Start

### 1. Clone and Setup

```bash
git clone <your-hivemind-repo-url>
cd HiveMind
setup.bat
```

This creates a Python venv, installs dependencies, and builds the VS Code extension.

### 2. Configure Your Client

Copy the included example template and edit it:

```bat
mkdir clients\acme
copy clients\_example\repos.yaml clients\acme\repos.yaml
echo acme > memory\active_client.txt
```

Then edit `clients/acme/repos.yaml` with your actual repos:

```yaml
client_name: acme
display_name: "Acme Corp"

repos:
  - name: acme-harness-pipelines
    path: "C:\\path\\to\\acme-harness-pipelines"
    type: cicd
    platform: harness
    branches:
      - main
      - release_26_3
    description: "Harness CI/CD pipeline definitions"

  - name: acme-terraform
    path: "C:\\path\\to\\acme-terraform"
    type: infrastructure
    platform: terraform
    branches:
      - main
    description: "Terraform infrastructure layers"

  - name: acme-helm-charts
    path: "C:\\path\\to\\acme-helm-charts"
    type: mixed
    platform: helm
    branches:
      - main
    description: "Helm charts and deployment artifacts"

default_branch: main

sync:
  interval_seconds: 300
  watch_enabled: true
  auto_ingest: true

discovery:
  detect_naming_conventions: true
  detect_secret_patterns: true
  min_confidence: 0.7
```

> **Note:** Repos must be cloned locally. HiveMind reads from disk — it doesn't clone for you.

### 3. Install the VS Code Extension

```bat
install_extension.bat
```

### 4. Start HiveMind

```bat
start_hivemind.bat
```

This runs the initial ingest (crawl, classify, extract, embed) and starts a background watcher that re-indexes on changes.

### 5. Ask Questions

Open Copilot Chat in VS Code:

```
@hivemind What pipelines deploy audit-service?
@hivemind /impact deploy_audit.yaml
@hivemind /secrets my-service-db-connection
@hivemind /pipeline deploy_my_service.yaml
@hivemind /status
@hivemind /diff develop release_26_3
@hivemind /branches
```

Or use the **agent dropdown** (Copilot Enterprise) to talk directly to a specialist:

| Agent | Use for |
|-------|---------|
| **hivemind-team-lead** | General questions — auto-routes to specialists |
| **hivemind-devops** | Pipelines, Helm, deployments, rollouts |
| **hivemind-architect** | Terraform, infra layers, resource naming |
| **hivemind-security** | Secrets, RBAC, managed identities, Key Vault |
| **hivemind-investigator** | Root cause analysis, incident tracing |
| **hivemind-analyst** | Impact analysis, blast radius, change risk |
| **hivemind-planner** | Runbooks, migration plans, step-by-step procedures |

Agents hand off to each other automatically when cross-domain expertise is needed.

## Slash Commands

| Command     | Description                          |
|-------------|--------------------------------------|
| `/ingest`   | Re-index all repos                   |
| `/status`   | Show HiveMind status                 |
| `/switch`   | Switch active client context         |
| `/impact`   | Run blast radius analysis            |
| `/secrets`  | Trace secret lifecycle               |
| `/pipeline` | Deep-parse a pipeline YAML           |
| `/diff`     | Compare changes between two branches |
| `/branches` | List indexed branches with tiers     |

## Agent Roster

Agents are defined in `.github/agents/*.agent.md` and auto-detected by GitHub Copilot Enterprise.

| Agent                 | Role                    | Hands off to          |
|-----------------------|-------------------------|-----------------------|
| hivemind-team-lead    | Orchestrator / Router   | All specialist agents |
| hivemind-devops       | CI/CD Specialist        | Security, Architect, Investigator |
| hivemind-architect    | IaC Specialist          | Security, DevOps      |
| hivemind-security     | RBAC / Secrets          | Architect, DevOps     |
| hivemind-investigator | Root Cause Analysis     | DevOps, Security, Architect |
| hivemind-analyst      | Impact / Blast Radius   | Planner               |
| hivemind-planner      | Runbooks / Procedures   | DevOps, Architect, Security |

## Branch Protection

HiveMind enforces branch protection rules to prevent direct modifications to critical branches — in client repos AND in HiveMind itself.

### Protected Branches

| Pattern | Tier | Direct Edit |
|---------|------|-------------|
| `main` / `master` | production | **BLOCKED** |
| `develop` / `development` | integration | **BLOCKED** |
| `release_*` / `release/*` | release | **BLOCKED** |
| `hotfix_*` / `hotfix/*` | hotfix | **BLOCKED** |
| `feature/*` / `feat/*` / `fix/*` | working | Allowed |
| `hivemind/*` | working (auto) | Allowed |
| Any other branch | unclassified | Allowed |

### Required Workflow

When targeting a protected branch:

1. **Create** a working branch (e.g., `hivemind/main-fix-config`)
2. **Make** all changes on the working branch
3. **Create** a Pull Request to merge back

### Enforcement Layers

- **Copilot instructions** (`copilot-instructions.md`) — blocks MCP GitHub tools from writing to protected branches
- **Agent rules** — all 7 agents include branch protection directives
- **Python API** (`sync/branch_protection.py`) — programmatic validation for scripts and tools

```python
from sync.branch_protection import BranchProtection

bp = BranchProtection()
bp.is_protected("main")           # True
bp.is_protected("feat/my-work")   # False

# Auto-redirect: creates working branch if target is protected
branch, redirected = bp.get_safe_branch_for_edit("/path/to/repo", "main", "fix-config")
# branch = "hivemind/main-fix-config", redirected = True
```

## Directory Structure

```
HiveMind/
├── .github/
│   ├── copilot-instructions.md      # Auto-loaded system prompt
│   ├── agents/                       # Copilot Enterprise agents
│   │   ├── hivemind-team-lead.agent.md
│   │   ├── hivemind-devops.agent.md
│   │   ├── hivemind-architect.agent.md
│   │   ├── hivemind-security.agent.md
│   │   ├── hivemind-investigator.agent.md
│   │   ├── hivemind-analyst.agent.md
│   │   └── hivemind-planner.agent.md
│   └── skills/                       # On-demand tool skills
│       ├── query-memory/SKILL.md
│       ├── query-graph/SKILL.md
│       ├── get-entity/SKILL.md
│       ├── search-files/SKILL.md
│       ├── get-pipeline/SKILL.md
│       ├── get-secret-flow/SKILL.md
│       ├── impact-analysis/SKILL.md
│       ├── diff-branches/SKILL.md
│       └── list-branches/SKILL.md
├── clients/                          # Client configurations
│   ├── _example/                     #   Tracked template (copy this)
│   │   └── repos.yaml                #   Example client config
│   └── <your-client>/                #   Your actual client (gitignored)
│       └── repos.yaml
├── tools/                            # Python tools (invoked by agents)
│   ├── query_memory.py               #   Semantic search (ChromaDB/JSON)
│   ├── query_graph.py                #   BFS graph traversal (SQLite)
│   ├── get_entity.py                 #   Entity detail lookup
│   ├── search_files.py               #   File pattern search
│   ├── get_pipeline.py               #   Pipeline YAML deep parser
│   ├── get_secret_flow.py            #   Secret lifecycle tracer
│   ├── impact_analysis.py            #   Blast radius assessment
│   ├── diff_branches.py              #   Branch diff comparison
│   ├── list_branches.py              #   Branch listing with tiers
│   └── set_client.py                 #   Client context switcher
├── ingest/                           # Ingest pipeline
│   ├── crawl_repos.py                #   Main orchestrator
│   ├── classify_files.py             #   File type classification
│   ├── extract_relationships.py      #   Entity relationship extraction
│   ├── branch_indexer.py             #   Branch tier tracking
│   ├── embed_chunks.py               #   Chunk embedding
│   └── discovery/                    #   Auto-discovery modules
│       ├── discover_services.py
│       ├── discover_environments.py
│       ├── discover_pipelines.py
│       ├── discover_infra_layers.py
│       ├── discover_secrets.py
│       ├── discover_naming.py
│       ├── discover_repo_type.py
│       └── build_profile.py
├── sync/                             # Background sync & safety
│   ├── git_utils.py                  #   Git operations
│   ├── branch_protection.py          #   Branch protection engine
│   ├── incremental_sync.py           #   Incremental re-indexing
│   └── watch_repos.py                #   Background watcher daemon
├── tests/                            # Test suite (unittest)
│   ├── conftest.py
│   ├── test_branch_protection.py
│   ├── test_branch_awareness.py
│   ├── test_query_memory.py
│   ├── test_query_graph.py
│   ├── test_get_entity.py
│   ├── test_get_pipeline.py
│   ├── test_search_files.py
│   ├── test_impact_analysis.py
│   ├── test_secret_flow.py
│   ├── test_diff_branches.py
│   ├── test_list_branches.py
│   ├── test_set_client.py
│   ├── test_discovery.py
│   ├── test_classify.py
│   ├── test_relationships.py
│   ├── test_agent_files.py
│   ├── test_full_ingest.py
│   └── fixtures/                     #   Fake repos for testing
├── vscode-extension/                 # VS Code extension
│   ├── package.json
│   ├── tsconfig.json
│   └── src/extension.ts
├── memory/                           # Generated at runtime (gitignored)
│   └── README.md                     #   Explains runtime data structure
├── setup.bat                         # One-time setup
├── install_extension.bat             # Package & install extension
├── start_hivemind.bat                # Start background watcher
├── stop_hivemind.bat                 # Stop background watcher
├── run_all_tests.bat                 # Test runner
├── run_all_tests.py                  # Test runner (Python)
├── requirements.txt
└── .gitignore
```

## Running Tests

```bat
run_all_tests.bat              # All tests
run_all_tests.bat --verbose    # Verbose output
```

Or directly:

```bash
python run_all_tests.py
python -m unittest tests.test_branch_protection -v   # Single test module
```

## Design Principles

1. **Local-first** — No cloud APIs, no paid services, no telemetry
2. **Copilot-only AI** — GitHub Copilot Chat is the sole LLM; no OpenAI keys needed
3. **Native multi-agent** — Specialist agents via Copilot Enterprise `.agent.md` with native handoffs
4. **Branch-aware** — All queries respect branch context and tier classification
5. **Branch-protected** — Protected branches require working branch + PR; no direct edits
6. **Graceful degradation** — ChromaDB → JSON, PyYAML → regex, Git → file scan
7. **Zero-config** — `setup.bat` + `start_hivemind.bat` and you're running

## Contributing

1. **Create a working branch** from `main`:
   ```bash
   git checkout -b feature/your-change main
   ```
2. **Make your changes** — follow existing code patterns and naming conventions
3. **Add tests** — every new module should have a corresponding `test_*.py`
4. **Run the test suite**:
   ```bash
   python run_all_tests.py
   ```
5. **Commit and push** your working branch
6. **Open a Pull Request** to `main` with a clear description

### Guidelines

- Python tools go in `tools/`, ingest modules in `ingest/`, sync utilities in `sync/`
- Agent definitions go in `.github/agents/*.agent.md`
- Skill definitions go in `.github/skills/*/SKILL.md`
- Tests use `unittest` (no pytest dependency) — see `tests/conftest.py` for shared fixtures
- Never commit client data (`clients/`, `memory/`) — these are gitignored
- **Never push directly to `main`, `develop`, or `release_*`** — use a working branch

## Roadmap

- [ ] **Multi-platform support** — Linux/macOS shell scripts alongside `.bat`
- [ ] **GitHub Actions integration** — CI pipeline for automated testing
- [ ] **PR-aware indexing** — auto-index open PRs and compare against base branch
- [ ] **Incident correlation** — link alerts/incidents to infrastructure changes
- [ ] **Cost analysis agent** — new specialist agent for Azure cost optimization
- [ ] **Web dashboard** — lightweight status page for indexed repos and branch health
- [ ] **Multi-client switching** — seamless hot-switching between client contexts

## Stopping HiveMind

```bat
stop_hivemind.bat
```
