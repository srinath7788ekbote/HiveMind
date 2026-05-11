# CLAUDE.md — Claude Agent Configuration for HiveMind

HiveMind is a local-first SRE knowledge assistant that indexes infrastructure repos (Terraform, Harness pipelines, Helm charts, Kubernetes secrets, Spring Cloud Config settings) into a ChromaDB-backed knowledge base, then exposes 21 MCP tools + 25 Hawkeye pipeline observability tools + 24 Sherlock observability tools (70 total) for semantic search, dependency graph traversal, impact analysis, secret lifecycle tracing, config lineage tracking, live pipeline diagnosis, live observability investigation, and incident investigation across multi-repo, multi-branch client environments.

### Retrieval Pipeline

`query_memory` uses a 3-stage hybrid retrieval pipeline:
1. **ChromaDB** semantic search (top-20) + **BM25** keyword search (top-20)
2. **Reciprocal Rank Fusion** (RRF, k=60) merges both result sets
3. **FlashRank** cross-encoder (ms-marco-MiniLM-L-12-v2, ONNX, CPU-only) reranks fused results to return top-N

Result fields: `rrf_score` (fusion confidence), `flashrank_score` (cross-encoder relevance — most important), `retrieval_method` (`hybrid_rrf_reranked` or `hybrid_rrf_no_rerank`).

### Structural Chunking

YAML and HCL files are chunked by structural boundaries via `ingest/chunkers/structural_chunker.py`:
- `.tf`/`.tfvars` → one chunk per resource/variable block
- Harness pipeline YAML → one chunk per pipeline stage
- `values.yaml` → one chunk per top-level service section
- Other YAML → one chunk per top-level key
- All other files → fixed-size chunking (fallback)

Dependency: `flashrank>=0.2.9` (lazy-loaded singleton, ~50MB model downloaded on first use).

***

## Claude Agent Capabilities

Claude Agent has capabilities beyond Copilot Chat. Use them.

### Direct File Access

Read local files to get runtime state without MCP tool calls:

* `memory/active_client.txt` — current client context
* `memory/active_branch.txt` — current branch context
* `memory/clients/{client}/discovered_profile.yaml` — auto-discovered architecture (services, environments, Terraform layers, naming conventions, secret patterns)
* `memory/sync_state.json` — last sync timestamps per repo/branch
* `clients/{client}/repos.yaml` — repo configuration for each client

### Safe Terminal Commands

Run these freely — they are read-only or non-destructive:

```
python scripts/sync_kb.py --status
python scripts/sync_kb.py --client <client> --auto-yes --workers 4
python tools/query_memory.py --client <client> --query <query>
python -m pytest tests/ -q
python scripts/populate_chromadb.py --verify
python hivemind_mcp/hivemind_server.py --test
python scripts/hti_index_all.py --workers 4
```

### Unsafe Commands (require explicit user approval)

Do NOT run these without asking the user first:

```
python ingest/crawl_repos.py          # Takes 2+ hours, re-indexes all repos
python scripts/populate_chromadb.py   # Takes 2+ hours, rebuilds vector store
git push                              # User must push manually
git commit                            # User reviews changes first
```

***

## Subagent Orchestration

### When to Use Subagents

| Scenario                                      | Action                           |
| --------------------------------------------- | -------------------------------- |
| Simple KB lookup ("where is X defined?")      | Handle inline, no subagents      |
| Single-domain question (one agent can answer) | Handle inline, no subagents      |
| Incident investigation (multi-domain)         | Fire parallel data lanes + spawn subagents |
| Multi-repo or multi-service analysis          | Spawn parallel subagents         |
| Impact analysis + runbook generation          | Sequential: analyst then planner |

### Parallel Adaptive Investigation Pattern

When an incident is detected or a complex multi-domain question arrives:

**Phase 1 — Data Lanes (fire in parallel based on intent):**
```
KB Lane (ALWAYS)       → query_memory + get_entity + impact_analysis
Sherlock Lane (live)   → connect_account → golden_signals + k8s_health + search_logs
Hawkeye Lane (deploy)  → diagnose + get_failure_pattern
```

**Phase 2 — Agent Analysis (using data lane results):**
```
hivemind-investigator  → cross-reference all lane results (root cause)
hivemind-security      → get_secret_flow (if secrets/credentials involved)
hivemind-devops        → pipeline + Helm analysis + Hawkeye correlation
hivemind-architect     → Terraform/infra analysis (if infra involved)
```

**Phase 3 — Synthesis:**
The team-lead agent synthesizes all parallel results into a single response with:

* Cross-referenced findings from KB + Sherlock + Hawkeye
* Consolidated findings from each specialist agent
* Merged source citations table
* Single confidence rating (lowest of all agents)
* Recommended fix with specific file paths

### Agent Roster

| Agent                   | Specialty                                    | Subagent Role                     |
| ----------------------- | -------------------------------------------- | --------------------------------- |
| `hivemind-team-lead`    | Orchestrator, router, synthesizer            | Spawns and coordinates all others |
| `hivemind-investigator` | Root cause analysis, cross-domain tracing    | Worker: incident investigation    |
| `hivemind-devops`       | Pipelines, Helm, CI/CD, deployments          | Worker: pipeline/deploy analysis  |
| `hivemind-architect`    | Terraform, IaC, infra layers, resource deps  | Worker: infrastructure analysis   |
| `hivemind-security`     | RBAC, managed identities, Key Vault, secrets | Worker: security analysis         |
| `hivemind-analyst`      | Impact analysis, blast radius, change risk   | Worker: risk assessment           |
| `hivemind-planner`      | Runbooks, migration plans, procedures        | Worker: runbook generation        |

### Handoff Chains

Supported handoff paths between agents:

```
team-lead ──→ investigator ──→ devops/security/architect ──→ team-lead (synthesize)
team-lead ──→ analyst ──→ planner ──→ devops (implement)
investigator ──→ team-lead (root cause found → generate postmortem)
planner ──→ devops (plan ready → start implementation)
```

Maximum 3 handoff hops per investigation. Maximum 8 total consultations per task.

### Nested Subagent Support (VS Code 1.113+)

With `chat.subagents.allowInvocationsFromSubagents: true` in
.vscode/settings.json, specialists can invoke other specialists
directly without routing through team-lead. Each specialist's
agent.md frontmatter defines an allowlist of agents it can invoke.
Subagents get isolated context and return summary only.

Direct delegation paths:
- investigator → security, devops, architect
- devops → architect, security
- architect → security, devops
- security → architect
- analyst → planner
- planner → devops

No specialist can invoke team-lead (prevents upward recursion).
The 3-hop maximum counts total depth including nested calls.

### CrewAI-Inspired Coordination Model

Agents now use **phased parallel execution** with a **shared investigation registry**:

* **Semantic Intent Classification**: Team-lead classifies user intent semantically (INCIDENT, STRUCTURAL, DEPENDENCY, DIFF, SECRET\_FLOW, PLANNING, GENERAL) and routes accordingly. No keyword matching — reads the full message context.
* **Phased Execution**: Phase 1 (raw data gathering, parallel) → Phase 2 (specialized analysis using Phase 1 results, parallel) → Phase 3 (synthesis + completeness audit by team-lead).
* **Shared Investigation Registry**: Team-lead creates a registry of found files, confirmed repos, search coverage, and open gaps. Every subagent receives this registry and does NOT re-search files already listed.
* **Mandatory Output Contract**: Every agent produces structured output with: FOUND FILES table, specialist findings, WHAT I DELIBERATELY SKIPPED, OPEN GAPS with criticality, CONFIDENCE LEVELS per finding, and HANDOFF TO NEXT AGENT.
* **Completeness Audit**: Analyst agent runs a structured completeness check (Helm, Terraform, CI, CD, cross-repo, secret chain coverage) before team-lead produces the final report. Confidence downgrades and contradiction detection included.

***

## MCP Tools (70 tools: 21 HiveMind + 25 Hawkeye + 24 Sherlock)

All 70 tools are available via `.vscode/mcp.json`. The tools are shared between Copilot Chat and Claude Agent — no separate configuration needed. See `hivemind_mcp/hivemind_server.py` for tool definitions.

**HiveMind core tools (21):** `hivemind_get_active_client`, `hivemind_query_memory`, `hivemind_query_graph`, `hivemind_get_entity`, `hivemind_search_files`, `hivemind_get_pipeline`, `hivemind_get_secret_flow`, `hivemind_impact_analysis`, `hivemind_diff_branches`, `hivemind_list_branches`, `hivemind_set_client`, `hivemind_write_file`, `hivemind_read_file`, `hivemind_propose_edit`, `hivemind_check_branch`, `hivemind_ensure_fresh`, `hivemind_get_active_branch`, `hivemind_save_investigation`, `hivemind_recall_investigation`, `hivemind_hti_get_skeleton`, `hivemind_hti_fetch_nodes`.

**Hawkeye pipeline observability tools (25):** `hivemind_hawkeye_diagnose`, `hivemind_hawkeye_investigate_failure`, `hivemind_hawkeye_get_execution`, `hivemind_hawkeye_get_stage_detail`, `hivemind_hawkeye_get_step_logs`, `hivemind_hawkeye_get_execution_inputs`, `hivemind_hawkeye_list_recent_executions`, `hivemind_hawkeye_get_all_stages`, `hivemind_hawkeye_get_child_execution`, `hivemind_hawkeye_check_approvals`, `hivemind_hawkeye_compare_executions`, `hivemind_hawkeye_get_failure_pattern`, `hivemind_hawkeye_get_pipeline_definition`, `hivemind_hawkeye_list_pipelines`, `hivemind_hawkeye_get_input_sets`, `hivemind_hawkeye_connect_account`, `hivemind_hawkeye_list_profiles`, `hivemind_hawkeye_list_delegates`, `hivemind_hawkeye_check_delegate`, `hivemind_hawkeye_list_connectors`, `hivemind_hawkeye_check_connector`, `hivemind_hawkeye_build_link`, `hivemind_hawkeye_parse_terraform_plan`, `hivemind_hawkeye_release_precheck_report`, `hivemind_hawkeye_ping`.

**Sherlock observability tools (24):** `hivemind_sherlock_connect_account`, `hivemind_sherlock_list_profiles`, `hivemind_sherlock_learn_account`, `hivemind_sherlock_get_account_summary`, `hivemind_sherlock_get_session_context`, `hivemind_sherlock_get_frustration_context`, `hivemind_sherlock_get_structured_report`, `hivemind_sherlock_get_nrql_context`, `hivemind_sherlock_investigate_synthetic`, `hivemind_sherlock_get_service_golden_signals`, `hivemind_sherlock_get_k8s_health`, `hivemind_sherlock_search_logs`, `hivemind_sherlock_get_synthetic_monitors`, `hivemind_sherlock_get_monitor_status`, `hivemind_sherlock_get_monitor_results`, `hivemind_sherlock_get_apm_applications`, `hivemind_sherlock_get_app_metrics`, `hivemind_sherlock_get_deployments`, `hivemind_sherlock_get_alerts`, `hivemind_sherlock_get_incidents`, `hivemind_sherlock_get_service_incidents`, `hivemind_sherlock_run_nrql_query`, `hivemind_sherlock_get_service_dependencies`, `hivemind_sherlock_resolve_account`.

### Tool Tiers (Quick Reference)

* **Tier 1** (parallel-safe, read-only): query\_memory, query\_graph, get\_entity, search\_files, hti\_\*, check\_branch, list\_branches, read\_file, recall\_investigation, ensure\_fresh, get\_active\_\*, all hawkeye\_\* tools, all sherlock\_\* tools
* **Tier 2** (serial, analysis): impact\_analysis, diff\_branches, get\_pipeline, get\_secret\_flow, save\_investigation, set\_client
* **Tier 3** (user approval): write\_file, propose\_edit

***

## Hawkeye Integration (Pipeline Observability)

Hawkeye is integrated as a subprocess MCP server via `hivemind_mcp/hawkeye_bridge.py`. It connects to the Harness API to fetch live pipeline execution data, logs, and investigation results.

**Architecture:** HiveMind MCP Server → HawkeyeBridge (MCP client) → Hawkeye MCP Server (child process, stdio)

**Key workflow — Pipeline failure investigation:**
1. User provides a Harness URL or execution ID
2. Call `hivemind_hawkeye_diagnose(url=...)` to get full failure analysis from live Harness APIs
3. Extract service name, error type, and failed stage from the Hawkeye output
4. Call `hivemind_query_memory` to cross-reference with KB (Helm values, Terraform, secrets)
5. Call `hivemind_impact_analysis` to assess blast radius
6. Synthesize findings from both live pipeline data AND indexed infrastructure knowledge

**When to use Hawkeye tools:**
- User provides a Harness pipeline URL → `hivemind_hawkeye_diagnose`
- User asks about a specific execution → `hivemind_hawkeye_get_execution`
- User asks about delegate health → `hivemind_hawkeye_list_delegates` / `hivemind_hawkeye_check_delegate`
- User asks about connector status → `hivemind_hawkeye_list_connectors`
- User wants Terraform plan summary → `hivemind_hawkeye_parse_terraform_plan`
- User wants failure patterns → `hivemind_hawkeye_get_failure_pattern`

**Configuration:** Hawkeye credentials are stored in `~/.hawkeye/profiles.json` (configured via `make connect` in the Hawkeye project). The bridge uses Hawkeye's own venv at `C:\Users\sekbote\Documents\Hawkeye\.venv\`.

***

## Sherlock Integration (New Relic Observability)

Sherlock is integrated as a subprocess MCP server via `hivemind_mcp/sherlock_bridge.py`. It connects to the New Relic API to fetch APM metrics, K8s health, logs, alerts, synthetics, and service dependency data.

**Architecture:** HiveMind MCP Server → SherlockBridge (MCP client) → Sherlock MCP Server (child process, stdio)

**Key workflow — Service health investigation:**
1. Call `hivemind_sherlock_connect_account(profile_name=...)` to connect to the New Relic account
2. Call `hivemind_sherlock_learn_account()` to discover entities
3. Call `hivemind_sherlock_get_service_golden_signals(service_name=...)` for golden signals
4. Call `hivemind_sherlock_get_k8s_health(service_name=...)` for K8s pod/container health
5. Call `hivemind_sherlock_search_logs(service_name=..., severity="ERROR")` for error logs
6. Cross-reference with HiveMind KB via `hivemind_query_memory` for Helm/Terraform config

**When to use Sherlock tools:**
- Service performance investigation → `hivemind_sherlock_get_service_golden_signals`
- K8s pod health check → `hivemind_sherlock_get_k8s_health`
- Log search → `hivemind_sherlock_search_logs`
- Synthetic monitor failures → `hivemind_sherlock_investigate_synthetic`
- Alert/incident review → `hivemind_sherlock_get_alerts` / `hivemind_sherlock_get_service_incidents`
- Deployment correlation → `hivemind_sherlock_get_deployments`
- Custom NRQL queries → `hivemind_sherlock_run_nrql_query`
- Service dependency mapping → `hivemind_sherlock_get_service_dependencies`

**Configuration:** Sherlock credentials are stored in keychain profiles (configured via `connect_account` or `.env` auto-connect). The bridge uses Sherlock's own venv at `C:\Users\sekbote\Documents\sherlock\.venv\`.

***

## File Reference Format

All file citations must use `repo/path/to/file.ext:L<line>` for VS Code
click-to-open navigation. When line numbers are unavailable, use path only:
`repo/path/to/file.ext`. See `.github/copilot-instructions.md` section 1.2
for full rules.

***

## HTI — Structural Retrieval

Two tools for precise YAML/HCL navigation:

* `hivemind_hti_get_skeleton` → returns file skeleton (keys + paths, no values)
* `hivemind_hti_fetch_nodes` → fetches full content at specific node paths

Use these for any structural query (specific stages, configs, variables, specs). See `.github/copilot-instructions.md` for full routing rules.

Note: HTI provides exact structural lookups from the parsed YAML/HCL tree. For broad semantic search, use `query_memory` which returns results with `rrf_score` and `flashrank_score` from the 3-stage retrieval pipeline.

Claude Agent advantage: can iterate — if first `node_paths` are wrong, call `fetch_nodes` again with corrected paths. The skeleton stays in context.

***

## Full Instructions Reference

For complete HiveMind rules, anti-hallucination requirements, citation format, branch protection, incident auto-detection, tool selection guide, and response templates, see `.github/copilot-instructions.md` — loaded automatically by both Copilot Chat and Claude Agent.
