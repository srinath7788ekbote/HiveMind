# HiveMind Usage Guide

## Overview

HiveMind is a local-first SRE knowledge assistant that indexes your infrastructure repos (Terraform, Harness pipelines, Helm charts, Kubernetes secrets) into a searchable knowledge base and exposes them through 20 MCP tools, 7 specialist AI agents, and 17 slash-command skills — all inside VS Code. You ask questions in natural language, and HiveMind answers using your actual infrastructure data with file-path citations.

HiveMind uses a dual retrieval system: ChromaDB/BM25 for broad semantic search, and HTI (HiveMind Tree Intelligence) for precise structural navigation of YAML/HCL files.

```
  You paste logs / ask a question
       │
       ▼
  ┌──────────────────┐
  │  Copilot Chat /   │  Routes to specialist agent
  │  Claude Agent     │  (or auto-triggers on incidents)
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  HiveMind MCP    │  20 tools: query, search, trace,
  │  Server           │  diff, impact, graph, HTI, write...
  └────────┬─────────┘
           ▼
  ┌──────────────────┐
  │  Knowledge Base   │  JSON chunks + SQLite graph
  │  + ChromaDB       │  + ChromaDB vectors
  │  + HTI SQLite     │  + Structural skeletons/nodes
  └────────┬─────────┘
           ▼
  Answer with file-path citations from YOUR infra
```

---

## Prerequisites

- **VS Code** with GitHub Copilot extension (Enterprise or Individual with agent mode)
- **Python 3.12** — `py -3.12 --version` (NOT 3.14+; ChromaDB requires < 3.14)
- **Git** in PATH
- **make** (or run commands manually)
- Your infrastructure repos cloned locally on disk

---

## Initial Setup

### 1. Clone HiveMind

```bash
git clone <your-hivemind-repo-url>
cd HiveMind
```

### 2. Create virtual environment and install dependencies

```bash
make setup
```

This creates a `.venv` with Python 3.12 and installs all requirements.

### 3. Add your first client

```bash
make add-client
```

The interactive wizard asks for:
- **Client name** — short identifier (e.g., `dfin`)
- **Display name** — human-readable name
- **Repos** — for each repo:
  - Name (e.g., `Eastwood-terraform`)
  - Local path to the cloned repo on disk
  - Type — auto-detected from file patterns (`.tf`, `pipeline.yaml`, `Chart.yaml`)
  - Platform (e.g., `azure`, `aws`)
  - Branches to index (e.g., `main`, `develop`, `release_26_2`, `release_26_3`)
- Validates that each repo path exists on disk

### 4. Index the client

```bash
make crawl CLIENT=<your-client>
```

This crawls all repos, classifies files, extracts relationships, builds the knowledge base, and automatically indexes HTI. Takes ~2 hours for large codebases.

### 5. Populate ChromaDB (optional but recommended)

```bash
make chromadb CLIENT=<your-client>
```

Populates the ChromaDB vector store for semantic search. Takes ~3 hours. Without this, HiveMind falls back to BM25 keyword search, which is still accurate.

### 6. Set up HTI (structural search)

```bash
make hti-setup CLIENT=<your-client>
```

Sets up HTI (HiveMind Tree Intelligence) for precise structural navigation of YAML/HCL files. This runs migration (creates `hti_skeletons` and `hti_nodes` tables) then indexes all repos. Takes ~5 minutes.

> **Note:** If you ran `make crawl`, HTI indexing already happened automatically. `make hti-setup` is only needed if you skipped the crawl or want to ensure HTI schema is set up.

### 7. Start the MCP server

```bash
make server
```

Keep this running while using HiveMind. Copilot Chat and Claude Agent connect to it automatically.

### 8. VS Code setup

- Open VS Code in the HiveMind project folder
- Verify `.vscode/mcp.json` exists (it should — it's checked into the repo)
- Open Copilot Chat (Ctrl+Alt+I)
- HiveMind tools load automatically via MCP

---

## Using HiveMind with GitHub Copilot Chat

### Starting a session

1. Open VS Code (with HiveMind as the workspace)
2. Make sure `make server` is running
3. Open Copilot Chat (Ctrl+Alt+I)
4. Ensure agent mode is on (click the `@` button)
5. HiveMind tools load automatically via the MCP configuration

### How to ask questions

Just ask naturally. HiveMind will call the right tools and cite sources.

---

**Example 1 — Simple KB query:**

```
You:  What are the resource limits for tagging-service?
```

HiveMind calls `hivemind_query_memory` → returns exact CPU/memory values from the Helm chart with file path citation:

```
📋 Finding: tagging-service has cpu: 500m, memory: 512Mi (request), cpu: 1, memory: 1Gi (limit)
📁 Sources:
  - `charts/tagging-service/values.yaml` [repo: newAd_Artifacts, branch: release_26_3]
```

---

**Example 2 — Incident investigation (paste logs):**

```
You:  [paste CrashLoopBackOff pod logs here]
```

HiveMind **auto-triggers** an investigation without being asked:
1. Extracts service name from pod logs
2. Calls `query_memory` + `impact_analysis`
3. Routes to the investigator agent
4. Returns root cause with KB citations, dependency chain, and recommended fix

---

**Example 3 — Secret flow trace:**

```
You:  How does tagging-service get its database password?
```

HiveMind calls `get_secret_flow` → traces the full chain:

```
Terraform creates secret in Key Vault
  → azurerm_key_vault_secret in layer_5/secrets_tagging_service.tf
  → CSI SecretProviderClass mounts it to the pod
  → Helm values.yaml injects it as DB_PASSWORD env var
```

---

**Example 4 — Pipeline lookup:**

```
You:  Show me the deployment pipeline for newAd services
```

HiveMind calls `get_pipeline` → returns pipeline YAML reference with stages, template refs, service refs, environment bindings, and approval gates.

---

**Example 5 — Impact analysis:**

```
You:  If I change auth-service, what breaks?
```

HiveMind calls `impact_analysis` → returns the dependency tree:

```
Risk Level: HIGH (8 dependents)
Direct: tagging-service, billing-service, notification-service
Transitive: audit-service, reporting-service (via billing-service)
```

---

### Slash commands (Copilot skills)

| Command | When to use | What it does |
|---------|-------------|--------------|
| `/triage` | Paste any logs or error messages | Full incident triage: KB search + observability + root cause + remediation |
| `/k8s` | Pod, node, or Kubernetes issues | Deep K8s investigation: pod lifecycle, container diagnosis, node health |
| `/secrets` | Secret, KeyVault, or credential failures | Full secret chain audit: Terraform → KeyVault → CSI → Pod → App |
| `/postmortem` | After an investigation is complete | Generates structured RCA report with timeline, contributing factors, MTTR |
| `/recall` | "Have we seen this before?" | Searches past saved investigations for similar incidents |
| `/cert-audit` | TLS, certificate, or mTLS failures | TLS/certificate chain investigation: Istio mTLS, cert-manager, KeyVault certs, JVM truststores, ingress TLS |
| `/db` | Database or messaging issues | Database and messaging investigation: connection pools, migrations, deadlocks, replication, message queues |
| `/perf` | Performance degradation or slowness | Performance investigation: latency, throughput, memory leaks, CPU throttling, GC pressure, thread exhaustion |
| `/diff-branches` | Compare branches | Structured diff between Git branches categorized by file type (pipeline/terraform/helm) |
| `/get-entity` | Entity details lookup | Full entity profile: metadata, graph edges, related files |

**How to invoke each:**

```
/triage [paste your error logs here]

/k8s tagging-service-pod-xyz  default

/secrets tagging-service

/postmortem
(run this after you've completed an investigation in the same chat)

/recall tagging-service CrashLoopBackOff

/cert-audit tagging-service
(investigates TLS/cert issues for the service)

/db tagging-service
(investigates database connectivity, pool exhaustion, migration issues)

/perf tagging-service
(investigates latency spikes, memory leaks, CPU throttling)

/diff-branches release_26_2 release_26_3
(compare two branches with categorized file diffs)

/get-entity auth-service
(full entity profile with relationships and file references)
```

---

### Using specific agents

You can invoke agents directly using the `@` syntax:

| Agent | When to use | Example |
|-------|-------------|---------|
| `@hivemind-team-lead` | Full investigation coordinator | `@hivemind-team-lead investigate this incident: [logs]` |
| `@hivemind-investigator` | Direct KB investigation | `@hivemind-investigator what caused the tagging-service crash?` |
| `@hivemind-devops` | Pipeline and Helm questions | `@hivemind-devops Show me the deploy pipeline for client-service` |
| `@hivemind-architect` | Terraform and infra questions | `@hivemind-architect What Terraform layer owns the AKS cluster?` |
| `@hivemind-security` | Secret and identity questions | `@hivemind-security Why is tagging-service failing to mount secrets?` |
| `@hivemind-analyst` | Impact and blast radius questions | `@hivemind-analyst What's the blast radius of changing auth-service?` |
| `@hivemind-planner` | Runbook and plan creation | `@hivemind-planner Create a runbook for upgrading tagging-service` |

---

### Saving and recalling investigations

After completing an investigation:

```
You:  Save this investigation
```

HiveMind saves the root cause, resolution, files cited, and tags to memory.

Next time you see a similar issue:

```
You:  /recall tagging-service CrashLoopBackOff
```

Or:

```
You:  Have we seen CrashLoopBackOff on tagging-service before?
```

HiveMind searches past saved investigations and returns matching root causes and resolutions.

---

## Using HiveMind with Claude Agent in VS Code

### Setup (one time)

1. **Enable Claude Agent** in VS Code settings:
   ```json
   "github.copilot.chat.claudeAgent.enabled": true
   ```
2. **Enable third-party agents** in GitHub Copilot settings (see [GitHub docs on enabling third-party agents](https://docs.github.com/en/copilot/using-github-copilot/using-extensions-to-integrate-external-tools-with-copilot-chat))
3. **Verify CLAUDE.md** exists at the project root (it does — checked into the repo)

### Starting a Claude Agent session

1. Open Chat view (Ctrl+Alt+I)
2. Click New Chat (+)
3. Session Type dropdown → select **"Claude" (local)**
   OR: Session Type → "Cloud" → Partner Agent → "Claude"
4. HiveMind MCP tools load automatically (same `.vscode/mcp.json`)

### Claude Agent slash commands

| Command | What it does |
|---------|-------------|
| `/memory` | View/edit CLAUDE.md (HiveMind persistent context) |
| `/init` | Initialize CLAUDE.md if missing |
| `/agents` | Create and manage HiveMind subagents |
| `/triage` | Same as Copilot — incident triage |
| `/k8s` | Same as Copilot — K8s debug |
| `/secrets` | Same as Copilot — secret audit |
| `/postmortem` | Same as Copilot — explicit postmortem only |
| `/recall` | Same as Copilot — investigation memory |
| `/cert-audit` | Same as Copilot — TLS/certificate investigation |
| `/db` | Same as Copilot — database/messaging investigation |
| `/perf` | Same as Copilot — performance investigation |
| `/diff-branches` | Same as Copilot — structured branch diff |
| `/get-entity` | Same as Copilot — entity profile lookup |

### Parallel subagents (Claude Agent exclusive)

This is the key advantage of Claude Agent over Copilot Chat.

- **Copilot Chat**: agents work one at a time (sequential handoffs)
- **Claude Agent**: agents work simultaneously (parallel subagents)

```
  You paste logs
       │
       ▼
  team-lead spawns IN PARALLEL:
  ┌────────────────────────────────────────────┐
  │  [investigator] → queries KB for root cause │
  │  [security]     → checks secret flow        │
  │  [devops]       → checks Helm/pipeline       │
  │  [analyst]      → checks impact/blast radius  │
  └────────────────────────────────────────────┘
       │
       ▼  All finish simultaneously
  team-lead synthesizes → single unified answer
```

**How to trigger parallel investigation:**

Just paste logs — `team-lead` auto-detects the incident and delegates to specialists in parallel.

Or explicitly:

```
@hivemind-team-lead investigate this incident: [paste logs]
```

### Handoff chains

After an agent responds, handoff buttons appear:

- After investigation → **"Generate Postmortem"** button appears
- After planning → **"Start Implementation"** button appears

Click the handoff button → switches to the target agent with all context pre-filled.

Full handoff chains:

```
Incident → investigator → team-lead → postmortem
Request  → planner → devops (implement)
```

Maximum 3 handoff hops per investigation. Maximum 8 total consultations per task.

### Using agents directly in Claude Agent

Same `@` syntax works:

```
@hivemind-investigator investigate tagging-service CrashLoopBackOff
@hivemind-security audit secret mounts for tagging-service
@hivemind-devops show me the deploy pipeline for client-service
```

---

## All 20 MCP Tools Reference

All tools are exposed via the HiveMind MCP server and callable from both Copilot Chat and Claude Agent.

| Tool | Description | Example use |
|------|-------------|-------------|
| `hivemind_get_active_client` | Get the currently active client name | "Which client am I working with?" |
| `hivemind_get_active_branch` | Get the currently active branch | "Which branch am I on?" |
| `hivemind_query_memory` | Semantic search over indexed KB (Terraform, pipelines, Helm) | "Resource limits for tagging-service" |
| `hivemind_query_graph` | Traverse entity relationship graph (BFS) | "What depends on auth-service?" |
| `hivemind_get_entity` | Look up a specific entity by name | "Get full details of tagging-service" |
| `hivemind_search_files` | Search indexed files by name, type, or repo | "Find all values.yaml files" |
| `hivemind_get_pipeline` | Deep-parse a Harness pipeline YAML | "Deployment pipeline for newAd" |
| `hivemind_get_secret_flow` | Trace secret lifecycle (Key Vault → K8s → Pod) | "How does tagging-service get its DB password?" |
| `hivemind_impact_analysis` | Assess blast radius of a change | "What breaks if auth-service changes?" |
| `hivemind_diff_branches` | Compare two branches of a repository | "Diff release_26_2 vs release_26_3" |
| `hivemind_list_branches` | List indexed branches with tier classification | "What branches are indexed?" |
| `hivemind_check_branch` | Validate a branch is indexed / exists on remote | "Is release_26_4 indexed?" |
| `hivemind_set_client` | Switch active client context | "Switch to client2" |
| `hivemind_write_file` | Write file with branch protection enforcement | "Create a fix on the working branch" |
| `hivemind_read_file` | Read actual file content from a repo | "Show me the full pipeline YAML" |
| `hivemind_propose_edit` | Propose or apply an edit to a file | "Change the replica count to 3" |
| `hivemind_save_investigation` | Save investigation to memory for future recall | "Save this investigation" |
| `hivemind_recall_investigation` | Search past saved investigations | "Have we seen this before?" |
| `hivemind_hti_get_skeleton` | Get YAML/HCL file skeleton for structural navigation | "Show me the structure of the deploy pipeline" |
| `hivemind_hti_fetch_nodes` | Fetch full content at specific node paths | "Get the Deploy stage steps" |

---

## HTI — Structural Navigation (Tools #19 and #20)

HTI (HiveMind Tree Intelligence) is HiveMind's precision retrieval system for navigating YAML and HCL infrastructure files by structure, not by keyword similarity.

### When to use HTI vs query_memory

| Use HTI when... | Use query_memory when... |
|----------------|------------------------|
| "What are the steps in the Deploy stage?" | "Which services use KeyVault?" |
| "What Terraform variables are in prod module?" | "Find all liveness probe configs" |
| "Show the rollback config for presentation-service" | "Which pipelines reference connector X?" |
| "What Helm values override staging vs production?" | "Find anything about nginx" |
| Specific structural element in a known file | Search across all repos |

### How HTI works (what Copilot/Claude does automatically)

When you ask a structural question, Copilot/Claude:

1. Calls `hivemind_hti_get_skeleton` → gets the file's structure (keys + paths)
2. Reasons over the skeleton: "Deploy stage is at `root.pipeline.stages[3]`"
3. Calls `hivemind_hti_fetch_nodes` → gets exact content at that path
4. Answers with complete, path-annotated content

You don't need to invoke HTI explicitly — just ask structural questions.

### Example HTI queries that work well

- "What are all the steps in the Deploy stage of cd_deploy_env?"
- "Show me all approval gates in the presentation-service pipeline"
- "What Terraform variables are defined in Eastwood layer 5?"
- "What resource limits are set for tagging-service in Helm?"
- "Show the versioning stage configuration for newAd pipelines"
- "What environment variables does presentation-service inject?"

### HTI Setup (for new clients)

After crawling a new client, also set up HTI:

```bash
make hti-setup CLIENT=<client>
```

This runs migration (creates `hti_skeletons` and `hti_nodes` tables) then indexes all repos (3,369 files = ~140K nodes for dfin).

### Keeping HTI updated

HTI updates automatically when you run:
- `make sync` → syncs KB and HTI together (incremental, fast)
- `make crawl` → full crawl also re-indexes HTI

HTI uses mtime-based incremental indexing — only re-indexes changed files. A typical daily sync updates HTI in < 30 seconds.

### HTI index status

Check what's indexed:

```bash
make hti-status
make hti-status CLIENT=dfin
```

---

## Daily Workflow

### Morning routine (2 minutes)

```bash
make sync
```

- Runs automatically at 7am daily via Task Scheduler (using `scripts/sync_kb_scheduled.bat`)
- Shows which repos have changes
- Re-indexes only changed files (~2-5 minutes)
- **Automatically updates HTI index** (incremental, < 30 seconds for unchanged files)

### Before investigating an incident

```bash
make status CLIENT=dfin
```

Check that the KB is fresh. If stale:

```bash
make sync CLIENT=dfin
```

### During investigation

1. Open Copilot Chat or Claude Agent session
2. Paste logs or describe the issue
3. HiveMind auto-investigates (incident detection is automatic)
4. If it's a new incident pattern: say **"Save this investigation"**

### New release branch (every 2 weeks)

```bash
make sync
```

Sync detects new branches on remote and asks if you want to add them. Answer `y` to add and index the new branch. Takes ~30 minutes for one new branch.

---

## Keeping the KB Updated

### When to run what

| Situation | Command | KB updated | HTI updated | Time |
|-----------|---------|:----------:|:-----------:|------|
| Daily changes | `make sync` | Yes | Yes (auto) | ~2-5 min |
| New release branch | `make sync` (auto-detects) | Yes | Yes (auto) | ~30 min |
| New repo added | `make add-client` → `make crawl` | Yes | Yes (auto) | ~2 hours |
| Full re-index | `make crawl CLIENT=x` | Yes | Yes (auto) | ~2 hours |
| Full re-index (all clients) | `make crawl-all` | Yes | Yes (auto) | ~2 hours per client |
| Populate ChromaDB | `make chromadb CLIENT=x` | - | - | ~3 hours |
| HTI only | `make hti-index CLIENT=x` | No | Yes | ~5 min |
| Check KB status | `make status` | - | - | instant |
| Check HTI status | `make hti-status` | - | - | instant |

### ChromaDB vs BM25

HiveMind supports two search backends:

- **BM25 (keyword search)** — searches JSON chunk files using keyword matching (~350ms). Always works. This is the default and fallback.
- **ChromaDB (semantic search)** — searches vector embeddings for meaning-based matching (~370ms). Needs one-time population with `make chromadb`.

Both give accurate results. ChromaDB is better at understanding synonyms and related concepts (e.g., searching "memory limits" also finds "resource requests"). BM25 is better for exact matches.

Run `make chromadb CLIENT=x` once to populate ChromaDB from existing JSON data. After that, `make sync` keeps both in sync.

---

## Troubleshooting

### HiveMind tools not appearing in Copilot Chat

1. Check `make server` is running in a terminal
2. Check `.vscode/mcp.json` has the correct Python path
3. Restart VS Code (Copilot re-reads MCP config on startup)

### Wrong results or stale data

1. Run `make sync` to update the KB with latest repo changes
2. Run `make status` to see which branches are indexed and when they were last synced

### ChromaDB slow or empty

1. Run `make chromadb CLIENT=<client>` to populate it
2. HiveMind falls back to BM25 automatically if ChromaDB is empty — no data loss

### New branch not found

1. Run `make sync` — it detects new branches on remote automatically
2. Answer `y` when it asks to add the new branch

### Investigation saved but /recall finds nothing

1. Check `memory/<client>/investigations/` folder exists
2. Run manually: `python tools/recall_investigation.py --client <client> --query "<search terms>"`

### Claude Agent not seeing HiveMind tools

1. Verify `CLAUDE.md` exists at the project root
2. Check VS Code setting: `github.copilot.chat.claudeAgent.enabled = true`
3. Restart VS Code and start a fresh Claude session

### HTI not returning results

1. Run `make hti-status CLIENT=<client>` to check if HTI is indexed
2. If not indexed: `make hti-setup CLIENT=<client>`
3. If indexed but stale: `make hti-index CLIENT=<client> FORCE=true`

### `ModuleNotFoundError`

Run `make setup` to install dependencies into the virtual environment.

### ChromaDB import error

Use Python 3.12 or 3.13 — ChromaDB does not support Python 3.14+.

---

## Quick Reference Card

### 5 Most Common Prompts

```
1. "What are the resource limits for <service>?"
2. [paste error logs]  ← auto-triggers investigation
3. "How does <service> get its database password?"
4. "If I change <service>, what breaks?"
5. "Have we seen this before?" or /recall <service> <error>
```

### All 10 Slash Commands

```
/triage [paste logs]           Full incident investigation
/k8s <pod-name> <namespace>   Deep K8s debugging
/secrets <service-name>        Secret chain audit
/postmortem                    Generate RCA report (after investigation)
/recall <service> <error>      Search past investigations
/cert-audit <service-name>     TLS/certificate chain investigation
/db <service-name>             Database/messaging investigation
/perf <service-name>           Performance degradation investigation
/diff-branches <branch1> <branch2>  Structured branch diff
/get-entity <entity-name>     Full entity profile lookup
```

### All 20 MCP Tools

```
hivemind_get_active_client     Get current client context
hivemind_get_active_branch     Get current branch context
hivemind_query_memory          Semantic search (BM25/ChromaDB)
hivemind_query_graph           Entity relationship graph traversal
hivemind_get_entity            Entity lookup by name
hivemind_search_files          File search by name/type/repo
hivemind_get_pipeline          Harness pipeline deep parse
hivemind_get_secret_flow       Secret lifecycle trace
hivemind_impact_analysis       Blast radius assessment
hivemind_diff_branches         Branch diff comparison
hivemind_list_branches         Branch listing with tiers
hivemind_check_branch          Branch validation
hivemind_set_client            Switch client context
hivemind_write_file            Write file (branch-protected)
hivemind_read_file             Read file content from repo
hivemind_propose_edit          Propose/apply file edits
hivemind_save_investigation    Save investigation to memory
hivemind_recall_investigation  Search past investigations
hivemind_hti_get_skeleton      Get YAML/HCL file skeleton (structural)
hivemind_hti_fetch_nodes       Fetch content at specific node paths
```

### Make Commands Cheat Sheet

```
make setup              First-time setup (venv + deps)
make add-client         Add a new client (interactive wizard)
make crawl CLIENT=x     Index a single client (~2 hours) + HTI
make chromadb CLIENT=x  Populate ChromaDB (~3 hours, optional)
make chromadb-all       Populate ChromaDB for all clients
make server             Start MCP server (keep running)
make start              Start HiveMind background watcher daemon
make stop               Stop HiveMind background watcher daemon
make sync               Daily sync — updates KB + HTI (~5 min)
make status             Check what's indexed (instant)
make test               Run test suite
make verify             Run tests + KB status + ChromaDB + HTI check
make crawl-all          Re-index all clients (slow) + HTI
make recall CLIENT=x QUERY=y  Search past investigations
make hti-setup CLIENT=x Full HTI setup (migrate + index)
make hti-index CLIENT=x Index repos into HTI structural DB
make hti-index          Index all clients into HTI
make hti-status         Show HTI index status
make hti-migrate CLIENT=x Run HTI schema migration
```

### When to Use Copilot Chat vs Claude Agent

| Feature | Copilot Chat | Claude Agent |
|---------|-------------|--------------|
| HiveMind KB access | Yes | Yes |
| All 20 MCP tools | Yes | Yes |
| Slash commands (/triage, /k8s, etc.) | Yes | Yes |
| Sequential agent handoffs | Yes | Yes |
| Parallel subagent investigation | No | Yes |
| Handoff chain buttons | No | Yes |
| Direct file access (read local files) | No | Yes |
| Terminal command execution | No | Yes |
| /memory command (CLAUDE.md) | No | Yes |

**Rule of thumb:** Use Copilot Chat for quick questions. Use Claude Agent for complex incidents that benefit from parallel investigation.
