---
name: investigation-memory
description: >
  Save and recall past incident investigations. Prevents re-investigating
  the same root causes across a 50+ microservice platform.
---

## When to use this skill

### Recall (search past investigations)

Trigger on any of these signals:

- "have we seen this before"
- "similar issue", "similar incident"
- "last time this happened"
- "recall", "/recall"
- "past incident", "previously"
- Automatically at the **start** of any new investigation — check memory
  before starting a fresh root-cause analysis

### Save (persist an investigation)

Trigger ONLY when the user explicitly asks:

- "save this investigation"
- "remember this investigation"
- "save what we found"
- "store this incident"
- "remember the fix"

**Never auto-save.** Never save partial investigations.

## How to invoke

### Recall past investigations

```
python tools/recall_investigation.py --client {client} --query "{query}"
```

Optional filters:

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Client name | --client dfin |
| --query | Search query | --query "spring bean init failure" |
| --service | Filter by service | --service tagging-service |
| --incident_type | Filter by type | --incident_type CrashLoopBackOff |
| --top_k | Number of results | --top_k 5 |

### Save an investigation

```
python tools/save_investigation.py --client {client} \
    --service {service_name} \
    --incident_type {type} \
    --root_cause "{summary}" \
    --resolution "{fix}" \
    --files "{path:repo:branch}" \
    --tags "{tag1,tag2}"
```

## What gets stored

Each investigation record contains:

| Field | Description |
|-------|-------------|
| id | UUID (auto-generated) |
| timestamp | ISO datetime |
| client | Client name |
| service_name | Primary service investigated |
| incident_type | CrashLoopBackOff, OOMKilled, SecretMount, ProbeFailure, PipelineFailure, InfraFailure, AppStartup, NetworkPolicy, ImagePull, Unknown |
| root_cause_summary | 2-3 sentence factual summary |
| resolution | What fix was applied or recommended |
| files_cited | File paths with repo, branch, and relevance |
| tags | Searchable tags (e.g. keyvault, spring-boot, probe) |

## Storage

Dual storage for reliability:

1. **JSON** — `memory/<client>/investigations/<id>.json` (human-readable)
2. **ChromaDB** — `investigations` collection in `memory/<client>/vectors/`

## Output format

When recalling past investigations, present results as:

```
## Past Investigations Found

### Investigation 1 (relevance: 95.2%)
- **Service:** tagging-service
- **Type:** CrashLoopBackOff
- **Time:** 2026-03-10T14:30:00Z
- **Root Cause:** Spring bean coreTaxonomySearchService failed to initialize
  due to search backend unavailable in predemo environment
- **Resolution:** Confirmed search service dependency was down. Restarted
  search-service pod. tagging-service recovered automatically.
- **Tags:** spring-boot, bean-init, dependency, search-service
- **Files:**
  - `charts/tagging-service/templates/deployment.yaml` [repo: newAd_Artifacts, branch: release_26_2]
```

## MCP tool names

| MCP Tool | Purpose |
|----------|---------|
| `hivemind_save_investigation` | Save — explicit only |
| `hivemind_recall_investigation` | Search past investigations |

## Citation rule

When citing a past investigation, include the investigation ID and timestamp
so users can locate the source JSON file if needed.
