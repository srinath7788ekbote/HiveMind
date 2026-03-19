# CLAUDE.md — Claude Agent Configuration for HiveMind

HiveMind is a local-first SRE knowledge assistant that indexes infrastructure repos (Terraform, Harness pipelines, Helm charts, Kubernetes secrets) into a ChromaDB-backed knowledge base, then exposes 16 MCP tools for semantic search, dependency graph traversal, impact analysis, secret lifecycle tracing, and incident investigation across multi-repo, multi-branch client environments.

---

## Claude Agent Capabilities

Claude Agent has capabilities beyond Copilot Chat. Use them.

### Direct File Access

Read local files to get runtime state without MCP tool calls:

- `memory/active_client.txt` — current client context
- `memory/active_branch.txt` — current branch context
- `memory/clients/{client}/discovered_profile.yaml` — auto-discovered architecture (services, environments, Terraform layers, naming conventions, secret patterns)
- `memory/sync_state.json` — last sync timestamps per repo/branch
- `clients/{client}/repos.yaml` — repo configuration for each client

### Safe Terminal Commands

Run these freely — they are read-only or non-destructive:

```
python scripts/sync_kb.py --status
python tools/query_memory.py --client <client> --query <query>
python -m pytest tests/ -q
python scripts/populate_chromadb.py --verify
python hivemind_mcp/hivemind_server.py --test
```

### Unsafe Commands (require explicit user approval)

Do NOT run these without asking the user first:

```
python ingest/crawl_repos.py          # Takes 2+ hours, re-indexes all repos
python scripts/populate_chromadb.py   # Takes 2+ hours, rebuilds vector store
git push                              # User must push manually
git commit                            # User reviews changes first
```

---

## Subagent Orchestration

### When to Use Subagents

| Scenario | Action |
|----------|--------|
| Simple KB lookup ("where is X defined?") | Handle inline, no subagents |
| Single-domain question (one agent can answer) | Handle inline, no subagents |
| Incident investigation (multi-domain) | Spawn parallel subagents |
| Multi-repo or multi-service analysis | Spawn parallel subagents |
| Impact analysis + runbook generation | Sequential: analyst then planner |

### Parallel Investigation Pattern

When an incident is detected or a complex multi-domain question arrives, spawn these subagents IN PARALLEL:

```
hivemind-investigator  → query_memory + impact_analysis (root cause)
hivemind-security      → get_secret_flow (if secrets/credentials involved)
hivemind-devops        → get_pipeline + Helm chart lookup (if deployment involved)
hivemind-architect     → Terraform/infra analysis (if infra involved)
```

The team-lead agent synthesizes all parallel results into a single response with:
- Consolidated findings from each agent
- Merged source citations table
- Single confidence rating (lowest of all agents)
- Recommended fix with specific file paths

### Agent Roster

| Agent | Specialty | Subagent Role |
|-------|-----------|---------------|
| `hivemind-team-lead` | Orchestrator, router, synthesizer | Spawns and coordinates all others |
| `hivemind-investigator` | Root cause analysis, cross-domain tracing | Worker: incident investigation |
| `hivemind-devops` | Pipelines, Helm, CI/CD, deployments | Worker: pipeline/deploy analysis |
| `hivemind-architect` | Terraform, IaC, infra layers, resource deps | Worker: infrastructure analysis |
| `hivemind-security` | RBAC, managed identities, Key Vault, secrets | Worker: security analysis |
| `hivemind-analyst` | Impact analysis, blast radius, change risk | Worker: risk assessment |
| `hivemind-planner` | Runbooks, migration plans, procedures | Worker: runbook generation |

### Handoff Chains

Supported handoff paths between agents:

```
team-lead ──→ investigator ──→ devops/security/architect ──→ team-lead (synthesize)
team-lead ──→ analyst ──→ planner ──→ devops (implement)
investigator ──→ team-lead (root cause found → generate postmortem)
planner ──→ devops (plan ready → start implementation)
```

Maximum 3 handoff hops per investigation. Maximum 8 total consultations per task.

### CrewAI-Inspired Coordination Model

Agents now use **phased parallel execution** with a **shared investigation registry**:

- **Semantic Intent Classification**: Team-lead classifies user intent semantically (INCIDENT, STRUCTURAL, DEPENDENCY, DIFF, SECRET_FLOW, PLANNING, GENERAL) and routes accordingly. No keyword matching — reads the full message context.
- **Phased Execution**: Phase 1 (raw data gathering, parallel) → Phase 2 (specialized analysis using Phase 1 results, parallel) → Phase 3 (synthesis + completeness audit by team-lead).
- **Shared Investigation Registry**: Team-lead creates a registry of found files, confirmed repos, search coverage, and open gaps. Every subagent receives this registry and does NOT re-search files already listed.
- **Mandatory Output Contract**: Every agent produces structured output with: FOUND FILES table, specialist findings, WHAT I DELIBERATELY SKIPPED, OPEN GAPS with criticality, CONFIDENCE LEVELS per finding, and HANDOFF TO NEXT AGENT.
- **Completeness Audit**: Analyst agent runs a structured completeness check (Helm, Terraform, CI, CD, cross-repo, secret chain coverage) before team-lead produces the final report. Confidence downgrades and contradiction detection included.

---

## MCP Tools (16 tools)

All 16 HiveMind MCP tools are available via `.vscode/mcp.json`. The tools are shared between Copilot Chat and Claude Agent — no separate configuration needed. See `hivemind_mcp/hivemind_server.py` for tool definitions.

Key tools: `hivemind_get_active_client`, `hivemind_query_memory`, `hivemind_query_graph`, `hivemind_get_entity`, `hivemind_search_files`, `hivemind_get_pipeline`, `hivemind_get_secret_flow`, `hivemind_impact_analysis`, `hivemind_diff_branches`, `hivemind_list_branches`, `hivemind_set_client`, `hivemind_write_file`, `hivemind_check_branch`, `hivemind_get_active_branch`, `hivemind_save_investigation`, `hivemind_recall_investigation`.

---

## HTI — Structural Retrieval

Two new tools for precise YAML/HCL navigation:
- `hivemind_hti_get_skeleton` → returns file skeleton (keys + paths, no values)
- `hivemind_hti_fetch_nodes` → fetches full content at specific node paths

Use these for any structural query (specific stages, configs, variables, specs). See `.github/copilot-instructions.md` for full routing rules.

Claude Agent advantage: can iterate — if first `node_paths` are wrong, call `fetch_nodes` again with corrected paths. The skeleton stays in context.

---

## Full Instructions Reference

For complete HiveMind rules, anti-hallucination requirements, citation format, branch protection, incident auto-detection, tool selection guide, and response templates, see `.github/copilot-instructions.md` — loaded automatically by both Copilot Chat and Claude Agent.
