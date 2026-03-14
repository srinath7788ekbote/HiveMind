````skill
---
name: incident-triage
description: >
  Full-cycle incident investigation and triage for SRE operations. Combines
  HiveMind KB (Helm, Terraform, Harness pipelines, secret flows) with Sherlock
  live observability (New Relic APM, alerts, logs, K8s health, golden signals)
  to produce root-cause analysis, remediation plans, and rollback paths.
triggers:
  - CrashLoopBackOff
  - OOMKilled
  - ImagePullBackOff
  - Evicted
  - Terminating
  - Pending
  - BackOff
  - ContainerCreating
  - probe failed
  - connection refused
  - connection timed out
  - panic
  - FATAL
  - SIGKILL
  - SIGTERM
  - exit code 137
  - exit code 143
  - 5xx
  - 502
  - 503
  - 504
  - timeout
  - gateway timeout
  - service unavailable
  - Error
  - Exception
  - failed to
  - unable to
  - permission denied
  - unauthorized
  - ResourceNotFound
  - AuthorizationFailed
  - QuotaExceeded
  - incident
  - outage
  - down
  - alerting
  - triage
  - investigate
  - root cause
  - postmortem
  - rollback
slash_command: /triage
---

# Incident Triage — SRE Operations Playbook

> This skill governs how Copilot investigates production incidents. It is
> activated automatically when logs, errors, alerts, or incident data appear
> in the conversation. Follow every phase in order. Skip nothing.

---

## ⛔ PRIME CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| C-1 | **NEVER run commands.** Copilot operates on an AVD via jump host. You CANNOT execute `kubectl`, `helm`, `az`, or any shell command. You MUST recommend commands for the user to run, then wait for pasted output. |
| C-2 | **NEVER answer from training data when KB or Sherlock has relevant results.** |
| C-3 | **NEVER skip `hivemind_impact_analysis`.** Cascading failures are the norm on microservice platforms. Always check the dependency chain. |
| C-4 | **ALWAYS check Sherlock** for correlated New Relic alerts, golden signals, and logs. |
| C-5 | **ALWAYS cite file path + repo + branch** for every KB finding. |
| C-6 | **ALWAYS ask:** "Is this service the origin or a downstream victim?" |
| C-7 | **ALWAYS provide a rollback path** in the remediation plan. |
| C-8 | **ALWAYS extract signals from logs FIRST** — never ask the user "which service is this?" |
| C-9 | **NEVER output a partial investigation.** Complete all applicable phases before responding. |
| C-10 | **NEVER say "I can look into this if you'd like"** — you MUST already be investigating. |

---

## Phase 1 — SIGNAL EXTRACTION

Parse the pasted content **immediately**. Do NOT ask clarifying questions before extraction.

### 1.1. Extract These Signals

| Signal | Source |
|--------|--------|
| **service_name** | Pod name prefix, container name, namespace label, log `source` field, image name |
| **error_type** | Error class: `OOMKilled`, `CrashLoopBackOff`, `connection refused`, HTTP status, exception class |
| **namespace** | Kubernetes namespace from pod FQDN, kubectl output, or log metadata |
| **timestamp_range** | Earliest and latest timestamps in the pasted content |
| **secret_refs** | Any Key Vault name, secret name, config map, credential, or mount path referenced |
| **image_refs** | Container image names and tags (ACR registry, image name, tag/SHA) |
| **config_refs** | ConfigMap names, environment variable names, Helm value paths |
| **pipeline_refs** | Harness pipeline name, stage name, execution ID |

### 1.2. Classify Incident Type

Assign exactly ONE primary type:

| Type | ID | Trigger Patterns |
|------|----|------------------|
| Pod / Container Failure | `POD` | CrashLoopBackOff, OOMKilled, ImagePullBackOff, Evicted, Pending, ContainerCreating, exit code 137/143 |
| Secret / Config Failure | `SECRET` | KeyVault mount failed, secret not found, missing env var, MountVolume.SetUp failed, permission denied on secret |
| Probe Failure | `PROBE` | liveness probe failed, readiness probe failed, startup probe failed, connection refused on probe port |
| Pipeline / Deployment Failure | `PIPELINE` | Harness stage failed, rollout stuck, image pull error in deploy stage, approval timeout |
| Infrastructure Failure | `INFRA` | Node NotReady, DiskPressure, MemoryPressure, PVC pending, Terraform drift, network policy deny |
| Application Failure | `APP` | Spring Boot BeanCreationException, connection refused to dependency, socket timeout, NullPointerException, JDBC connection failure |
| Monitoring Alert | `ALERT` | New Relic alert condition, NRQL threshold breach, missing golden signals, synthetic monitor failure |

### 1.3. Assess Blast Radius (Initial)

| Scope | Criteria |
|-------|----------|
| **SINGLE_POD** | One pod in CrashLoopBackOff, other replicas healthy |
| **SINGLE_SERVICE** | All pods of one service affected |
| **MULTI_SERVICE** | Logs reference multiple service names or cascading errors |
| **CLUSTER_WIDE** | Node-level issues, namespace-wide failures, ingress down |

---

## Phase 2 — KB CROSS-REFERENCE (HiveMind)

Query the knowledge base **before forming any hypothesis**. The KB contains the actual infrastructure configuration.

### 2.1. Mandatory First Steps

```
STEP 1: Call hivemind_get_active_client()
        → Determines which client KB to search

STEP 2: Call hivemind_query_memory(client=<client>, query="<service_name> <error_type>")
        → Search for Helm values, Terraform config, pipeline definitions

STEP 3: Call hivemind_get_entity(client=<client>, name="<service_name>")
        → Get full entity metadata: repos, environments, dependencies

STEP 4: Call hivemind_impact_analysis(client=<client>, entity="<service_name>")
        → NEVER SKIP — get upstream/downstream dependency chain
```

### 2.2. Tool Selection Matrix by Incident Type

| Incident Type | Required HiveMind Tools | Query Patterns |
|---------------|------------------------|----------------|
| `POD` | `query_memory`, `get_entity`, `impact_analysis` | `"<service> helm values"`, `"<service> deployment"`, `"<service> resources limits"` |
| `SECRET` | `get_secret_flow`, `query_memory`, `impact_analysis` | `"<secret_name> keyvault"`, `"<service> secrets"`, `"<service> env vars"` |
| `PROBE` | `query_memory`, `get_entity`, `impact_analysis` | `"<service> probes"`, `"<service> health check"`, `"<service> readiness liveness"` |
| `PIPELINE` | `get_pipeline`, `query_memory`, `impact_analysis` | `"<pipeline_name>"`, `"<service> deploy pipeline"`, `"<service> harness"` |
| `INFRA` | `query_memory`, `impact_analysis`, `search_files` | `"<resource> terraform"`, `"aks node pool"`, `"pvc storage"`, `"network policy"` |
| `APP` | `query_memory`, `get_entity`, `get_secret_flow` | `"<service> configuration"`, `"<service> dependencies"`, `"<service> connection string"` |
| `ALERT` | `query_memory`, `get_entity`, `impact_analysis` | `"<service> monitoring"`, `"<service> alert"`, `"<service> NRQL"` |

### 2.3. Conditional Tool Calls

| Condition in Logs | Additional Tool Call |
|-------------------|---------------------|
| Secret, KeyVault, credential, mount, or permission error | `hivemind_get_secret_flow(client=<client>, secret="<secret_name>")` |
| Pipeline, deployment, rollout, release, or Harness reference | `hivemind_get_pipeline(client=<client>, name="<pipeline_name>")` |
| Cross-service dependency error (connection refused to another service) | `hivemind_impact_analysis` on BOTH source and target services |
| Terraform resource name or infra component referenced | `hivemind_search_files(client=<client>, query="<resource>.tf")` |
| Branch-specific investigation | `hivemind_check_branch` first, then branch-filtered queries |

---

## Phase 3 — OBSERVABILITY CROSS-REFERENCE (Sherlock / New Relic)

After KB lookup, query live telemetry to correlate timing and detect active alerts.

### 3.1. Mandatory Sherlock Calls

```
STEP 1: Call mcp_sherlock_get_service_golden_signals(service_name="<service>")
        → Get latency, error rate, throughput, saturation

STEP 2: Call mcp_sherlock_get_service_incidents(service_name="<service>")
        → Check for active or recent New Relic incidents

STEP 3: Call mcp_sherlock_search_logs(service_name="<service>", severity="ERROR", since_minutes=60)
        → Get recent error logs from New Relic

STEP 4: Call mcp_sherlock_get_k8s_health(service_name="<service>")
        → Get pod/container/node health from New Relic K8s integration
```

### 3.2. Conditional Sherlock Calls

| Condition | Sherlock Tool |
|-----------|---------------|
| Need to check deployment timing correlation | `mcp_sherlock_get_deployments(app_name="<service>")` |
| Upstream/downstream service health check | `mcp_sherlock_get_service_dependencies(service_name="<service>")` |
| Full parallel investigation (latency, errors, logs, K8s, alerts combined) | `mcp_sherlock_investigate_service(service_name="<service>")` |
| Synthetic monitor implicated (health check / login flow) | `mcp_sherlock_investigate_synthetic(monitor_name="<monitor>")` |
| Custom NRQL needed for specific metric | `mcp_sherlock_run_nrql_query(nrql="<query>")` — call `mcp_sherlock_get_nrql_context()` first |
| Need to check all open alerts across account | `mcp_sherlock_get_incidents(state="open")` |
| Application performance metrics needed | `mcp_sherlock_get_app_metrics(app_name="<service>")` |

### 3.3. Timing Correlation — CRITICAL

Cross-reference these two timelines:

1. **Deployment timeline** — from `mcp_sherlock_get_deployments` and `hivemind_get_pipeline`
2. **Incident timeline** — from the pasted logs and `mcp_sherlock_get_service_incidents`

Ask explicitly:
- Did the incident start **BEFORE** or **AFTER** the last deployment?
- If AFTER: the deployment is a prime suspect → check image tag, Helm values diff, pipeline config
- If BEFORE: likely a runtime issue → check resource limits, dependencies, secrets expiry

---

## Phase 4 — COMMAND RECOMMENDATIONS

Copilot **CANNOT** run commands. Recommend commands for the user to execute on their jump host.

### 4.1. Format Requirements

Every command recommendation MUST follow this format:

```
### 🔧 Recommended Commands

Run these commands on your jump host and paste the output back:

**1. [Purpose of command]**
```bash
kubectl <exact command>
```
> What this reveals: [one sentence explaining what to look for in output]

**2. [Purpose of command]**
```bash
kubectl <exact command>
```
> What this reveals: [one sentence]
```

### 4.2. Command Playbooks by Incident Type

#### POD — Pod / Container Failures

```bash
# 1. Get pod status and restart count
kubectl get pods -n <namespace> -l app=<service> -o wide

# 2. Describe the failing pod (events, conditions, resource limits)
kubectl describe pod <pod-name> -n <namespace>

# 3. Get previous container logs (the crash that caused the restart)
kubectl logs <pod-name> -n <namespace> --previous --tail=200

# 4. Get current container logs
kubectl logs <pod-name> -n <namespace> --tail=200

# 5. Check resource usage vs limits
kubectl top pod <pod-name> -n <namespace>

# 6. Check node resource pressure
kubectl describe node <node-name> | Select-String -Pattern "Conditions" -Context 0,10
```

#### SECRET — Secret / Config Failures

```bash
# 1. Check if the secret exists in the namespace
kubectl get secret <secret-name> -n <namespace>

# 2. Describe the secret (verify keys, not values)
kubectl describe secret <secret-name> -n <namespace>

# 3. Check CSI driver SecretProviderClass
kubectl get secretproviderclass -n <namespace>

# 4. Describe the SecretProviderClass for KeyVault config
kubectl describe secretproviderclass <spc-name> -n <namespace>

# 5. Check pod events for mount failures
kubectl describe pod <pod-name> -n <namespace> | Select-String -Pattern "Warning|Error|Failed|Mount" -Context 1,3

# 6. Verify managed identity binding
kubectl get azureidentity,azureidentitybinding -n <namespace>
```

#### PROBE — Probe Failures

```bash
# 1. Check probe config on the deployment
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}'

# 2. Check readiness probe config
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}'

# 3. Get events showing probe failures
kubectl get events -n <namespace> --field-selector reason=Unhealthy --sort-by='.lastTimestamp' | Select-Object -Last 20

# 4. Exec into pod to test the probe endpoint manually
kubectl exec -it <pod-name> -n <namespace> -- curl -v http://localhost:<port>/<path>

# 5. Check if the application is still starting (JVM warmup)
kubectl logs <pod-name> -n <namespace> --tail=50 | Select-String -Pattern "Started|Ready|Listening"
```

#### PIPELINE — Pipeline / Deployment Failures

```bash
# 1. Check rollout status
kubectl rollout status deployment/<service> -n <namespace>

# 2. Check rollout history
kubectl rollout history deployment/<service> -n <namespace>

# 3. Get the current image tag
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].image}'

# 4. Check if image exists in ACR
az acr repository show-tags --name <acr-name> --repository <image-name> --orderby time_desc --top 5

# 5. Check for stuck ReplicaSets
kubectl get rs -n <namespace> -l app=<service>
```

#### INFRA — Infrastructure Failures

```bash
# 1. Check node conditions
kubectl get nodes -o wide
kubectl describe node <node-name> | Select-String -Pattern "Conditions" -Context 0,15

# 2. Check PVC status
kubectl get pvc -n <namespace>

# 3. Check network policies
kubectl get networkpolicy -n <namespace>

# 4. Check resource quotas
kubectl describe resourcequota -n <namespace>

# 5. Check cluster events
kubectl get events --all-namespaces --sort-by='.lastTimestamp' | Select-Object -Last 30
```

#### APP — Application Failures

```bash
# 1. Get application logs with error context
kubectl logs <pod-name> -n <namespace> --tail=300 | Select-String -Pattern "Exception|Error|FATAL" -Context 3,5

# 2. Check environment variables (redacted secrets)
kubectl exec <pod-name> -n <namespace> -- env | Sort-Object

# 3. Test connectivity to dependency from inside the pod
kubectl exec -it <pod-name> -n <namespace> -- curl -v http://<dependency-service>:<port>/health

# 4. Check DNS resolution
kubectl exec <pod-name> -n <namespace> -- nslookup <dependency-service>.<namespace>.svc.cluster.local

# 5. Get Spring Boot actuator health (if available)
kubectl exec <pod-name> -n <namespace> -- curl -s http://localhost:<port>/actuator/health | python -m json.tool
```

#### ALERT — Monitoring Alerts

```bash
# 1. Check current pod resource usage
kubectl top pods -n <namespace> --sort-by=memory

# 2. Check HPA status (if autoscaling)
kubectl get hpa -n <namespace>

# 3. Check recent events in namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | Select-Object -Last 20
```

### 4.3. After User Pastes Results

When the user pastes command output back:
1. Parse the output for new signals (resource limits, image tags, event messages)
2. Cross-reference with KB findings from Phase 2
3. Refine the root cause hypothesis
4. Recommend additional commands ONLY if needed
5. Proceed to Phase 5

---

## Phase 5 — ROOT CAUSE SYNTHESIS

### 5.1. Confidence Levels

| Level | Criteria |
|-------|----------|
| **HIGH** | KB evidence + log match + Sherlock correlation. All three data sources agree. |
| **MEDIUM** | Two of three sources agree, or KB has partial match. |
| **LOW** | Single-source hypothesis only. Flag as `⚠️ HYPOTHESIS — needs validation`. |

### 5.2. Root Cause Categories

Classify the root cause into exactly ONE category:

| Category | Description | Examples |
|----------|-------------|----------|
| **APP_BUG** | Application code defect | NullPointerException, unhandled exception, logic error |
| **CONFIG_ERROR** | Misconfiguration in Helm values, env vars, or secrets | Wrong port, missing env var, incorrect secret path |
| **INFRA_ISSUE** | Infrastructure resource problem | Node pressure, PVC full, network policy blocking |
| **DEPENDENCY_FAILURE** | Upstream or downstream service failure causing cascading impact | Database down, shared service timeout, DNS failure |
| **DEPLOYMENT_ERROR** | Bad deployment (wrong image, failed rollout, missing config in new release) | Image tag mismatch, Helm values regression, pipeline misconfiguration |
| **SECRET_EXPIRY** | Credential rotation or KeyVault access issue | Expired secret, managed identity permission change, KV access policy |
| **RESOURCE_EXHAUSTION** | CPU/memory limits too low or leak | OOMKilled (limit too low), CPU throttling, connection pool exhaustion |

### 5.3. Origin vs Victim Analysis

For EVERY multi-service incident, explicitly answer:

```
🔍 ORIGIN vs VICTIM ANALYSIS:
- Service A: [ORIGIN / VICTIM / UNKNOWN]
  Evidence: <what proves this>
- Service B: [ORIGIN / VICTIM / UNKNOWN]
  Evidence: <what proves this>
- Cascade direction: A → B → C
```

Use `hivemind_impact_analysis` dependency chain + `mcp_sherlock_get_service_dependencies` to determine cascade direction. The service whose errors appear FIRST in the timeline is the likely origin.

### 5.4. Things That Are Never Root Cause

Do NOT declare root cause as:
- "Unknown" — without exhausting KB + Sherlock + command results
- "Network issues" — without checking network policies and DNS
- "Kubernetes issue" — without specifying WHICH K8s component
- "Configuration issue" — without specifying WHICH config key in WHICH file

---

## Phase 6 — REMEDIATION PLAN

Every remediation plan MUST have three sections: Immediate Mitigation, Permanent Fix, and Rollback Path.

### 6.1. Immediate Mitigation

Stop the bleeding. Recommend commands the user can run NOW:

| Incident Type | Immediate Action |
|---------------|------------------|
| `POD` — OOMKilled | Recommend increasing memory limit in Helm values. Cite the exact `values.yaml` file path from KB. |
| `POD` — CrashLoopBackOff | Recommend checking previous logs, then `kubectl rollout undo` if deployment-related. |
| `SECRET` — mount failure | Recommend verifying secret exists: `kubectl get secret`. Check SecretProviderClass. |
| `PROBE` — timeout | Recommend increasing `initialDelaySeconds` in Helm values. Cite exact file. |
| `PIPELINE` — stuck rollout | Recommend `kubectl rollout undo deployment/<service> -n <namespace>`. |
| `INFRA` — node pressure | Recommend cordoning node: `kubectl cordon <node>`. Check for pod eviction. |
| `APP` — dependency timeout | Recommend checking dependency health. Increase timeout in app config if safe. |

### 6.2. Permanent Fix

Reference specific files from the KB:

```
📋 **Permanent Fix:**
1. Modify `<file_path>` [repo: <repo>, branch: <branch>]
   - Change: `<specific key>` from `<old_value>` to `<new_value>`
   - Reason: <why this fixes the root cause>

2. Update pipeline `<pipeline_name>` [repo: <repo>, branch: <branch>]
   - Change: <what to change in the pipeline>

3. Verify fix:
   - Deploy to <lower environment> first
   - Monitor golden signals via Sherlock for 30 minutes
   - Confirm no regressions in dependency chain
```

If the fix requires a file change and the user approves, use `hivemind_write_file` to stage the change on a working branch (NEVER directly on a protected branch — see Branch Protection rules).

### 6.3. Rollback Path

**ALWAYS** provide a rollback path. NEVER skip this section.

```
🔄 **Rollback Path:**
1. Harness rollback: <pipeline name> → trigger rollback stage
   OR
   kubectl rollout undo deployment/<service> -n <namespace> --to-revision=<N>

2. Previous known-good image: <image:tag from KB or Sherlock deployments>

3. Verification after rollback:
   - kubectl get pods -n <namespace> -l app=<service>
   - Check golden signals via Sherlock
   - Confirm upstream/downstream services recovered
```

---

## Incident Type Playbooks

### Playbook 1 — POD: CrashLoopBackOff / OOMKilled / ImagePullBackOff / Evicted

**Likely causes** (ranked by frequency on Java/Spring microservice platforms):
1. OOMKilled — JVM heap + metaspace exceeds container memory limit
2. CrashLoopBackOff — application fails to start (missing config, dependency unreachable, bean init failure)
3. ImagePullBackOff — wrong image tag, ACR auth failure, image doesn't exist
4. Evicted — node under DiskPressure or MemoryPressure

**First 3 HiveMind tools:**
1. `hivemind_query_memory(query="<service> helm values resources limits")` — find memory/CPU limits
2. `hivemind_get_entity(name="<service>")` — get service metadata and repos
3. `hivemind_impact_analysis(entity="<service>")` — check downstream blast radius

**First 3 Sherlock tools:**
1. `mcp_sherlock_get_k8s_health(service_name="<service>")` — pod/container status from NR
2. `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — error rate spike?
3. `mcp_sherlock_search_logs(service_name="<service>", severity="ERROR")` — recent errors

**First 3 kubectl commands to recommend:**
1. `kubectl describe pod <pod> -n <ns>` — events, conditions, resource limits
2. `kubectl logs <pod> -n <ns> --previous --tail=200` — crash logs
3. `kubectl top pod <pod> -n <ns>` — actual resource usage

**Common gotchas (Harness + Azure):**
- ACR image pull requires `imagePullSecrets` — check Helm values for `imagePullSecrets` config
- AKS kubelet reserves memory — actual allocatable is less than node capacity
- Harness may deploy an image tag that hasn't finished building in ACR
- JVM `-Xmx` set in `JAVA_TOOL_OPTIONS` env var may conflict with container memory limit

---

### Playbook 2 — SECRET: KeyVault Mount Failures / Missing Env Vars

**Likely causes:**
1. KeyVault secret does not exist or was recently rotated
2. Managed identity lacks `GET` permission on KeyVault access policy
3. SecretProviderClass references wrong KeyVault name or secret name
4. Terraform hasn't been applied to create the secret in the target environment
5. Helm values missing the secret mount or env var injection

**First 3 HiveMind tools:**
1. `hivemind_get_secret_flow(secret="<secret_name>")` — trace KV → K8s → Helm → Pod
2. `hivemind_query_memory(query="<secret_name> keyvault terraform")` — find TF definition
3. `hivemind_impact_analysis(entity="<service>")` — what else uses this secret?

**First 3 Sherlock tools:**
1. `mcp_sherlock_search_logs(service_name="<service>", keyword="secret|KeyVault|mount|permission")` — mount error logs
2. `mcp_sherlock_get_k8s_health(service_name="<service>")` — pod events with mount failures
3. `mcp_sherlock_get_service_incidents(service_name="<service>")` — correlated alerts

**First 3 kubectl commands to recommend:**
1. `kubectl describe pod <pod> -n <ns>` — look for `MountVolume.SetUp failed` events
2. `kubectl get secretproviderclass -n <ns> -o yaml` — verify KV config
3. `kubectl get secret <secret> -n <ns>` — verify K8s secret exists

**Common gotchas (Harness + Azure):**
- KeyVault soft-delete means a deleted secret blocks re-creation with same name
- Managed identity binding must be in the SAME namespace as the pod
- Terraform `azurerm_key_vault_secret` and `azurerm_key_vault_access_policy` must be in the same layer
- Harness variable overrides can shadow Helm secret mounts

---

### Playbook 3 — PROBE: Liveness / Readiness Probe Failures

**Likely causes:**
1. JVM warmup takes longer than `initialDelaySeconds` (Spring Boot with many beans)
2. Probe path or port doesn't match what the application actually serves
3. Application stuck in GC pause or thread deadlock
4. Dependency health check fails (probe calls `/actuator/health` which checks downstream)
5. Readiness probe too aggressive — removes pod from service during minor GC

**First 3 HiveMind tools:**
1. `hivemind_query_memory(query="<service> probes readiness liveness")` — find probe config in Helm values
2. `hivemind_get_entity(name="<service>")` — get deployment config
3. `hivemind_impact_analysis(entity="<service>")` — is a dependency causing health check failure?

**First 3 Sherlock tools:**
1. `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — latency spike = slow startup
2. `mcp_sherlock_get_k8s_health(service_name="<service>")` — container restart events
3. `mcp_sherlock_search_logs(service_name="<service>", keyword="health|actuator|probe|Started")` — startup timing

**First 3 kubectl commands to recommend:**
1. `kubectl get deployment <svc> -n <ns> -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}'` — probe config
2. `kubectl get events -n <ns> --field-selector reason=Unhealthy` — probe failure events
3. `kubectl logs <pod> -n <ns> --tail=100` — check for "Started" log to measure startup time

**Common gotchas (Harness + Azure):**
- Spring Boot 3.x startup probes should use `/actuator/health/liveness` not `/actuator/health`
- AKS load balancer health probe is SEPARATE from K8s readiness probe
- `initialDelaySeconds` in Helm values may be overridden by Harness variable expressions
- Actuator `/health` with `show-details=always` may fail if ANY downstream dependency is unhealthy

---

### Playbook 4 — PIPELINE: Harness Stage Failures / Stuck Rollouts

**Likely causes:**
1. Image tag variable not resolved — Harness expression `<+artifact.tag>` returns empty
2. Approval stage timed out or was rejected
3. Helm upgrade failed — values file has syntax error or missing required key
4. Canary/rolling update stuck — new pods failing health checks
5. Harness delegate lost connectivity to AKS cluster

**First 3 HiveMind tools:**
1. `hivemind_get_pipeline(name="<pipeline_name>")` — full pipeline structure and stages
2. `hivemind_query_memory(query="<service> harness deploy pipeline")` — related pipeline configs
3. `hivemind_impact_analysis(entity="<service>")` — what does this deployment affect?

**First 3 Sherlock tools:**
1. `mcp_sherlock_get_deployments(app_name="<service>")` — recent deployment history from NR
2. `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — error rate after deploy
3. `mcp_sherlock_get_service_incidents(service_name="<service>")` — alerts triggered by deploy

**First 3 kubectl commands to recommend:**
1. `kubectl rollout status deployment/<svc> -n <ns>` — is rollout progressing?
2. `kubectl rollout history deployment/<svc> -n <ns>` — revision history
3. `kubectl get rs -n <ns> -l app=<svc>` — check for stuck ReplicaSets

**Common gotchas (Harness + Azure):**
- Harness `templateRef` must match the exact template name and version — check with `get_pipeline`
- ACR webhook triggers may fire before the image push is complete
- Harness variable expressions resolve at runtime — a missing variable silently becomes empty string
- AKS cluster with private endpoint requires Harness delegate in the same VNET

---

### Playbook 5 — INFRA: Terraform Drift / Node Pressure / PVC / Network Policy

**Likely causes:**
1. Node under MemoryPressure or DiskPressure — pods evicted
2. PVC stuck in Pending — storage class doesn't exist or quota exceeded
3. NetworkPolicy blocking inter-service traffic
4. Terraform drift — manual changes made outside of IaC
5. AKS node pool auto-scaler max reached

**First 3 HiveMind tools:**
1. `hivemind_query_memory(query="<resource> terraform aks")` — find TF definition
2. `hivemind_search_files(query="<resource>.tf")` — locate exact TF file
3. `hivemind_impact_analysis(entity="<resource>")` — what depends on this infra?

**First 3 Sherlock tools:**
1. `mcp_sherlock_get_k8s_health(namespace="<namespace>")` — node/pod health
2. `mcp_sherlock_get_incidents(state="open")` — infra-level alerts
3. `mcp_sherlock_run_nrql_query(nrql="SELECT ... FROM K8sNodeSample ...")` — node metrics

**First 3 kubectl commands to recommend:**
1. `kubectl get nodes -o wide` — node status
2. `kubectl describe node <node>` — conditions, allocatable resources, taints
3. `kubectl get events --all-namespaces --field-selector reason=Evicted` — eviction events

**Common gotchas (Harness + Azure):**
- AKS system node pool has reserved resources — check `allocatable` not `capacity`
- Azure Disk PVCs are zone-pinned — pod must schedule in same zone
- Terraform state lock can cause drift if two pipelines apply simultaneously
- NSG rules on AKS subnet can silently break pod networking

---

### Playbook 6 — APP: Spring Boot Failures / Dependency Timeouts

**Likely causes:**
1. `BeanCreationException` — missing dependency bean or circular reference
2. Connection refused/timeout to database, cache, or downstream service
3. JDBC connection pool exhausted (HikariCP `connectionTimeout`)
4. Thread pool exhaustion on async service calls
5. ClassNotFoundException after dependency version bump (Spring Boot auto-config)

**First 3 HiveMind tools:**
1. `hivemind_query_memory(query="<service> configuration application properties")` — app config
2. `hivemind_get_entity(name="<service>")` — service metadata, dependencies
3. `hivemind_get_secret_flow(secret="<service>-db-connection")` — database credential chain

**First 3 Sherlock tools:**
1. `mcp_sherlock_investigate_service(service_name="<service>")` — full parallel investigation
2. `mcp_sherlock_get_service_dependencies(service_name="<service>")` — upstream/downstream health
3. `mcp_sherlock_search_logs(service_name="<service>", severity="ERROR", keyword="Exception|timeout|refused")` — error logs

**First 3 kubectl commands to recommend:**
1. `kubectl logs <pod> -n <ns> --tail=300` — full startup/error log
2. `kubectl exec <pod> -n <ns> -- curl -s http://localhost:<port>/actuator/health` — health details
3. `kubectl exec <pod> -n <ns> -- curl -v http://<dependency>:<port>/health` — test dependency

**Common gotchas (Harness + Azure):**
- Azure SQL firewall rules may block AKS pod IPs if VNET integration isn't configured
- Spring Boot actuator health shows `DOWN` if ANY dependency check group fails
- Connection strings in KeyVault may reference internal DNS names not resolvable from new AKS clusters
- Hikari pool default is 10 — may need increase for high-traffic services

---

### Playbook 7 — ALERT: New Relic NRQL Conditions / Missing Golden Signals

**Likely causes:**
1. NRQL alert condition threshold breached (error rate, latency, throughput drop)
2. Agent reporting gap — New Relic APM agent stopped reporting
3. Synthetic monitor failure — external endpoint unreachable
4. Alert condition misconfigured — threshold too sensitive or missing baseline
5. Golden signals missing — service not instrumented or agent crash

**First 3 HiveMind tools:**
1. `hivemind_query_memory(query="<service> monitoring alert NRQL")` — find alert config in KB
2. `hivemind_get_entity(name="<service>")` — service metadata
3. `hivemind_impact_analysis(entity="<service>")` — blast radius of degraded service

**First 3 Sherlock tools:**
1. `mcp_sherlock_get_service_incidents(service_name="<service>")` — active incidents
2. `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — current golden signals
3. `mcp_sherlock_get_alerts()` — all alert policies and conditions

**First 3 kubectl commands to recommend:**
1. `kubectl get pods -n <ns> -l app=<service>` — are pods running?
2. `kubectl top pods -n <ns> -l app=<service>` — resource usage
3. `kubectl logs <pod> -n <ns> --tail=50` — check for agent errors

**Common gotchas (Harness + Azure):**
- New Relic Java agent logs to container stdout — check for `com.newrelic` ERROR entries
- NRQL `SINCE` clause in alert conditions uses sliding windows — check evaluation offset
- AKS pod restarts reset the NR agent — creates gaps in reporting
- Alert conditions on `Metric` vs `Transaction` event types behave differently for percentiles

---

## Escalation Criteria

### Escalate to Human Immediately (Page On-Call)

| Condition | Action |
|-----------|--------|
| **Data loss risk** — database corruption, persistent volume failure, backup failure | Page on-call + DBA. Do NOT attempt automated fix. |
| **Security breach** — unauthorized access, leaked credentials, suspicious API calls | Page on-call + security team. Recommend immediate secret rotation. |
| **>3 services impacted** — cascading failure across dependency chain | Page on-call. This is a platform incident, not a service incident. |
| **Customer-facing 5xx >5 minutes** — production traffic affected | Page on-call. Recommend immediate rollback while investigating. |
| **Complete namespace or cluster failure** — multiple unrelated services down | Page on-call + infra team. Likely node/network level issue. |

### Handle Asynchronously (Ticket, No Page)

| Condition | Action |
|-----------|--------|
| Single pod restart with auto-recovery | Create ticket. Monitor for recurrence. |
| Non-production environment failure | Create ticket. Investigate during business hours. |
| Alert condition flapping (resolved within 2 minutes) | Create ticket. Review alert threshold sensitivity. |
| Known issue with documented workaround | Apply workaround. Create ticket for permanent fix. |

### Rollback Decision Matrix

| Condition | Action |
|-----------|--------|
| Bad deployment confirmed (image/config regression) | **Harness rollback pipeline** — trigger rollback stage with previous known-good artifact. |
| Rollback pipeline unavailable or broken | **kubectl rollout undo** — manual rollback to previous revision. |
| Rollback won't help (infra/secret issue) | **Do NOT rollback** — fix the root cause. Rollback wastes time for non-deployment issues. |
| Partial rollback needed (one service of many) | **kubectl rollout undo** on specific service only. Verify dependency compatibility. |

---

## Output Format — TRIAGE REPORT

Every triage response MUST use this exact structure:

```
## 🚨 TRIAGE REPORT — Automatic Investigation

### Incident Classification
| Field | Value |
|-------|-------|
| Type | <POD / SECRET / PROBE / PIPELINE / INFRA / APP / ALERT> |
| Service | <extracted service name> |
| Namespace | <namespace or "not specified"> |
| Error Type | <specific error class> |
| Blast Radius | <SINGLE_POD / SINGLE_SERVICE / MULTI_SERVICE / CLUSTER_WIDE> |
| Severity | <CRITICAL / HIGH / MEDIUM / LOW> |
| Time Range | <timestamps from logs or "not specified"> |

### KB Findings (HiveMind)

**hivemind-investigator**
  📋 Finding: <what was found in KB>
  📁 Sources:
    - `<file_path>` [repo: <repo>, branch: <branch>]

**hivemind-{specialist}** (consulted by hivemind-investigator)
  📋 Finding: <specialist findings>
  📁 Sources:
    - `<file_path>` [repo: <repo>, branch: <branch>]

### Observability Findings (Sherlock / New Relic)

| Signal | Value | Status |
|--------|-------|--------|
| Error Rate | <value> | 🔴 / 🟡 / 🟢 |
| Latency (p99) | <value> | 🔴 / 🟡 / 🟢 |
| Throughput | <value> | 🔴 / 🟡 / 🟢 |
| Pod Restarts | <count> | 🔴 / 🟡 / 🟢 |
| Active Alerts | <list> | — |
| Last Deployment | <timestamp + version> | — |

### Dependency Chain
<output from hivemind_impact_analysis + mcp_sherlock_get_service_dependencies>
- Upstream: <services that call this service>
- Downstream: <services this service calls>
- 🔍 Origin vs Victim: <analysis>

### Recommended Commands
<numbered, copy-paste ready commands per Phase 4>

### Root Cause Hypothesis
📋 **Category:** <APP_BUG / CONFIG_ERROR / INFRA_ISSUE / DEPENDENCY_FAILURE / DEPLOYMENT_ERROR / SECRET_EXPIRY / RESOURCE_EXHAUSTION>
📋 **Hypothesis:** <specific root cause statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - `<file1>` — <what this file shows>
  - `<file2>` — <what this file shows>
  - Sherlock: <what live telemetry confirms>

### Remediation Plan

**🔥 Immediate Mitigation:**
1. <command or action to stop the bleeding>

**🔧 Permanent Fix:**
1. Modify `<file_path>` [repo: <repo>, branch: <branch>]
   - Change: <what to change>
   - Reason: <why>

**🔄 Rollback Path:**
1. <exact rollback command or pipeline>
2. Verification: <how to confirm rollback succeeded>

### Escalation
<NONE / ASYNC_TICKET / PAGE_ONCALL — with reason>

---
## All Sources
| Source | Agent/Tool | File / Query | Repo | Branch |
|--------|-----------|--------------|------|--------|
| KB | hivemind-investigator | <file1> | <repo> | <branch> |
| KB | hivemind-{specialist} | <file2> | <repo> | <branch> |
| Live | Sherlock | <tool_name>(<params>) | — | — |
| Cmd | User | <kubectl command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```

---

## Graceful Degradation

| Condition | Required Behavior |
|-----------|-------------------|
| Service name NOT extractable | Use strongest signal (namespace, pod prefix, image name). State: `"⚠️ Service name inferred as '<name>' from <signal>. Correct me if wrong."` |
| Service NOT in HiveMind KB | State: `"NOT IN KNOWLEDGE BASE — searched for: <name>. Queries: <list>."` Continue with Sherlock + commands only. Set confidence to LOW. |
| Service NOT in Sherlock / New Relic | State: `"⚠️ Service not found in New Relic. Not instrumented or different name."` Continue with KB + commands only. |
| Both KB and Sherlock miss | State: `"⚠️ Service not found in KB or New Relic."` Recommend commands only. Set confidence to LOW. |
| Logs are ambiguous / multi-service | Run `hivemind_query_memory` AND `mcp_sherlock_investigate_service` for EACH candidate. Present all findings ranked. |
| KB returns partial results | Present what was found with `🎯 Confidence: MEDIUM`. List missing items: `"⚠️ Missing from KB: <expected but not found>."` |
| Multiple root cause candidates | Present each as numbered hypothesis with own confidence + evidence. Do NOT pick one without evidence. |
| Sherlock tool call fails | Log failure, continue with remaining phases. Note: `"⚠️ Sherlock <tool_name> failed — <error>. Live telemetry incomplete."` |
| HiveMind tool call fails | Log failure, continue with remaining phases. Note: `"⚠️ HiveMind <tool_name> failed — <error>. KB data incomplete."` |
| User does not paste command output | Proceed with KB + Sherlock findings. State: `"⚠️ Awaiting command output for higher-confidence diagnosis."` |

````