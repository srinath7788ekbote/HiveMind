# HiveMind — Local SRE Assistant

A local-first SRE assistant that uses GitHub Copilot Chat to answer questions about your infrastructure, pipelines, secrets, and services. No external AI APIs — the only AI is GitHub Copilot, already running in your VS Code.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  VS Code — GitHub Copilot Chat                        │
│  @hivemind participant + native multi-agent            │
│    ├── slash commands (/ingest, /status, /impact ...) │
│    ├── agent dropdown (Team Lead, DevOps, Architect..)│
│    └── copilot-instructions.md (auto-loaded context)  │
└───────────────┬──────────────────────────────────────┘
                │ Native Copilot Enterprise agents
┌───────────────▼──────────────────────────────────────┐
│  .github/agents/*.agent.md (7 specialist agents)      │
│    hivemind-team-lead -> devops, architect, security, │
│                          investigator, analyst, planner│
│    YAML frontmatter: name, tools, handoffs             │
│    Native handoffs (no custom AgentBus needed)          │
└───────────────┬──────────────────────────────────────┘
                │ Agents invoke skills
┌───────────────▼──────────────────────────────────────┐
│  .github/skills/*/SKILL.md (9 tool skills)            │
│    query-memory, query-graph, get-entity, search-files│
│    get-pipeline, get-secret-flow, impact-analysis     │
│    diff-branches, list-branches                        │
└───────────────┬──────────────────────────────────────┘
                │ child_process (Python)
┌───────────────▼──────────────────────────────────────┐
│  Tools                                                │
│    query_memory.py — semantic search (ChromaDB/JSON)   │
│    query_graph.py  — BFS graph traversal (SQLite)      │
│    get_entity.py   — entity lookup                     │
│    search_files.py — file search                       │
│    get_pipeline.py — deep pipeline YAML parser          │
│    get_secret_flow.py — secret lifecycle tracer         │
│    impact_analysis.py — blast radius assessment         │
│    diff_branches.py — branch comparison                 │
│    list_branches.py — branch listing                    │
│    set_client.py   — client context switcher            │
└───────────────┬──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│  Ingest Pipeline                                      │
│    crawl_repos -> classify_files -> extract_relations  │
│    -> embed_chunks -> branch_indexer                   │
│    discovery/ (services, environments, pipelines,      │
│               infra_layers, secrets, naming, profiles)  │
└───────────────┬──────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────┐
│  Memory                                               │
│    memory/graph.db          — SQLite entity graph       │
│    memory/chunks/           — ChromaDB or JSON chunks   │
│    memory/entities.json     — entity catalog             │
│    memory/branch_index.json — branch tier tracking       │
└──────────────────────────────────────────────────────┘
```

## Requirements

- **Python 3.10+** (Windows native)
- **Node.js 18+** (for VS Code extension)
- **VS Code** with GitHub Copilot Chat
- **Git** in PATH

Optional:
- **PyYAML** — better YAML parsing (fallback: regex parser)
- **ChromaDB** — vector search (fallback: JSON keyword search)

## Quick Start

### 1. Setup

```bat
setup.bat
```

This installs Python and Node.js dependencies, compiles the extension, and creates the memory directory.

### 2. Configure Client

Edit `clients/dfin/repos.yaml` with your repos:

```yaml
client: dfin
repos:
  - name: my-harness-pipelines
    url: https://github.com/org/my-harness-pipelines.git
    type: harness
  - name: my-terraform
    url: https://github.com/org/my-terraform.git
    type: terraform
  - name: my-helm
    url: https://github.com/org/my-helm.git
    type: helm
```

### 3. Install Extension

```bat
install_extension.bat
```

### 4. Start Background Watcher

```bat
start_hivemind.bat
```

This runs the initial ingest and starts the file watcher daemon.

### 5. Use in VS Code

Open Copilot Chat and use any of these methods:

**Quick commands via @hivemind:**

```
@hivemind What pipelines deploy audit-service?
@hivemind /impact deploy_audit.yaml
@hivemind /secrets automation-dev-dbauditservice
@hivemind /pipeline deploy_audit.yaml
@hivemind /status
@hivemind /diff develop release_26_1
@hivemind /branches
```

**Native agent dropdown (Copilot Enterprise):**

Click the agent dropdown in Copilot Chat and select a specialist:

| Agent | When to use |
|-------|-------------|
| **hivemind-team-lead** | General questions — routes to specialists |
| **hivemind-devops** | Pipeline, Helm, deployment questions |
| **hivemind-architect** | Terraform, infrastructure, naming |
| **hivemind-security** | Secrets, RBAC, managed identities |
| **hivemind-investigator** | Root cause analysis, incidents |
| **hivemind-analyst** | Impact analysis, blast radius |
| **hivemind-planner** | Runbooks, migration plans |

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

| Agent                 | Role                    | Handoffs to           |
|-----------------------|-------------------------|-----------------------|
| hivemind-team-lead    | Orchestrator / Router   | All specialist agents |
| hivemind-devops       | CI/CD Specialist        | Security, Architect, Investigator |
| hivemind-architect    | IaC Specialist          | Security, DevOps      |
| hivemind-security     | RBAC / Secrets          | Architect, DevOps     |
| hivemind-investigator | Root Cause Analysis     | DevOps, Security, Architect |
| hivemind-analyst      | Impact / Blast Radius   | Planner               |
| hivemind-planner      | Runbooks / Procedures   | DevOps, Architect, Security |

## Directory Structure

```
HiveMind/
├── .github/
│   ├── copilot-instructions.md     # Auto-loaded system prompt
│   ├── agents/                      # Native Copilot Enterprise agents
│   │   ├── hivemind-team-lead.agent.md
│   │   ├── hivemind-devops.agent.md
│   │   ├── hivemind-architect.agent.md
│   │   ├── hivemind-security.agent.md
│   │   ├── hivemind-investigator.agent.md
│   │   ├── hivemind-analyst.agent.md
│   │   └── hivemind-planner.agent.md
│   └── skills/                      # On-demand tool skills
│       ├── query-memory/SKILL.md
│       ├── query-graph/SKILL.md
│       ├── get-entity/SKILL.md
│       ├── search-files/SKILL.md
│       ├── get-pipeline/SKILL.md
│       ├── get-secret-flow/SKILL.md
│       ├── impact-analysis/SKILL.md
│       ├── diff-branches/SKILL.md
│       └── list-branches/SKILL.md
├── clients/                        # Client configurations
│   └── dfin/
│       └── repos.yaml
├── tools/                          # Python tools
│   ├── query_memory.py
│   ├── query_graph.py
│   ├── get_entity.py
│   ├── search_files.py
│   ├── get_pipeline.py
│   ├── get_secret_flow.py
│   ├── impact_analysis.py
│   ├── diff_branches.py
│   ├── list_branches.py
│   └── set_client.py
├── ingest/                         # Ingest pipeline
│   ├── crawl_repos.py
│   ├── classify_files.py
│   ├── extract_relationships.py
│   ├── branch_indexer.py
│   ├── embed_chunks.py
│   └── discovery/
│       ├── __init__.py
│       ├── discover_repo_type.py
│       ├── discover_services.py
│       ├── discover_environments.py
│       ├── discover_pipelines.py
│       ├── discover_infra_layers.py
│       ├── discover_secrets.py
│       ├── discover_naming.py
│       └── build_profile.py
├── sync/                           # Background sync
│   ├── git_utils.py
│   ├── incremental_sync.py
│   └── watch_repos.py
├── tests/                          # Test suite
│   ├── conftest.py
│   ├── test_discovery.py
│   ├── test_classify.py
│   ├── test_relationships.py
│   ├── test_query_memory.py
│   ├── test_query_graph.py
│   ├── test_impact_analysis.py
│   ├── test_secret_flow.py
│   ├── test_agent_files.py
│   ├── test_full_ingest.py
│   ├── test_branch_awareness.py
│   └── fixtures/
│       ├── fake_harness_repo/
│       ├── fake_terraform_repo/
│       └── fake_helm_repo/
├── vscode-extension/               # VS Code extension
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       └── extension.ts
├── memory/                         # Generated at runtime
│   ├── graph.db
│   ├── chunks/
│   ├── entities.json
│   └── branch_index.json
├── run_all_tests.py                # Test runner
├── run_all_tests.bat               # Test runner (Windows)
├── setup.bat                       # One-time setup
├── install_extension.bat           # Package & install extension
├── start_hivemind.bat              # Start background watcher
├── stop_hivemind.bat               # Stop background watcher
├── README.md                       # This file
└── .gitignore
```

## Running Tests

```bat
run_all_tests.bat              # All tests
run_all_tests.bat --unit       # Unit tests only
run_all_tests.bat --integration # Integration tests only
run_all_tests.bat --verbose    # Verbose output
```

Or directly:

```
python run_all_tests.py
```

## Design Principles

1. **Local-first** — No cloud APIs, no paid services, no telemetry
2. **Copilot-only AI** — GitHub Copilot Chat is the sole LLM
3. **Native multi-agent** — Specialist agents via Copilot Enterprise `.agent.md` files with native handoffs
4. **Branch-aware** — All queries respect branch context and tier classification
5. **Graceful degradation** — ChromaDB -> JSON, PyYAML -> regex, Git -> file scan
6. **Zero-config** — Works with `setup.bat` and `start_hivemind.bat`

## Stopping HiveMind

```bat
stop_hivemind.bat
```

This kills the background watcher process via its PID file.
