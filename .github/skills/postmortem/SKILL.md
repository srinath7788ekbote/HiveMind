---
name: postmortem
description: >
  Generates a structured incident postmortem from a completed investigation.
  Synthesizes findings from incident-triage, k8s-debug, and secret-audit
  into a chronological RCA report with timeline, contributing factors,
  MTTR/MTTD metrics, blast radius, and prevention measures.
  Output is rendered entirely in Copilot chat — no files created.
activation: explicit-only
triggers:
  - /postmortem
  - write a postmortem
  - generate postmortem
  - create postmortem
  - run postmortem
slash_command: /postmortem
---

# Postmortem — Incident RCA Report Generator

> **ACTIVATION: EXPLICIT ONLY.** This skill activates ONLY when the user
> explicitly asks for a postmortem (e.g., `/postmortem`, "write a postmortem",
> "generate postmortem"). It must NEVER auto-trigger from keywords like
> "RCA", "what happened", "incident report", or "impact" during normal
> investigation. Those belong to incident-triage or k8s-debug.
>
> This skill runs AFTER an investigation is complete. It synthesizes
> findings from incident-triage, k8s-debug, secret-audit, and any other
> investigation data already in the current chat into a structured
> postmortem report rendered directly in Copilot chat.
> Five mandatory sections. Every claim cited. No vague language. No files created.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| P-0 | **NEVER activate unless the user EXPLICITLY asks for a postmortem.** Keywords like "RCA", "what happened", "incident report", "impact", "how long were we down" during an investigation do NOT mean "generate a postmortem" — they belong to incident-triage or k8s-debug. This skill activates ONLY on `/postmortem` or an explicit request like "write a postmortem" / "generate postmortem". |
| P-1 | **NEVER generate a postmortem before root cause is identified.** If `/postmortem` is invoked before the investigation has identified a root cause, respond: `"⚠️ Root cause not yet identified in this conversation. Run /triage or complete the investigation first. I can start one now if you'd like."` |
| P-2 | **NEVER use vague language.** Banned words: "issues", "problems", "challenges", "opportunities for improvement", "suboptimal", "could be better". State exactly what was wrong. |
| P-3 | **NEVER omit a mandatory section.** All 5 mandatory sections must appear even if data is limited. If data is missing, state what's missing and mark as `"unknown"`. |
| P-4 | **NEVER invent times or metrics.** If a timestamp is unknown, write `"unknown"` or `"~estimated"`. Never fabricate a time to fill a gap. |
| P-5 | **NEVER editorialize.** State facts. Do not add opinions, judgments, or softening language. If a misconfiguration caused the outage, say so directly. |
| P-6 | **NEVER create files or export documents.** The postmortem is rendered in Copilot chat only. If the user wants to save it, they copy from chat. |
| P-7 | **NEVER run commands.** User is on AVD via jump host. If additional data is needed, ask the user to run a command and paste the result. |
| P-8 | **ALWAYS cite sources** for every finding: KB file path with repo and branch, Sherlock tool name, user-provided, or command output. |
| P-9 | **ALWAYS call `hivemind_impact_analysis`** for blast radius — never guess at affected services. |
| P-10 | **ALWAYS include all 5 mandatory sections** in this order: Timeline, Contributing Factors, MTTR/MTTD, Blast Radius, Prevention Measures. |

---

## 🔄 SHERLOCK FALLBACK RULE

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use it for MTTD/MTTR calculation, error rate windows, deployment markers |
| **Path B** | Sherlock unavailable or no data | Ask user for 4 timestamps, mark as "user-provided", continue |

**Path A tools (query automatically):**
- `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — error rate, throughput, response time windows
- `mcp_sherlock_get_deployments(app_name="<service>")` — last deployment before incident
- `mcp_sherlock_get_service_incidents(service_name="<service>")` — alert fire time (MTTD anchor)
- `mcp_sherlock_search_logs(service_name="<service>", keyword="error|exception|fatal")` — first error timestamp
- `mcp_sherlock_get_incidents()` — broader incident context

**Path B fallback — ask user these 4 questions:**
```
To calculate MTTR/MTTD without Sherlock, I need:
1. When was the first symptom observed? (timestamp or approximate)
2. When was the incident detected? (alert fired / user reported / team noticed)
3. When was the fix applied?
4. When was the service fully restored?
```
Mark all Path B times as `"user-provided (estimated)"` in the timeline and metrics tables.

---

## Input Gathering Phase

Before generating the postmortem, collect all inputs. Do this systematically — do not start writing until inputs are gathered.

### Source 1 — Current Chat (extract automatically, do NOT re-ask)

Scan the current conversation for:

| Data Point | Where to Find It |
|------------|-----------------|
| Affected service(s) | Investigation headers, signal extraction tables |
| Root cause statement | Root Cause / Hypothesis section of investigation output |
| Confidence level | `🎯 Confidence:` marker in investigation output |
| Failure mode | FM-1 through FM-7 (secret-audit), pod status (k8s-debug) |
| KB citations | `📁 Sources:` blocks with file paths, repos, branches |
| Command outputs | Code blocks pasted by user during investigation |
| Commands recommended | Numbered command lists from investigation skills |
| Secret chain findings | Chain trace from secret-audit output |
| Pod/container findings | Layer findings from k8s-debug output |

**Rule:** If the investigation already found it, do not ask the user again. Do not re-query KB for data already cited in the conversation.

### Source 2 — Sherlock (query automatically)

```
mcp_sherlock_get_service_golden_signals(service_name="<primary-service>")
mcp_sherlock_get_deployments(app_name="<primary-service>")
mcp_sherlock_get_service_incidents(service_name="<primary-service>")
```

Extract:
- Error rate: when it spiked, peak value, when it returned to baseline
- Response time: when it degraded, peak latency, when it normalized
- Throughput: when it dropped, lowest point, when it recovered
- Last deployment: exact timestamp and deployer (if available)
- First alert: exact timestamp and alert condition name

### Source 3 — HiveMind KB (query automatically)

```
hivemind_get_active_client()
hivemind_impact_analysis(client=<client>, entity="<primary-service>")
```

For any services in the blast radius that were NOT already investigated:
```
hivemind_get_entity(client=<client>, name="<affected-service>")
hivemind_query_memory(client=<client>, query="<affected-service> deployment health")
```

### Source 4 — User (ask explicitly if not already known)

Only ask for what is genuinely missing from Sources 1-3:

| Question | When to Ask |
|----------|------------|
| Who detected the incident and how? | If not clear from investigation chat |
| What resolution action was taken? | If investigation identified root cause but fix wasn't discussed |
| Were there manual interventions during the incident? | Always ask — investigations don't always capture this |
| Approximate times (if Sherlock unavailable) | Path B only — see fallback section |

**Ask all needed questions in a single message.** Do not ask one at a time.

---

## Mandatory Section 1 — Timeline of Events

Chronological table. Every row cites its source.

**Required events** (include all that apply, in order):

| Event Type | How to Determine | Required? |
|------------|-----------------|-----------|
| Last known-good state | Sherlock deployment marker or user confirmation | Yes |
| Triggering change | Deployment, config change, infra change, secret rotation | Yes (if identifiable) |
| First symptom | Sherlock error rate spike, first error log timestamp | Yes |
| Alert / detection | Sherlock alert fire time, or user-provided detection time | Yes |
| Investigation started | Approximate from chat timestamps or user | Yes |
| Root cause identified | When the investigation concluded | Yes |
| Mitigation applied | When fix was applied (rollback, config change, restart) | Yes |
| Service restored | Sherlock error rate return to baseline, or user confirmation | Yes |
| Contributing events | Any other changes during window (dependency outage, infra event) | If applicable |

**Format:**

```
### Timeline of Events

| Time (UTC) | Event | Source |
|------------|-------|--------|
| 2026-03-12 14:00 | Harness deployment `<pipeline>` completed for `<service>` | Sherlock: `get_deployments` |
| 2026-03-12 14:03 | Error rate spiked from 0.1% to 42% | Sherlock: `get_service_golden_signals` |
| 2026-03-12 14:05 | New Relic alert `<alert-name>` fired | Sherlock: `get_service_incidents` |
| 2026-03-12 14:10 | On-call SRE began investigation | User-provided |
| 2026-03-12 14:25 | Root cause identified: <one-line summary> | Investigation (this chat) |
| 2026-03-12 14:30 | Rollback initiated via Harness | User-provided |
| 2026-03-12 14:35 | Error rate returned to baseline | Sherlock: `get_service_golden_signals` |
```

**If exact times unknown:**
```
| T+0 | Deployment completed | KB: `pipelines/<service>.yaml` [repo: harness, branch: main] |
| T+3m (~estimated) | Error rate spike observed | User-provided (estimated) |
```

---

## Mandatory Section 2 — Contributing Factors

These are NOT the root cause — they are conditions that made the incident possible, harder to detect, or longer to resolve.

**Format for each factor:**

```
**<N>. <Specific factor statement>**
- Mechanism: <how this contributed to the incident or its duration>
- Evidence: `<file_path>` [repo: <repo>, branch: <branch>] / Sherlock: <tool> / Command output / User-provided
```

**Factor identification guide:**

| Category | What to Look For | Example (specific, not vague) |
|----------|-----------------|-------------------------------|
| Health check gap | Probe config vs actual startup time | `readinessProbe.initialDelaySeconds: 10` but Spring Boot JVM takes 45s to initialize — pod received traffic before ready |
| Alerting gap | What alerted vs what should have alerted | No alert on KeyVault 403 errors — alert only fires on HTTP 5xx at the service level, missing the upstream cause |
| Dependency coupling | Missing circuit breaker / retry / timeout | `<service>` calls `<dependency>` with no timeout configured — hung connections exhausted thread pool |
| Validation gap | What wasn't checked before deploy | Harness pipeline has no pre-deploy secret validation — `<secret-name>` was missing in target environment |
| Resource sizing | Limits vs actual usage | Memory limit 512Mi but service heap is 480Mi + Spring overhead — OOM on any traffic spike |
| Blast radius amplifier | Why one failure cascaded | All 12 services in `<namespace>` share managed identity `<identity>` — one broken federated credential took down everything |
| Missing runbook | Knowledge gap during incident | No documented procedure for CSI driver mount failures — investigation took 40 minutes to reach Layer 4 |
| Single point of failure | No redundancy | Single KeyVault `<vault>` serves all environments — vault-level outage affects dev through prod |

**Rules:**
- Minimum 2 contributing factors per postmortem (root cause alone never tells the full story)
- Maximum 8 (focus on the ones that matter)
- Each factor must have evidence — no speculative factors
- Never write "health check configuration was suboptimal" — write exactly what was wrong

---

## Mandatory Section 3 — MTTR / MTTD Metrics

**Definitions used in this report:**

| Metric | Start | End | Measures |
|--------|-------|-----|----------|
| **MTTD** (Mean Time To Detect) | First symptom (error rate spike, first error log) | Alert fired or human detected | How fast we noticed |
| **MTTR** (Mean Time To Recover) | Alert fired / detection | Service restored (error rate baseline) | How fast we fixed it |
| **Total Incident Duration** | First symptom | Full resolution | End-to-end outage window |
| **Impact Window** | First user/system impact | Last user/system impact | How long consumers were affected |

**Data source priority:**
1. Sherlock golden signals — error rate spike start/end = most accurate symptom window
2. Sherlock alert data — alert fire time = MTTD endpoint
3. Sherlock deployment markers — deployment time = potential symptom start
4. Command output timestamps from investigation — user-pasted `kubectl` or `az` output
5. User-provided estimates — mark as `"estimated"` in every reference

**Format:**

```
### MTTR / MTTD Metrics

| Metric | Start | End | Duration | Source |
|--------|-------|-----|----------|--------|
| MTTD | 14:03 (first error spike) | 14:05 (alert fired) | **2 minutes** | Sherlock |
| MTTR | 14:05 (alert fired) | 14:35 (error rate baseline) | **30 minutes** | Sherlock |
| Total Duration | 14:03 → 14:35 | | **32 minutes** | Calculated |
| Impact Window | 14:03 → 14:35 | | **32 minutes** | Sherlock golden signals |
```

**If Sherlock unavailable:**

```
| Metric | Start | End | Duration | Source |
|--------|-------|-----|----------|--------|
| MTTD | ~14:00 (estimated) | ~14:15 (user noticed) | **~15 minutes** | User-provided (estimated) |
| MTTR | ~14:15 (detected) | ~14:50 (confirmed restored) | **~35 minutes** | User-provided (estimated) |

⚠️ All times are user-provided estimates. Sherlock was unavailable for precise metrics.
```

**MTTR/MTTD assessment guidance (do NOT editorialize — state the numbers and let the table below contextualize):**

| MTTD | Assessment |
|------|-----------|
| < 2 min | Alert coverage worked |
| 2–10 min | Alert exists but threshold or evaluation window too wide |
| > 10 min | No alert covered this failure mode — detected manually |

| MTTR | Assessment |
|------|-----------|
| < 15 min | Standard rollback/restart recovery |
| 15–60 min | Required investigation to identify root cause |
| > 60 min | Complex root cause, multi-system coordination, or missing runbook |

---

## Mandatory Section 4 — Blast Radius / Services Affected

**Always run these tools:**
```
hivemind_impact_analysis(client=<client>, entity="<primary-service>")
hivemind_query_memory(client=<client>, query="<primary-service> dependency upstream downstream")
```

For Sherlock correlation on affected services (Path A only):
```
mcp_sherlock_get_service_dependencies(service_name="<primary-service>")
mcp_sherlock_get_service_golden_signals(service_name="<affected-service>")
```

**Impact classification:**

| Level | Definition | Example |
|-------|-----------|---------|
| **Primary** | The service that failed | `audit-service` — CrashLoopBackOff |
| **Direct** | Services that call the primary service | `api-gateway` — 504 timeout on `/audit` endpoint |
| **Indirect** | Services downstream of direct-impact services | `web-frontend` — user sees "Service Unavailable" |
| **External** | User-facing / partner-facing impact | End users cannot access audit reports |
| **Data** | Data loss, corruption, or inconsistency | Audit log entries missing for 32-minute window |

**Format:**

```
### Blast Radius

**Primary:**
└── `<primary-service>` — <status> — <what happened>
    📁 `<helm-values.yaml>` [repo: <repo>, branch: <branch>]

**Directly Impacted:**
├── `<service-A>` — <how affected> — <evidence>
│   📁 Source: `hivemind_impact_analysis`
├── `<service-B>` — <how affected> — <evidence>
│   📁 Source: `hivemind_impact_analysis`

**Indirectly Impacted:**
├── `<service-C>` — <how affected>

**External Impact:**
├── <user-facing feature/flow> — <degraded/unavailable>

**Data Impact:**
├── <data system> — <loss/corruption/none>

Total services affected: <N>
User-facing impact: Yes/No — <which features>
Data loss: Yes/No — <what data, what window>
```

---

## Mandatory Section 5 — Prevention Measures

Specific to what was found. Never generic.

**Format for each measure:**

```
**<N>. <Specific action statement>** [P<1|2|3>]
- Location: `<file_path>` [repo: <repo>, branch: <branch>] OR <system/process>
- Change: <exact field / config / process to change and to what value>
- Prevents: <how this stops the same incident from recurring>
```

**Priority definitions:**

| Priority | Meaning | Timeline |
|----------|---------|----------|
| **P1** | Prevents this exact incident from recurring | This sprint |
| **P2** | Reduces blast radius or impact duration of similar incidents | Next sprint |
| **P3** | Improves detection speed or investigation efficiency | Backlog |

**Categories to evaluate (include if relevant to THIS incident):**

| Category | What to Recommend | Example |
|----------|-------------------|---------|
| **Config Fix** | Exact field to change in exact file | `readinessProbe.initialDelaySeconds: 10` → `45` in `charts/<service>/values.yaml` |
| **Monitoring Gap** | Missing alert with NRQL query | `NRQL: SELECT count(*) FROM Log WHERE message LIKE '%KeyVault%403%' FACET serviceName` — alert if > 0 in 5 min |
| **Probe Fix** | Health check values based on observed startup | `livenessProbe.initialDelaySeconds` from `10` to `60` based on 45s observed JVM startup |
| **Resource Fix** | Limits based on observed usage | Memory limit from `512Mi` to `768Mi` based on 480Mi heap + 200Mi overhead |
| **Runbook** | Document for this failure mode | Create runbook: "CSI mount failure triage" covering Layers 3-4 of secret-audit |
| **Dependency Resilience** | Circuit breaker, timeout, retry | Add `resilience4j.circuitbreaker` config for `<dependency>` call with 5s timeout |
| **Deploy Gate** | Pre-deploy validation in pipeline | Add stage to Harness pipeline: verify secret exists in target env KeyVault before deploy |
| **Blast Radius Reduction** | Isolation, per-service identity | Migrate from shared identity `<shared-id>` to per-service workload identity |

**Rules:**
- Minimum 3 prevention measures per postmortem
- At least one P1 (otherwise the same incident can recur tomorrow)
- Config fixes must cite exact file path from KB — never say "update the Helm values" without specifying which file
- Monitoring gaps must include a draft NRQL query or alert condition
- Never write "improve monitoring" — write exactly what to monitor and how

---

## Investigation Completeness Check

Before generating the postmortem, verify:

| Check | How | If Missing |
|-------|-----|-----------|
| Root cause identified? | Look for Root Cause / Hypothesis in chat | Stop. Ask user to complete investigation or offer to run `/triage` |
| Confidence stated? | Look for `🎯 Confidence:` marker | Default to MEDIUM, note that confidence was not explicitly stated |
| KB citations present? | Look for `📁 Sources:` blocks | Run `hivemind_query_memory` for the affected service |
| Blast radius checked? | Look for impact analysis output | Run `hivemind_impact_analysis` now |
| Timeline events available? | At least: trigger, detection, resolution | Ask user for missing timestamps in a single question |
| Fix identified? | Look for fix/remediation in investigation | Include root cause without fix — note "fix not yet determined" |

**If root cause is not identified:** Do NOT generate the postmortem. Respond:
```
⚠️ Cannot generate postmortem — root cause has not been identified in this investigation.

Options:
1. I can run /triage to start the investigation
2. If you have a root cause in mind, state it and I'll build the postmortem around it
3. If the investigation is ongoing, continue it and run /postmortem when complete
```

---

## Graceful Degradation

| Condition | Behavior |
|-----------|----------|
| Sherlock unavailable | Ask user for 4 timestamps. Mark all metrics as "user-provided (estimated)". Generate full postmortem with KB-only blast radius. |
| KB returns no results for service | Note: `"⚠️ <service> not found in HiveMind KB. Blast radius based on investigation findings only."` Use whatever dependency info was found during investigation. |
| Investigation was partial | Generate postmortem with available data. Mark missing sections with `"⚠️ Data not available — <what's missing>"`. Never skip the section entirely. |
| No Sherlock + no KB | Generate postmortem from chat investigation findings only. Mark all external data points as unavailable. Still produce all 5 mandatory sections from what the investigation already found. |
| User invokes `/postmortem` with no prior investigation | See P-1 constraint. Do not generate. Offer to start investigation. |
| Multiple services failed simultaneously | Generate one postmortem covering all services. Blast radius section shows the full cascade. Timeline shows parallel event streams. |
| Root cause confidence is LOW | State it clearly in the report: `"🎯 Confidence: LOW — root cause is a hypothesis, not confirmed."` Include what additional data would raise confidence. |

---

## Full Output Format

Render this structure in Copilot chat. No file creation. No export.

```
## 📋 INCIDENT POSTMORTEM — <service-name> — <YYYY-MM-DD>

### Incident Summary
<3-4 sentences. What service. What happened. How long. What fixed it.
Factual. No hedging. Example:>

`audit-service` in the `prod` namespace entered CrashLoopBackOff at 14:03 UTC
on 2026-03-12 following a Harness deployment that introduced a reference to
KeyVault secret `audit-db-password` which did not exist in the production
KeyVault. The service was down for 32 minutes. Resolution was a rollback to
the previous deployment via Harness.

### Root Cause
📋 **Root Cause:** <single clear statement — what specifically was wrong>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - `<file_path>` [repo: <repo>, branch: <branch>] — <what this file shows>
  - Sherlock: `<tool>(<params>)` — <what this showed>
  - Command output: `<command>` — <what user result showed>

### Timeline of Events

| Time (UTC) | Event | Source |
|------------|-------|--------|
| <time> | <event> | <source with citation> |
| <time> | <event> | <source with citation> |
| ... | ... | ... |

### Contributing Factors

**1. <Specific factor>**
- Mechanism: <how it contributed>
- Evidence: <citation>

**2. <Specific factor>**
- Mechanism: <how it contributed>
- Evidence: <citation>

### MTTR / MTTD Metrics

| Metric | Start | End | Duration | Source |
|--------|-------|-----|----------|--------|
| MTTD | <time> | <time> | **<duration>** | <source> |
| MTTR | <time> | <time> | **<duration>** | <source> |
| Total Duration | <start> | <end> | **<duration>** | Calculated |
| Impact Window | <start> | <end> | **<duration>** | <source> |

### Blast Radius

**Primary:**
└── `<service>` — <status>

**Directly Impacted:**
├── `<service>` — <how affected>

**Indirectly Impacted:**
├── `<service>` — <how affected>

**External Impact:** <user-facing description or "None">
**Data Impact:** <data loss description or "None">
Total services affected: <N>

### Prevention Measures

**1. <Action>** [P1]
- Location: `<file_path>` [repo: <repo>, branch: <branch>]
- Change: <exact change>
- Prevents: <mechanism>

**2. <Action>** [P2]
- Location: `<file_path>` [repo: <repo>, branch: <branch>]
- Change: <exact change>
- Prevents: <mechanism>

**3. <Action>** [P3]
- Location: <system/process>
- Change: <exact change>
- Prevents: <mechanism>

---
## All Sources
| Source Type | Tool / Command | File / Query | Repo | Branch |
|------------|---------------|-------------|------|--------|
| KB | hivemind_get_secret_flow | `<file_path>` | <repo> | <branch> |
| KB | hivemind_impact_analysis | `<entity>` | — | — |
| KB | hivemind_query_memory | `<file_path>` | <repo> | <branch> |
| Sherlock | get_service_golden_signals | `<service>` | — | — |
| Sherlock | get_deployments | `<service>` | — | — |
| User | — | <user-provided data point> | — | — |
| Cmd | User ran | `<command>` | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```

---

## KB Cross-Reference — Summary Map

| What You Need | HiveMind Tool | Query Pattern |
|---------------|---------------|---------------|
| Blast radius (**ALWAYS**) | `hivemind_impact_analysis(entity="<service>")` | Upstream + downstream cascade |
| Service metadata | `hivemind_get_entity(name="<service>")` | Repos, branches, environments |
| Secret chain (if secret-related) | `hivemind_get_secret_flow(secret="<name>")` | Full chain trace |
| Pipeline config | `hivemind_get_pipeline(name="<pipeline>")` | Stages, variables, gates |
| Deployment config | `hivemind_query_memory(query="<service> deployment helm values")` | Helm values, resource limits |
| Health checks | `hivemind_query_memory(query="<service> readinessProbe livenessProbe")` | Probe configuration |
| Dependencies | `hivemind_query_memory(query="<service> dependency upstream")` | Service graph |
| Shared identities | `hivemind_query_memory(query="<identity> managed identity services")` | Identity blast radius |
| Terraform infra | `hivemind_query_memory(query="<service> terraform module layer")` | IaC definitions |

---

## Sherlock Correlation — Summary Map

**Path A (Sherlock available):**

| What You Need | Sherlock Tool | Extracts |
|---------------|-------------|----------|
| Error rate window | `get_service_golden_signals` | Spike start, peak, return to baseline |
| Response time window | `get_service_golden_signals` | Degradation start, peak latency, recovery |
| Throughput window | `get_service_golden_signals` | Drop start, lowest point, recovery |
| Deployment marker | `get_deployments` | Exact deploy time, correlation with symptom start |
| Alert fire time | `get_service_incidents` | MTTD endpoint |
| Error logs | `search_logs` | First error timestamp, error pattern |
| Dependency health | `get_service_dependencies` | Which dependencies were also impacted |
| Affected service signals | `get_service_golden_signals` (per affected service) | Confirm blast radius with metrics |

**Path B (Sherlock unavailable):**

Ask user once for all needed times:
```
Sherlock is unavailable. To build the postmortem timeline and metrics, I need:

1. When did the incident start? (first symptom or triggering change)
2. When was it detected? (alert, user report, or manual observation)
3. When was the fix applied? (rollback, config change, restart)
4. When was the service confirmed restored?
5. How was it detected? (which alert, user complaint, monitoring check)
```
