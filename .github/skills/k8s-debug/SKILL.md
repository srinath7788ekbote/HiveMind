---
name: k8s-debug
description: >
  Deep Kubernetes investigation skill for AKS platform. The second-level
  deep-dive layer invoked after incident-triage identifies the pod, container,
  node, or workload as the problem domain. Covers pod lifecycle, container
  diagnosis, node health, networking, storage, workload rollouts, and
  AKS-specific failure modes on a 50+ Spring Boot Java microservice platform.
triggers:
  - pod
  - container
  - kubectl
  - namespace
  - node
  - deployment
  - statefulset
  - daemonset
  - replicaset
  - CrashLoopBackOff
  - OOMKilled
  - Pending
  - Evicted
  - Terminating
  - ImagePullBackOff
  - ContainerCreating
  - mount
  - PVC
  - ingress
  - HPA
  - rollout
  - node pressure
  - taint
  - toleration
  - endpoint
  - DNS
  - network policy
  - cordon
  - drain
  - NotReady
  - MemoryPressure
  - DiskPressure
  - PIDPressure
  - init container
  - sidecar
  - CSI driver
  - SecretProviderClass
  - imagePullSecret
  - Azure CNI
  - spot instance
  - AKS
  - node pool
  - managed identity
  - workload identity
slash_command: /k8s
---

# Kubernetes Deep-Dive Debug — AKS Operations Playbook

> This skill is the DEEP investigation layer for Kubernetes failures. It is
> activated after `incident-triage` classifies the problem domain as pod,
> container, node, network, storage, or workload. Follow the decision tree
> first, then execute the matching investigation layer top to bottom.
> Skip nothing. Recommend every command — never run them.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| K-1 | **NEVER run commands.** User is on AVD via jump host. Recommend every `kubectl`, `helm`, `az` command. Wait for paste-back. |
| K-2 | **NEVER skip `hivemind_impact_analysis`.** A failing pod is often a downstream victim — always check the dependency chain. |
| K-3 | **NEVER assume the first failing pod is the root cause service.** Check upstream dependencies before concluding. |
| K-4 | **NEVER block on Sherlock.** If Sherlock is unavailable or returns no data, fall back to kubectl commands immediately (see Sherlock Fallback Rule). |
| K-5 | **ALWAYS check for recent deployments** — via Sherlock (Path A) or `kubectl rollout history` (Path B). Deployments cause >60% of pod failures. |
| K-6 | **ALWAYS provide the next command to run** based on what the previous output showed. Never leave the user without a next step. |
| K-7 | **Commands MUST be copy-paste ready** with clear `<placeholder>` markers for values the user fills in. |
| K-8 | **NEVER answer from training data** when HiveMind KB or Sherlock has relevant results. |
| K-9 | **ALWAYS cite file path + repo + branch** for every KB finding. Search ALL indexed repos for the active client, not just one. |
| K-10 | **ALWAYS ask:** "Is this pod the origin or a downstream victim?" |
| K-11 | **NEVER stage or write files.** When root cause is found, provide the exact file path + repo + branch + what to change. The user makes all changes. |

---

## 🔄 SHERLOCK FALLBACK RULE — CRITICAL

The investigation MUST continue regardless of Sherlock availability. Two paths exist:

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use Sherlock data, correlate with KB findings, proceed |
| **Path B** | Sherlock unavailable, times out, or returns no useful data | Fall back to kubectl/az commands immediately, proceed |

### Rules

- NEVER say "I cannot continue without Sherlock"
- NEVER pause or block the investigation waiting for Sherlock
- If Path B: mark the observability section as `"⚠️ Sherlock unavailable — proceeding with command-based investigation"` and continue seamlessly
- Path B fallback commands are listed in each investigation layer below

### Path B Fallback Commands (per layer)

| Layer | Path A (Sherlock) | Path B Fallback (kubectl) |
|-------|-------------------|--------------------------|
| Layer 1 — Pod Health | `mcp_sherlock_get_k8s_health`, `mcp_sherlock_get_service_golden_signals` | `kubectl top pod <pod> -n <ns>` |
| Layer 2 — Container | `mcp_sherlock_search_logs`, `mcp_sherlock_get_app_metrics` | `kubectl logs <pod> -n <ns> --tail=200` |
| Layer 3 — Workload | `mcp_sherlock_get_deployments`, `mcp_sherlock_get_service_golden_signals` | `kubectl rollout history deployment/<svc> -n <ns>` |
| Layer 4 — Node | `mcp_sherlock_run_nrql_query` (K8sNodeSample) | `kubectl top nodes`, `kubectl describe node <node>` |
| Layer 5 — Networking | `mcp_sherlock_get_service_dependencies`, `mcp_sherlock_search_logs` | `kubectl exec <pod> -n <ns> -- curl -sv <target>` |
| Layer 6 — Storage | `mcp_sherlock_get_k8s_health` | `kubectl describe pvc <name> -n <ns>`, `kubectl get events -n <ns>` |
| Metrics | `mcp_sherlock_get_service_golden_signals`, `mcp_sherlock_get_app_metrics` | `kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/<ns>/pods` |

---

## Decision Tree — START HERE

Read the pod status and follow the matching branch. Every branch leads to an investigation layer and a first command.

```
POD STATUS
│
├── Pending
│   ├── Events: "FailedScheduling ... insufficient cpu/memory"
│   │   → LAYER 4 (Node) → First cmd: kubectl describe node <node>
│   │   └── Check: resource quotas, node capacity, autoscaler maxCount
│   ├── Events: "FailedScheduling ... didn't match Pod's node affinity/selector"
│   │   → LAYER 4 (Node) → First cmd: kubectl get nodes --show-labels
│   │   └── Check: nodeSelector, tolerations, affinity rules in Helm values
│   ├── Events: "FailedScheduling ... had taint ... that the pod didn't tolerate"
│   │   → LAYER 4 (Node) → First cmd: kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
│   │   └── Check: spot instance taint, system pool taint, custom taints
│   ├── PVC not bound
│   │   → LAYER 6 (Storage) → First cmd: kubectl describe pvc <name> -n <ns>
│   │   └── Check: StorageClass, Azure Disk zone, provisioner health
│   └── Image pull backoff
│       → LAYER 2 (Container) → First cmd: kubectl describe pod <pod> -n <ns>
│       └── Check: ACR auth, image tag existence, imagePullSecrets
│
├── CrashLoopBackOff
│   ├── Exit code 1 → App error
│   │   → LAYER 2 (Container) → First cmd: kubectl logs <pod> -n <ns> --previous --tail=300
│   │   └── Check: stack trace, missing config, dependency connection failure
│   ├── Exit code 137 (SIGKILL) → OOMKilled
│   │   → LAYER 2 (Container) → First cmd: kubectl describe pod <pod> -n <ns>
│   │   └── Check: Last State → OOMKilled, resource limits, JVM flags
│   ├── Exit code 143 (SIGTERM) → Graceful shutdown exceeded
│   │   → LAYER 3 (Workload) → First cmd: kubectl logs <pod> -n <ns> --previous --tail=100
│   │   └── Check: terminationGracePeriodSeconds vs Spring shutdown hook
│   └── Exit code 0 with restarts → App completes but K8s restarts
│       → LAYER 2 (Container) → First cmd: kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.restartPolicy}'
│       └── Check: missing command/args, process exits immediately
│
├── OOMKilled
│   └── Always → LAYER 2 (Container) → First cmd: kubectl describe pod <pod> -n <ns>
│       ├── JVM heap (-Xmx) + metaspace + native > container memory limit
│       ├── Native memory leak (off-heap) — grows linearly
│       └── Container limit genuinely too low for workload
│
├── ImagePullBackOff
│   └── Always → LAYER 2 (Container) → First cmd: kubectl describe pod <pod> -n <ns>
│       ├── Image tag doesn't exist in ACR
│       ├── ACR auth: imagePullSecrets missing or expired
│       ├── ACR name wrong (different per environment)
│       └── AKS managed identity not assigned AcrPull role
│
├── Evicted
│   └── Always → LAYER 4 (Node) → First cmd: kubectl describe node <node>
│       ├── Node DiskPressure or MemoryPressure
│       ├── Spot instance reclaimed by Azure
│       └── Ephemeral storage limit exceeded
│
├── Terminating (stuck)
│   ├── Finalizer not being removed
│   │   → LAYER 3 (Workload) → First cmd: kubectl get pod <pod> -n <ns> -o jsonpath='{.metadata.finalizers}'
│   ├── Volume unmount hanging
│   │   → LAYER 6 (Storage) → First cmd: kubectl describe pod <pod> -n <ns>
│   └── preStop hook timeout
│       → LAYER 3 (Workload) → First cmd: kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.containers[0].lifecycle}'
│
├── ContainerCreating (stuck)
│   ├── Secret mount failing → KeyVault CSI
│   │   → LAYER 6 (Storage) → First cmd: kubectl describe pod <pod> -n <ns>
│   ├── ConfigMap not found
│   │   → LAYER 2 (Container) → First cmd: kubectl get configmap -n <ns>
│   └── Init container stuck
│       → LAYER 2 (Container) → First cmd: kubectl logs <pod> -n <ns> -c <init-container>
│
├── Running but errors in logs
│   ├── Connection refused to dependency → LAYER 5 (Networking)
│   ├── Timeout to external service → LAYER 5 (Networking)
│   ├── Exception / stack trace → LAYER 2 (Container)
│   └── Probe failures in Events → LAYER 2 (Container, section 2.6)
│
├── Error (generic)
│   ├── Init container failure → LAYER 2 (Container, section 2.5)
│   └── Entrypoint or command missing → LAYER 2 (Container)
│
└── Unknown status
    → First cmd: kubectl describe pod <pod> -n <ns>
    → Read Events section → re-enter this tree with specific status
```

---

## LAYER 1 — POD HEALTH (Always Start Here)

### Commands to Recommend (in order)

**1. Get pod status overview**
```bash
kubectl get pods -n <namespace> -l app=<service> -o wide
```
> **Look for:** STATUS column, RESTARTS count, AGE, NODE assignment, READY column (e.g., 0/1 = not ready). If multiple pods show different states = workload-level issue, go to Layer 3.

**2. Describe the failing pod**
```bash
kubectl describe pod <pod-name> -n <namespace>
```
> **Look for:** See [Command Output Interpretation — describe pod](#interpret-describe-pod) below. This is the single most information-dense output.

**3. Get previous container logs (if RESTARTS > 0)**
```bash
kubectl logs <pod-name> -n <namespace> --previous --tail=300
```
> **Look for:** Stack trace (Spring Boot `BeanCreationException`, `ConnectException`, `OutOfMemoryError`), the LAST lines before exit, any `FATAL` or `Error` log lines. The `--previous` flag shows the crashed container's output — this is where the crash reason lives.

**4. Get current container logs**
```bash
kubectl logs <pod-name> -n <namespace> --tail=200
```
> **Look for:** Startup progress (search for "Started" or "JVM running for"), current ERROR lines, probe endpoint responses, retrying connection messages.

**5. Check resource usage (if pod is Running)**
```bash
kubectl top pod <pod-name> -n <namespace>
```
> **Look for:** Memory usage near limit = imminent OOM. CPU at limit = throttling (latency spikes).

### KB Cross-Reference (Layer 1)

Call these HiveMind tools in this order. Search ALL repos for the active client.

```
STEP 1: hivemind_get_active_client()
STEP 2: hivemind_get_entity(client=<client>, name="<service>")
        → Full metadata: repos, environments, dependencies
STEP 3: hivemind_impact_analysis(client=<client>, entity="<service>")
        → MANDATORY — upstream/downstream dependency chain
STEP 4: hivemind_query_memory(client=<client>, query="<service> helm values deployment")
        → Find Helm values with pod spec, probes, resources, env vars
```

### Sherlock Correlation (Layer 1)

**Path A (Sherlock available):**

| Data Needed | Sherlock Tool |
|-------------|---------------|
| Pod/container health from NR | `mcp_sherlock_get_k8s_health(service_name="<service>")` |
| Error rate, latency, throughput | `mcp_sherlock_get_service_golden_signals(service_name="<service>")` |
| Recent deployment timing | `mcp_sherlock_get_deployments(app_name="<service>")` |
| Error logs from NR | `mcp_sherlock_search_logs(service_name="<service>", severity="ERROR")` |
| Active alerts | `mcp_sherlock_get_service_incidents(service_name="<service>")` |

**Path B (Sherlock unavailable) — recommend these commands instead:**
```bash
# Pod resource metrics
kubectl top pod <pod-name> -n <namespace>

# Check recent rollout (deployment timing proxy)
kubectl rollout history deployment/<service> -n <namespace>

# Recent events as incident timeline
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -30
```
State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## LAYER 2 — CONTAINER DIAGNOSIS

### 2.1. Image Pull Issues

**Commands:**
```bash
# 1. Check image name and tag on the deployment
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].image}'

# 2. Check imagePullSecrets configured
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.imagePullSecrets}'

# 3. Verify image exists in ACR
az acr repository show-tags --name <acr-name> --repository <image-name> --orderby time_desc --top 10

# 4. Check pull secret content (verify registry URL)
kubectl get secret <pull-secret-name> -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```

**Root causes (ranked by frequency):**
1. Image tag does not exist in ACR — Harness pipeline pushed to wrong registry or build failed mid-push
2. `imagePullSecrets` not configured in Helm values — missing from `values.yaml`
3. AKS managed identity not assigned `AcrPull` role on the ACR resource
4. ACR name differs per environment — wrong registry in Helm override for this env

**KB tools:**
- `hivemind_query_memory(client=<client>, query="<service> image pull ACR imagePullSecrets")` — check Helm values
- `hivemind_get_pipeline(client=<client>, name="<deploy-pipeline>")` — check what image tag the pipeline pushes

### 2.2. Resource Limits — OOMKilled / CPU Throttling

**Commands:**
```bash
# 1. Check configured limits
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].resources}' | python -m json.tool

# 2. Check actual usage
kubectl top pod <pod-name> -n <namespace>

# 3. Check OOMKilled events
kubectl get events -n <namespace> --field-selector reason=OOMKilling --sort-by='.lastTimestamp'

# 4. Check JVM flags (Spring Boot)
kubectl exec <pod-name> -n <namespace> -- env | grep -i "java\|jvm\|heap\|xmx\|xms\|JAVA_TOOL_OPTIONS"
```

**Root causes (ranked):**
1. JVM heap (`-Xmx`) + metaspace + native memory > container `resources.limits.memory`
2. Container limit set too low for the workload
3. Memory leak — usage grows linearly until OOM (check NR or `kubectl top` over time)
4. `requests` set equal to `limits` with no headroom for GC spikes

**Critical formula for JVM containers on this platform:**
```
Container memory limit >= Heap (-Xmx) + Metaspace (256MB typical) + Native (200-400MB) + 100MB buffer

Example: -Xmx512m needs at minimum 1068Mi container limit (use 1.5Gi for safety)
```

**KB tools:**
- `hivemind_query_memory(client=<client>, query="<service> resources limits memory helm")` — find Helm values file
- `hivemind_query_memory(client=<client>, query="<service> JAVA_TOOL_OPTIONS Xmx")` — find JVM flags

**Sherlock Path A:** `mcp_sherlock_get_app_metrics(app_name="<service>")` — memory trend over time
**Sherlock Path B:**
```bash
kubectl top pod <pod-name> -n <namespace> --containers
```

### 2.3. Environment Variables & ConfigMaps

**Commands:**
```bash
# 1. List all env vars on the pod (redacted secrets show as <set to:>)
kubectl set env deployment/<service> -n <namespace> --list

# 2. Check configmap existence
kubectl get configmap -n <namespace>

# 3. Describe configmap contents
kubectl describe configmap <configmap-name> -n <namespace>

# 4. Check env var source references in deployment spec
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].env}' | python -m json.tool

# 5. Check envFrom references (bulk-loaded from configmap/secret)
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].envFrom}' | python -m json.tool
```

**Root causes:**
1. Environment variable references a Secret or ConfigMap that doesn't exist in this namespace
2. ConfigMap key name changed but deployment spec not updated
3. Harness variable override shadowing a Helm-defined env var
4. `SPRING_PROFILES_ACTIVE` not set or set to wrong profile

**KB tools:**
- `hivemind_query_memory(client=<client>, query="<service> environment variables configmap")` — Helm values
- `hivemind_get_secret_flow(client=<client>, secret="<secret-ref>")` — if env var references a secret

### 2.4. Volume Mounts & KeyVault CSI Driver

**Commands:**
```bash
# 1. Check mount definitions on the container
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].volumeMounts}' | python -m json.tool

# 2. Check volume definitions on the pod spec
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.volumes}' | python -m json.tool

# 3. Check SecretProviderClass objects in namespace
kubectl get secretproviderclass -n <namespace>
kubectl describe secretproviderclass <spc-name> -n <namespace>

# 4. Check CSI driver pods are healthy
kubectl get pods -n kube-system -l app=secrets-store-csi-driver

# 5. Check pod events for mount failures
kubectl describe pod <pod-name> -n <namespace> | grep -A5 -i "warning\|error\|failed\|mount"
```

**Root causes (ranked for this platform):**
1. KeyVault secret name in SecretProviderClass doesn't match actual secret name in KV
2. Managed identity (or workload identity SA) lacks `GET` permission on KeyVault access policy
3. Identity binding not in the same namespace as the pod
4. CSI driver pod not running or crashlooping on the node
5. KeyVault secret was soft-deleted — blocks re-creation with same name

**KB tools:**
- `hivemind_get_secret_flow(client=<client>, secret="<secret-name>")` — full chain: KV → Terraform → K8s Secret → Helm → Pod
- `hivemind_query_memory(client=<client>, query="<service> secretProviderClass keyvault volume")` — Helm/TF config

### 2.5. Init Containers

**Commands:**
```bash
# 1. List init containers on the pod
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.initContainers[*].name}'

# 2. Check init container status
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.initContainerStatuses}' | python -m json.tool

# 3. Get init container logs
kubectl logs <pod-name> -n <namespace> -c <init-container-name>
```

**Root causes:**
1. Init container waiting for a dependency service to become available (readiness gate)
2. Init container hitting a network policy block
3. Init container image pull failure (same ACR issues as main container)
4. Init container ConfigMap/Secret mount failure
5. Init container completing but with bad exit code (permissions issue, script error)

**Next steps based on init container logs:**
- If "connection refused" or "timeout" → check target service health (Layer 5)
- If "permission denied" → check RBAC / managed identity (AKS Gotchas section)
- If no logs at all → check image pull (Section 2.1)

### 2.6. Probe Failures

**Commands:**
```bash
# 1. Get liveness probe config
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].livenessProbe}' | python -m json.tool

# 2. Get readiness probe config
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].readinessProbe}' | python -m json.tool

# 3. Get startup probe config (if exists)
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].startupProbe}' | python -m json.tool

# 4. Check probe failure events
kubectl get events -n <namespace> --field-selector reason=Unhealthy --sort-by='.lastTimestamp' | tail -20

# 5. Test probe endpoint from inside the pod (if pod is running)
kubectl exec <pod-name> -n <namespace> -- curl -sv http://localhost:<port>/<path>

# 6. Measure actual startup time from logs
kubectl logs <pod-name> -n <namespace> | grep -i "started\|ready\|listening\|initialized\|JVM running"
```

**Root causes (ranked for Spring Boot on AKS — #1 is most common):**
1. JVM startup exceeds `initialDelaySeconds` — see Spring Boot Gotchas section
2. Probe path or port doesn't match what the application actually serves
3. `/actuator/health` checks all health indicators — if a dependent DB is down, probe fails → pod restarts → cascading CrashLoopBackOff
4. GC pause or thread deadlock causes probe timeout
5. Readiness probe too aggressive (low `periodSeconds` or `timeoutSeconds`) — pod removed from service during minor GC pauses

**KB tools:**
- `hivemind_query_memory(client=<client>, query="<service> probes readiness liveness initialDelaySeconds startupProbe")` — find probe config in Helm values

---

## LAYER 3 — WORKLOAD DIAGNOSIS

### Commands to Recommend

**1. Deployment status**
```bash
kubectl get deployment <service> -n <namespace> -o wide
```
> **Look for:** READY column (desired vs available), UP-TO-DATE (matches desired?), AVAILABLE. If UP-TO-DATE < DESIRED, rollout is stuck.

**2. Rollout status**
```bash
kubectl rollout status deployment/<service> -n <namespace>
```
> **Look for:** See [Command Output Interpretation — rollout status](#interpret-rollout-status).

**3. Rollout history**
```bash
kubectl rollout history deployment/<service> -n <namespace>
```
> **Look for:** Revision count, CHANGE-CAUSE annotations (image tag changes). The most recent revision is the current deployment.

**4. ReplicaSet status**
```bash
kubectl get rs -n <namespace> -l app=<service> --sort-by='.metadata.creationTimestamp'
```
> **Look for:** Old RS with READY pods = rollback candidate. New RS with 0 READY = new version failing. Multiple RS with pods = rollout in progress or stuck.

**5. HPA status**
```bash
kubectl get hpa -n <namespace>
kubectl describe hpa <hpa-name> -n <namespace>
```
> **Look for:** TARGETS column (current/target — e.g., `85%/80%` means over threshold). MINPODS/MAXPODS. CONDITIONS: `ScalingActive`, `AbleToScale`, `ScalingLimited`.

**6. StatefulSet status (if applicable)**
```bash
kubectl get statefulset <service> -n <namespace>
kubectl rollout status statefulset/<service> -n <namespace>
```
> **Look for:** READY vs DESIRED. StatefulSets update pods sequentially — if one pod is stuck, the rollout halts.

### Stuck Rollout Diagnosis

| Symptom | Cause | Next Step |
|---------|-------|-----------|
| New RS has 0 READY pods | New pods failing health checks | Check new pod: `kubectl describe pod <new-pod>` → Layer 2 |
| `Progressing=False` condition | `progressDeadlineSeconds` exceeded | Check why new pods aren't ready, consider rollback |
| Old RS not scaling down | `maxUnavailable=0` and new pods not ready | Fix new pod issue or `kubectl rollout undo` |
| Multiple RS with pods | Successive deploys before previous finished | Check Harness execution history |

### Rollback (if needed)
```bash
# Undo to previous revision
kubectl rollout undo deployment/<service> -n <namespace>

# Undo to specific revision
kubectl rollout undo deployment/<service> -n <namespace> --to-revision=<N>
```

### KB Cross-Reference (Layer 3)

| Signal | HiveMind Tool | Query |
|--------|---------------|-------|
| Deployment strategy | `hivemind_query_memory(query="<service> deployment strategy rollingUpdate maxUnavailable")` | Rolling update params |
| HPA config | `hivemind_query_memory(query="<service> autoscaling HPA minReplicas maxReplicas")` | Scale bounds |
| Pipeline that deployed | `hivemind_get_pipeline(name="<pipeline>")` | Stages, artifact, variables |
| Artifact/image | `hivemind_query_memory(query="<service> image tag artifact")` | What image was deployed |

### Sherlock Correlation (Layer 3)

**Path A:**

| Data Needed | Sherlock Tool |
|-------------|---------------|
| Deployment history & timing | `mcp_sherlock_get_deployments(app_name="<service>")` |
| Error rate after deploy | `mcp_sherlock_get_service_golden_signals(service_name="<service>")` |
| Full parallel investigation | `mcp_sherlock_investigate_service(service_name="<service>")` |

**Path B fallback:**
```bash
# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>

# Current image vs previous
kubectl get rs -n <namespace> -l app=<service> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'
```

---

## LAYER 4 — NODE DIAGNOSIS

### Commands to Recommend

**1. Node overview**
```bash
kubectl get nodes -o wide
```
> **Look for:** STATUS (Ready/NotReady/SchedulingDisabled), VERSION, node names (AKS pattern: `aks-<nodepool>-<vmss-id>`). NotReady = node-level issue.

**2. Describe the target node**
```bash
kubectl describe node <node-name>
```
> **Look for:** See [Command Output Interpretation — describe node](#interpret-describe-node).

**3. Node resource usage**
```bash
kubectl top nodes
```
> **Look for:** CPU% and MEMORY% close to allocatable. >90% = scheduling pressure.

**4. Pods running on the node**
```bash
kubectl get pods --all-namespaces --field-selector spec.nodeName=<node-name> -o wide
```
> **Look for:** System pods (kube-system) in bad state = node-level failure. Many user pods evicted = resource pressure.

**5. Node pool info (AKS)**
```bash
az aks nodepool show --resource-group <rg> --cluster-name <cluster> --name <nodepool-name> -o table
```
> **Look for:** provisioningState, count, vmSize, mode (System/User), enableAutoScaling, minCount/maxCount.

**6. Node labels and taints**
```bash
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
kubectl get nodes --show-labels | grep <nodepool-label>
```
> **Look for:** Taint mismatches with pod tolerations. Missing labels for nodeSelector.

### Taint / Toleration Debugging

```bash
# Pod tolerations
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.tolerations}' | python -m json.tool

# Deployment nodeSelector
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.nodeSelector}'

# Deployment affinity rules
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.affinity}' | python -m json.tool
```

**Common AKS scheduling failures:**
| Taint on Node | Required Toleration | Meaning |
|--------------|---------------------|---------|
| `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` | Must tolerate `spot` | Spot instance node — only tolerating workloads can schedule |
| `CriticalAddonsOnly=true:NoSchedule` | System pods only | System pool — user workloads cannot schedule here |
| `node.kubernetes.io/not-ready:NoSchedule` | Auto-added | Node is unhealthy — pods being drained |
| `node.kubernetes.io/unschedulable:NoSchedule` | Auto-added | Node cordoned for maintenance |

### Node Condition Interpretation

| Condition | True Means | Action |
|-----------|-----------|--------|
| `MemoryPressure` | Node running out of allocatable memory | Identify highest-memory pods on node, check for leaks |
| `DiskPressure` | Node disk >85% full | Check container log volumes, image cache, ephemeral storage |
| `PIDPressure` | Too many processes on node | Check for fork bombs, excessive threads in Java apps |
| `NetworkUnavailable` | CNI not configured or failing | Check Azure CNI plugin pod, kube-proxy |
| `Ready=False` | Node unhealthy | Check kubelet logs, VM status in Azure portal |

### KB Cross-Reference (Layer 4)

| Signal | HiveMind Tool | Query |
|--------|---------------|-------|
| Node pool Terraform | `hivemind_query_memory(query="aks node pool terraform vmSize")` | Node pool TF definition |
| Node selectors in Helm | `hivemind_query_memory(query="<service> nodeSelector toleration affinity")` | Scheduling constraints |
| Node pool TF files | `hivemind_search_files(query="aks.tf node_pool")` | Locate TF files |

### Sherlock Correlation (Layer 4)

**Path A:**

| Data | Sherlock Tool |
|------|---------------|
| K8s node metrics | `mcp_sherlock_run_nrql_query(nrql="SELECT latest(cpuPercent), latest(memoryPercent) FROM K8sNodeSample SINCE 1 hour ago FACET nodeName")` |
| Cluster health | `mcp_sherlock_get_k8s_health()` |
| Infra alerts | `mcp_sherlock_get_incidents(state="open")` |

**Path B fallback:**
```bash
kubectl top nodes
kubectl describe node <node-name> | grep -A20 "Allocated resources"
```

---

## LAYER 5 — NETWORKING DIAGNOSIS

### Commands to Recommend

**1. Service and endpoints**
```bash
kubectl get svc -n <namespace> -l app=<service>
kubectl get endpoints -n <namespace> <service-name>
```
> **Look for:** ENDPOINTS column empty = no pods match the service selector. Check selector labels match pod labels. ClusterIP vs LoadBalancer type messages.

**2. DNS resolution from inside a pod**
```bash
kubectl exec <any-running-pod> -n <namespace> -- nslookup <target-service>.<target-namespace>.svc.cluster.local
```
> **Look for:** NXDOMAIN = service doesn't exist or wrong namespace. Timeout = CoreDNS issue. Server failure = DNS pod unhealthy.

If no running pod available:
```bash
kubectl run debug-dns --rm -it --image=busybox:1.36 --restart=Never -n <namespace> -- nslookup <target-service>.<target-namespace>.svc.cluster.local
```

**3. Connectivity test**
```bash
kubectl exec <pod-name> -n <namespace> -- curl -sv http://<target-service>:<port>/health --connect-timeout 5
```
> **Look for:** `Connection refused` = target not listening on that port. `Timed out` = network policy block or target is down. `200 OK` = connectivity is fine, issue is elsewhere.

**4. Network policies**
```bash
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy <policy-name> -n <namespace>
```
> **Look for:** If ANY NetworkPolicy selects a pod, only explicitly allowed ingress/egress traffic gets through (default-deny). Check `podSelector`, `ingress.from`, `egress.to` rules.

**5. Ingress**
```bash
kubectl get ingress -n <namespace>
kubectl describe ingress <ingress-name> -n <namespace>
```
> **Look for:** Backend service name + port, TLS config, host rules, ADDRESS assignment (should have an IP).

**6. CoreDNS health**
```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns
```
> **Look for:** All CoreDNS pods should be Running with READY 1/1. CrashLoopBackOff = DNS is broken cluster-wide.

**7. Azure load balancer (AKS-specific)**
```bash
kubectl get svc -n <namespace> -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.metadata.annotations}{"\n"}{end}'
```
> **Look for:** `service.beta.kubernetes.io/azure-load-balancer-internal: "true"` for internal services. Missing annotation on an internal service = it gets a public IP.

### Common AKS Networking Failures

| Symptom | Likely Cause | Verify |
|---------|-------------|--------|
| Pod can't reach external service | NSG on AKS subnet blocking outbound | Azure portal → NSG → outbound rules |
| Pod can't reach another pod | NetworkPolicy default-deny | `kubectl describe networkpolicy` in BOTH namespaces |
| Service has empty endpoints | Label selector mismatch | Compare `svc.spec.selector` with `pod.metadata.labels` |
| DNS fails | CoreDNS unhealthy | `kubectl get pods -n kube-system -l k8s-app=kube-dns` |
| LoadBalancer stuck Pending | Subnet IP exhaustion (Azure CNI) | See AKS Gotchas: CNI IP Exhaustion |

### KB Cross-Reference (Layer 5)

| Signal | HiveMind Tool | Query |
|--------|---------------|-------|
| Network policies | `hivemind_query_memory(query="<service> networkpolicy ingress egress")` | NP definitions in Helm/TF |
| Service dependencies | `hivemind_impact_analysis(entity="<service>")` | Upstream/downstream service map |
| Ingress config | `hivemind_query_memory(query="<service> ingress host path")` | Ingress rules in Helm |

### Sherlock Correlation (Layer 5)

**Path A:**

| Data | Sherlock Tool |
|------|---------------|
| Dependency error rates | `mcp_sherlock_get_service_dependencies(service_name="<service>")` |
| Connection error logs | `mcp_sherlock_search_logs(service_name="<service>", keyword="connection refused|timeout|ECONNREFUSED")` |
| Target service health | `mcp_sherlock_get_service_golden_signals(service_name="<target-service>")` |

**Path B fallback:**
```bash
# Test connectivity from inside a pod
kubectl exec <pod> -n <ns> -- curl -sv http://<target>:<port>/health --connect-timeout 5

# Check DNS resolution
kubectl exec <pod> -n <ns> -- nslookup <target>.<target-ns>.svc.cluster.local
```

---

## LAYER 6 — STORAGE DIAGNOSIS

### Commands to Recommend

**1. PVC status**
```bash
kubectl get pvc -n <namespace>
```
> **Look for:** STATUS (Bound/Pending/Lost), CAPACITY, STORAGECLASS name, associated VOLUME name. Pending = provisioner can't create the disk.

**2. Describe PVC**
```bash
kubectl describe pvc <pvc-name> -n <namespace>
```
> **Look for:** See [Command Output Interpretation — describe pvc](#interpret-describe-pvc). Events section shows the provisioner's error message.

**3. StorageClass**
```bash
kubectl get storageclass
kubectl describe storageclass <sc-name>
```
> **Look for:** PROVISIONER (`disk.csi.azure.com` vs `file.csi.azure.com`), RECLAIMPOLICY (`Delete` vs `Retain`), VOLUMEBINDINGMODE (`WaitForFirstConsumer` vs `Immediate`).

**4. SecretProviderClass (KeyVault CSI)**
```bash
kubectl get secretproviderclass -n <namespace>
kubectl describe secretproviderclass <spc-name> -n <namespace>
```
> **Look for:** `keyvaultName`, `tenantId`, `useVMManagedIdentity` or `usePodIdentity`, `objects` array with secret names.

**5. CSI driver health**
```bash
kubectl get pods -n kube-system -l app=secrets-store-csi-driver
kubectl get pods -n kube-system -l app=csi-azuredisk-node
kubectl get pods -n kube-system -l app=csi-azurefile-node
```
> **Look for:** All CSI pods Running + Ready. CrashLoopBackOff = driver failing on specific nodes.

**6. PV and Azure Disk details**
```bash
kubectl get pv <pv-name> -o jsonpath='{.spec.azureDisk}' | python -m json.tool
```
> **Look for:** diskName, diskURI, cachingMode. If multi-attach error: the disk is RWO and attached to another node.

### Common AKS Storage Failures

| Symptom | Cause | Verify |
|---------|-------|--------|
| PVC stuck Pending | StorageClass doesn't exist or zone mismatch | `kubectl get sc`, check zone labels vs node zone |
| Multi-attach error | Azure Disk is ReadWriteOnce, pod moved to new node | Wait for old pod to terminate, or force-delete: `kubectl delete pod <old-pod> -n <ns> --force --grace-period=0` |
| Mount timeout | CSI driver pod not running on the target node | Check CSI pods on that specific node |
| KeyVault mount fails (ContainerCreating stuck) | Identity lacks KV access, wrong secret name, wrong vault | See AKS Gotchas: KeyVault CSI |
| Permission denied on mount | `fsGroup` not set in securityContext | Check `spec.securityContext.fsGroup` |
| Azure File slow | Premium tier not selected, large file count | Check StorageClass `skuName` parameter |

### KB Cross-Reference (Layer 6)

| Signal | HiveMind Tool | Query |
|--------|---------------|-------|
| Secret chain | `hivemind_get_secret_flow(secret="<secret-name>")` | Full KV → TF → K8s → Helm → Pod |
| PVC definitions | `hivemind_query_memory(query="<service> persistentVolumeClaim storage volume")` | Helm values for PVC |
| TF storage | `hivemind_search_files(query="storage.tf managed_disk")` | Terraform storage definitions |
| SecretProviderClass in Helm | `hivemind_query_memory(query="<service> secretProviderClass keyvaultName")` | SPC Helm template |

### Sherlock Correlation (Layer 6)

**Path A:** `mcp_sherlock_get_k8s_health(service_name="<service>")` — check for mount-related pod events
**Path B fallback:**
```bash
kubectl describe pod <pod> -n <ns> | grep -A10 -i "mount\|volume\|warning\|error"
kubectl get events -n <namespace> --field-selector reason=FailedMount --sort-by='.lastTimestamp'
```

---

## AKS-Specific Gotchas

### Managed Identity vs Service Principal

| Auth Method | How to Identify | Common Failure |
|-------------|----------------|----------------|
| **System-assigned managed identity** | `az aks show -g <rg> -n <cluster> --query identity` | Identity deleted or not assigned required role |
| **User-assigned managed identity** | `az aks show -g <rg> -n <cluster> --query identityProfile` | Identity not assigned to VMSS, or wrong identity |
| **Service principal** | `az aks show -g <rg> -n <cluster> --query servicePrincipalProfile` | SP secret expired (1-2 year default) |

**Debug commands:**
```bash
# Check cluster identity type
az aks show -g <rg> -n <cluster> --query "{identity: identity.type, principalId: identity.principalId}"

# Check kubelet identity (used for ACR pull, KeyVault access)
az aks show -g <rg> -n <cluster> --query "identityProfile.kubeletidentity"

# Check VMSS identity assignments
az vmss identity show --resource-group <MC_rg> --name <vmss-name>
```

### Workload Identity / AAD Pod Identity

**Workload Identity (newer, recommended):**
```bash
# Check ServiceAccount annotation for workload identity
kubectl describe serviceaccount <sa-name> -n <namespace>
# Must have: azure.workload.identity/client-id: <client-id>

# Check federated credential on the managed identity
az identity federated-credential list --identity-name <identity-name> --resource-group <rg>

# Check if pod has workload identity labels
kubectl get pod <pod> -n <ns> -o jsonpath='{.metadata.labels.azure\.workload\.identity/use}'
```

**AAD Pod Identity (legacy):**
```bash
# Check AzureIdentity and AzureIdentityBinding
kubectl get azureidentity,azureidentitybinding -n <namespace>

# Check NMI (Node Managed Identity) daemon health
kubectl get pods -n kube-system -l app=nmi

# Must be in SAME namespace as the pod
kubectl get azureidentitybinding -n <namespace> -o yaml
```

**Common failures:**
| Failure | Symptom | Fix |
|---------|---------|-----|
| SA missing annotation | Pod gets 401 calling Azure APIs | Add `azure.workload.identity/client-id` annotation to SA |
| Federated credential misconfigured | Token exchange fails, `AADSTS70021` error | Check issuer URL, subject, audience |
| AzureIdentityBinding in wrong namespace | Pod identity not bound, 403 on KV/ACR | Move binding to pod's namespace |
| NMI pod down | ALL identity-dependent pods fail simultaneously | `kubectl rollout restart daemonset/nmi -n kube-system` |

### KeyVault CSI Driver

**Most common mount failure on this platform.** Debug sequence:

```bash
# 1. Check pod events for mount error message
kubectl describe pod <pod> -n <ns> | grep -A5 "FailedMount\|MountVolume"

# 2. Check SecretProviderClass config
kubectl get secretproviderclass <spc> -n <ns> -o yaml

# 3. Verify the identity can access KeyVault
az keyvault show --name <vault-name> --query "properties.accessPolicies[?objectId=='<identity-object-id>']"

# 4. Verify secret exists in KeyVault
az keyvault secret show --vault-name <vault-name> --name <secret-name> --query "{name: name, enabled: attributes.enabled}"

# 5. Check CSI driver logs on the node where pod is scheduled
kubectl logs -n kube-system <csi-secrets-store-pod-on-node> --tail=100
```

**Failure matrix:**

| Error Message (in events) | Root Cause | Fix |
|--------------------------|-----------|-----|
| `keyvault. ... Forbidden` | Identity lacks GET/LIST on KV access policy | Add access policy or RBAC role assignment |
| `SecretNotFound` | Secret name mismatch or secret deleted | Check `objects` array in SecretProviderClass vs actual KV secrets |
| `MSI not available` | Managed identity not assigned to node VMSS | Assign identity to VMSS or use workload identity |
| `context deadline exceeded` | Network issue between node and KV | Check private endpoints, DNS resolution to KV |
| `failed to create provider` | CSI driver pod unhealthy | Restart CSI driver: `kubectl rollout restart daemonset/csi-secrets-store -n kube-system` |

**KB tools:** `hivemind_get_secret_flow(client=<client>, secret="<secret-name>")` — traces full lifecycle

### ACR Pull Authentication

| Method | How to Check | Common Failure |
|--------|-------------|----------------|
| **Managed identity (node-level)** | `az aks show -g <rg> -n <cluster> --query "identityProfile.kubeletidentity"` | Kubelet identity not assigned `AcrPull` role on ACR |
| **imagePullSecret (namespace-level)** | `kubectl get secret -n <ns> --field-selector type=kubernetes.io/dockerconfigjson` | Secret expired or references wrong ACR |
| **AKS-ACR integration** | `az aks check-acr -g <rg> -n <cluster> --acr <acr-name>` | Integration not configured |

```bash
# Verify ACR integration
az aks check-acr --resource-group <rg> --name <cluster> --acr <acr-name>.azurecr.io

# Check kubelet identity AcrPull role
az role assignment list --assignee <kubelet-identity-client-id> --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ContainerRegistry/registries/<acr-name>
```

**KB tools:** `hivemind_query_memory(client=<client>, query="<service> image repository ACR imagePullSecrets")` — Helm values with ACR config per environment

### Spot Instance Evictions

```bash
# 1. Identify spot nodes
kubectl get nodes -l kubernetes.azure.com/scalesetpriority=spot

# 2. Check if the failed pod was on a spot node
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.nodeName}'
kubectl get node <node> -o jsonpath='{.metadata.labels.kubernetes\.azure\.com/scalesetpriority}'

# 3. Check for eviction events cluster-wide
kubectl get events --all-namespaces --field-selector reason=Evicted --sort-by='.lastTimestamp'

# 4. Check Azure scheduled events on the node (from inside a node pod)
# Azure gives ~30 second notice before spot reclaim
```

**Key rules:**
- Spot nodes have taint: `kubernetes.azure.com/scalesetpriority=spot:NoSchedule`
- Critical/stateful workloads MUST NOT run on spot — check `nodeSelector` and `tolerations` in Helm values
- If a critical service is on spot → immediate fix: remove spot toleration from Helm values

### Azure CNI IP Exhaustion

**Symptom:** New pods stuck in Pending, new nodes can't join cluster.

```bash
# Check subnet IP allocation
az network vnet subnet show --resource-group <rg> --vnet-name <vnet> --name <subnet> --query "{addressPrefix: addressPrefix, ipConfigurations: ipConfigurations | length(@)}"

# Check max pods per node
az aks nodepool show --resource-group <rg> --cluster-name <cluster> --name <pool> --query maxPods
```

**Formula:** `Required IPs = (nodes × maxPods) + nodes + reserved_IPs`

A /24 subnet = 251 usable IPs. With `maxPods=30` and 8 nodes = 248 IPs reserved = nearly full.

**Fix:** Expand subnet CIDR (requires re-creation), reduce `maxPods`, or switch to overlay networking.

**KB tools:** `hivemind_query_memory(client=<client>, query="aks subnet vnet terraform CIDR")` — find subnet config in TF

### Node Pool Autoscaler Blocked

```bash
# Check autoscaler config
az aks nodepool show --resource-group <rg> --cluster-name <cluster> --name <pool> --query "{enableAutoScaling: enableAutoScaling, minCount: minCount, maxCount: maxCount, count: count}"

# Check cluster autoscaler logs
kubectl logs -n kube-system -l app=cluster-autoscaler --tail=50

# Check Azure VM quota
az vm list-usage --location <region> -o table | Select-String "<vm-sku>"
```

**Scale-up blocks:**
| Block Reason | Log Pattern | Fix |
|-------------|-------------|-----|
| VM quota exceeded | `ScaleUpFailed ... QuotaExceeded` | Request quota increase in Azure portal |
| Subnet IP exhaustion | `ScaleUpFailed ... InsufficientSubnetSize` | Expand subnet |
| `maxCount` reached | `ScaleUpFailed ... NodeGroupMaxSizeReached` | Increase `maxCount` in TF |
| VM SKU unavailable | `ScaleUpFailed ... AllocationFailed` | Try different region/zone or SKU |

### Azure Disk Multi-Attach

**Error:** `Multi-Attach error for volume "pvc-xxx": Volume is already attached to node "aks-nodepool-xxx"`

**Cause:** Azure Managed Disk is `ReadWriteOnce` — only one node can mount it at a time. When a pod moves to a different node (eviction, node drain, scaling), the old attachment may not release cleanly.

**Resolution sequence:**
1. Check if old pod is stuck Terminating: `kubectl get pods -n <ns> | grep Terminating`
2. If stuck: `kubectl delete pod <old-pod> -n <ns> --force --grace-period=0` (recommend with caution — data loss risk for non-replicated workloads)
3. Wait 2-3 minutes for Azure to detach the disk
4. If still attached: check in Azure portal → Disks → verify disk is not attached to old VMSS instance
5. Long-term fix: use Azure File (`ReadWriteMany`) for workloads that scale or move frequently

---

## Spring Boot on AKS — Java-Specific Gotchas

### JVM Startup Time vs Probe Timing

**Most common cause of CrashLoopBackOff on this platform.**

| Metric | Typical Value (Spring Boot 3.x, 50+ beans) |
|--------|---------------------------------------------|
| Spring Boot startup | 30–90 seconds |
| With DB/Flyway migrations | 60–180 seconds |
| JVM warmup (JIT) | Additional 15–30 seconds |

**Correct probe configuration for this platform:**
```yaml
# Best practice: use startupProbe for slow-starting JVM apps
startupProbe:
  httpGet:
    path: /actuator/health/liveness
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 15    # Total budget: 30 + (10 × 15) = 180 seconds
livenessProbe:
  httpGet:
    path: /actuator/health/liveness    # NOT /actuator/health
    port: 8080
  periodSeconds: 10
  failureThreshold: 3
readinessProbe:
  httpGet:
    path: /actuator/health/readiness   # NOT /actuator/health
    port: 8080
  periodSeconds: 5
  failureThreshold: 3
```

**Critical mistake:** Using `/actuator/health` (includes ALL health indicators) instead of `/actuator/health/liveness`. If a database dependency is down, `/actuator/health` returns 503 → liveness probe fails → **pod restarts in a loop, even though the app itself is fine** → cascading CrashLoopBackOff across all instances.

### OOMKilled — JVM Memory Model

**Container memory must accommodate all JVM memory regions, not just the heap.**

```
Container limit >= Heap (-Xmx) + Metaspace + Native + OS buffer

Breakdown for a typical service on this platform:
  -Xmx 512m  (heap — explicit or calculated from -XX:MaxRAMPercentage)
  + 256m     (metaspace — default unlimited, typical size ~200-300m)
  + 200m     (native: thread stacks, NIO direct buffers, JNI)
  + 100m     (OS/kernel overhead, cgroup accounting)
  ─────────
  = 1068m minimum → set container limit to 1.5Gi for safety margin
```

**Diagnostic commands:**
```bash
# Check JVM heap and metaspace flags
kubectl exec <pod> -n <ns> -- java -XX:+PrintFlagsFinal -version 2>&1 | grep -iE "MaxHeapSize|MaxMetaspaceSize|MaxRAMPercentage"

# Check JAVA_TOOL_OPTIONS (commonly used on this platform)
kubectl exec <pod> -n <ns> -- printenv JAVA_TOOL_OPTIONS

# Check container memory limit
kubectl get pod <pod> -n <ns> -o jsonpath='{.spec.containers[0].resources.limits.memory}'

# Check actual JVM memory usage (if pod is running)
kubectl exec <pod> -n <ns> -- jcmd 1 VM.native_memory summary 2>/dev/null || echo "NMT not enabled"
```

**KB check:** `hivemind_query_memory(client=<client>, query="<service> JAVA_TOOL_OPTIONS Xmx memory resources limits")` — find JVM flags and resource limits in Helm values.

### Spring Bean Initialization Failures

**Recognizing the stack trace pattern:**
```
org.springframework.beans.factory.BeanCreationException: Error creating bean with name 'dataSource'
  Caused by: org.springframework.beans.factory.UnsatisfiedDependencyException: ...
    Caused by: org.springframework.beans.factory.NoSuchBeanDefinitionException: ...
```

**Root causes (ranked):**
1. Missing configuration property — `application.yml` key missing or env var not set
2. Database unreachable at startup — connection string or network issue
3. Missing Spring profile — `SPRING_PROFILES_ACTIVE` env var not set or wrong value
4. Circular dependency — use `@Lazy` or refactor to constructor injection
5. Class not found after dependency version bump — Spring Boot auto-config classpath issue

**How to find the root bean:** Read the `Caused by:` chain bottom to top. The LAST `Caused by:` is the actual root cause. The first `BeanCreationException` is just the surface symptom.

### Spring Cloud Config / ConfigMap Startup Failures

**Symptom:** Pod fails to start with `Could not locate PropertySource` or `Connection refused: Config Server`.

**Root causes:**
1. Spring Cloud Config Server is down or unreachable
2. ConfigMap for Spring Config not mounted or wrong key name
3. `spring.config.import` referencing unavailable source
4. `spring.cloud.config.fail-fast: true` is set (fails on config server down)

**Debug:**
```bash
# Check if config server is healthy
kubectl get pods -n <namespace> -l app=<config-server>

# Check if configmap exists
kubectl get configmap <service>-config -n <namespace>

# Check Spring profiles and config imports
kubectl exec <pod> -n <ns> -- printenv | grep -i "spring\|config"
```

### Graceful Shutdown Timing

**K8s termination sequence:**
1. Pod enters `Terminating` state
2. `preStop` hook runs (if configured)
3. `SIGTERM` sent to PID 1
4. Wait for `terminationGracePeriodSeconds` (default: 30s)
5. `SIGKILL` if still running

**Spring Boot shutdown:**
```yaml
# application.yml
server.shutdown: graceful
spring.lifecycle.timeout-per-shutdown-phase: 30s
```

**Rule:** `terminationGracePeriodSeconds` MUST be > `spring.lifecycle.timeout-per-shutdown-phase` + `preStop` hook time. Otherwise K8s sends SIGKILL before Spring finishes draining connections.

**Symptom:** Clients get `Connection reset` during deployments = graceful shutdown not completing.

### ActiveProcessorCount

**Problem:** JVM in a container with CPU limit < 1 core sees `Runtime.availableProcessors() == 1`. Thread pools default to 1 thread:
- Tomcat worker threads: 1 (default = `availableProcessors * 2`)
- Hikari pool size: 1
- `@Async` executor: 1

**Symptom:** Service is Running but extremely slow, low throughput under load.

**Fix:** Add to `JAVA_TOOL_OPTIONS`:
```
-XX:ActiveProcessorCount=2
```

**KB check:** `hivemind_query_memory(client=<client>, query="<service> JAVA_TOOL_OPTIONS ActiveProcessorCount")` — check if already set in Helm values.

---

## Command Output Interpretation Guide

> **This is the most important section.** Since Copilot cannot run commands, it MUST know
> exactly what patterns to search for in pasted output and what to recommend next.
> Every pattern follows the format: **If you see X → it means Y → recommend Z.**

### <a name="interpret-describe-pod"></a>kubectl describe pod — Pattern Guide

Parse the user's pasted output in this order:

#### 1. Status Section

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `Phase: Pending` | Pod not scheduled to any node | Read Events section for scheduling failure reason |
| `Phase: Running` but user reports errors | App is running but misbehaving | `kubectl logs <pod> -n <ns> --tail=200` |
| `Phase: Failed` | Pod terminated with unrecoverable error | Check `containerStatuses.state.terminated.reason` |
| `Phase: Succeeded` | Pod completed (Job or init) | Check if this was a Job/CronJob, not a Deployment |
| `Phase: Unknown` | Node lost contact with API server | `kubectl get node <node>` — is node Ready? |

#### 2. Conditions Section

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `PodScheduled: False` | Scheduler can't place pod | Read Events for `FailedScheduling` message → Layer 4 |
| `Initialized: False` | Init container hasn't completed | `kubectl logs <pod> -n <ns> -c <init-container>` → Layer 2.5 |
| `ContainersReady: False` | Main container not passing readiness | Check readiness probe config → Layer 2.6 |
| `Ready: False` | Pod not serving traffic | Could be probe, could be init container — check other conditions |
| All conditions `True` but user sees errors | Pod is healthy from K8s perspective | Issue is application-level — check app logs |

#### 3. Container State Section

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `Waiting: CrashLoopBackOff` | Container crashing, K8s backing off restarts | `kubectl logs <pod> -n <ns> --previous --tail=300` |
| `Waiting: ImagePullBackOff` | Can't pull container image | Check image name/tag + ACR auth → Layer 2.1 |
| `Waiting: ContainerCreating` (>2 min) | Stuck on mount or pull | Read Events for `FailedMount` or `Pulling` → Layer 6 or 2.1 |
| `Waiting: PodInitializing` | Init container running | `kubectl logs <pod> -n <ns> -c <init-container>` → Layer 2.5 |
| `Running` | Container is healthy | Check logs for app-level errors |
| `Terminated: OOMKilled` (exit 137) | Out of memory | Layer 2.2 — check limits vs `kubectl top pod`, JVM flags |
| `Terminated: Error` (exit 1) | App error on startup or runtime | `kubectl logs <pod> -n <ns> --previous --tail=300` — look for stack trace |
| `Terminated: Error` (exit 137) | SIGKILL — OOM or external kill | Check `OOMKilled` field. If false: node eviction → Layer 4 |
| `Terminated: Error` (exit 143) | SIGTERM — graceful shutdown exceeded | Check `terminationGracePeriodSeconds` → Spring Boot Gotchas |
| `Last State: Terminated, OOMKilled: true` | Previous container was OOM killed | Memory limit problem → Layer 2.2 |

#### 4. Events Section

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `FailedScheduling: 0/N nodes available: insufficient cpu` | No node has enough CPU for the request | `kubectl top nodes` → check capacity or increase node count |
| `FailedScheduling: ... didn't match node affinity/selector` | nodeSelector/affinity doesn't match any node labels | `kubectl get nodes --show-labels` and check Helm values → Layer 4 |
| `FailedScheduling: ... had taint ... didn't tolerate` | Pod needs a toleration for the node's taint | Check taints + tolerations → Layer 4 |
| `Pulling` then `Pulled` | Image pull succeeded | Not the issue — move to container state |
| `Failed: ... pull access denied` | ACR auth failure | Check imagePullSecrets and managed identity → Layer 2.1 |
| `Failed: ... manifest unknown` | Image tag doesn't exist in registry | `az acr repository show-tags` → Layer 2.1 |
| `FailedMount: MountVolume.SetUp failed` | Secret or PVC mount error | Read FULL error message → Layer 6 |
| `FailedMount: ... keyvault ... Forbidden` | Identity can't access KeyVault | Check SecretProviderClass identity → AKS Gotchas: KeyVault CSI |
| `FailedMount: ... SecretNotFound` | KV secret name mismatch | Compare SPC `objects` array with actual KV secrets |
| `Unhealthy: Liveness probe failed: ...` | Liveness timeout → container will restart | Check probe config + startup time → Layer 2.6 |
| `Unhealthy: Readiness probe failed: ...` | Pod removed from service endpoints | Check probe config + dependency health → Layer 2.6 |
| `BackOff: restarting failed container` | Container keeps crashing | Get `--previous` logs |
| `Evicted` | Pod evicted from node | `kubectl describe node <node>` → Layer 4 |
| `FailedCreate` | ReplicaSet can't create pod | Check resource quotas: `kubectl describe resourcequota -n <ns>` |
| `SuccessfulCreate` then no further events | Pod was created, waiting on scheduling or pull | Wait, or check node availability |

### <a name="interpret-describe-node"></a>kubectl describe node — Pattern Guide

#### 1. Conditions Block

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `Ready: True` | Node healthy | Issue is pod-specific, not node |
| `Ready: False` | Node unhealthy — kubelet or Docker issue | Check Azure VM status in portal |
| `Ready: Unknown` | Node lost contact with API server | `az vmss list-instances -g <MC_rg> -n <vmss> -o table` |
| `MemoryPressure: True` | Node memory >90% used | `kubectl top pods --all-namespaces --field-selector spec.nodeName=<node> --sort-by=memory` |
| `DiskPressure: True` | Node disk >85% full | Check container logs volume, image cache |
| `PIDPressure: True` | Too many processes | Check Java thread counts — possible thread leak |
| `NetworkUnavailable: True` | CNI plugin not ready | Check Azure CNI pods in kube-system |

#### 2. Allocated Resources Section

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| CPU requests >90% of allocatable | No room for new pods with CPU requests | Scale node pool or reduce pod CPU requests |
| Memory requests >90% of allocatable | No room for new pods with memory requests | Scale node pool or reduce pod memory requests |
| Many pods at limits | Node is packed | Check if autoscaler `maxCount` is reached |

#### 3. Taints

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `node.kubernetes.io/not-ready:NoSchedule` | Node being marked unhealthy | Check kubelet, Azure VM health |
| `node.kubernetes.io/unschedulable:NoSchedule` | Node was cordoned | Check if maintenance or drain in progress |
| `kubernetes.azure.com/scalesetpriority=spot:NoSchedule` | This is a spot instance | Only pods with spot toleration can run here |
| No taints | Normal schedulable node | Scheduling issue is likely affinity or resource-based |

### <a name="interpret-rollout-status"></a>kubectl rollout status — Pattern Guide

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `successfully rolled out` | Deployment healthy | Issue is app-level, not deployment |
| `Waiting ... 0 of N updated replicas are available` | New pods not becoming ready | `kubectl describe pod <new-pod>` → check why |
| `Waiting ... N old replicas are pending termination` | Old pods stuck terminating | Check finalizers, volume unmounts |
| `exceeded its progress deadline` | `progressDeadlineSeconds` hit | Check new pod health, consider rollback |
| Command hangs indefinitely | Rollout blocked | `kubectl get rs -n <ns> -l app=<svc>` → check RS status |

### <a name="interpret-describe-pvc"></a>kubectl describe pvc — Pattern Guide

| If You See in Events | It Means | Recommend Next |
|---------------------|----------|----------------|
| `ProvisioningFailed: ... StorageAccountType ... not supported` | Wrong storage SKU for region/zone | Check StorageClass `skuName` parameter |
| `WaitForFirstConsumer` in VOLUMEBINDINGMODE | PVC won't bind until a pod uses it | Normal behavior — check the pod, not the PVC |
| `ProvisioningFailed: ... exceeded quota` | Azure disk quota reached | Check subscription disk quotas |
| `ProvisioningFailed: ... subnet` | Zone mismatch | Azure Disk is zone-pinned — ensure pod schedules in same zone |
| No events, Pending status | No provisioner matched the StorageClass | `kubectl get sc` — check provisioner is installed |

### kubectl logs — Java Stack Trace Patterns

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| `BeanCreationException` → `UnsatisfiedDependencyException` | Missing Spring bean or config | Read LAST `Caused by:` — that's the real issue |
| `ConnectException: Connection refused` at startup | Dependency unreachable during init | Check dependency service health → Layer 5 |
| `java.lang.OutOfMemoryError: Java heap space` | Heap too small or memory leak | Increase `-Xmx` or investigate leak → Layer 2.2 |
| `java.lang.OutOfMemoryError: Metaspace` | Too many loaded classes | Increase `-XX:MaxMetaspaceSize` |
| `HikariPool ... Connection is not available` | DB connection pool exhausted | Check DB health, pool size, connection timeout |
| `SocketTimeoutException: Read timed out` | Downstream service too slow | Check dependency with `mcp_sherlock_get_service_golden_signals` or `kubectl exec curl` |
| `FATAL` or `ERROR ... Shutting down` | App is crashing | Stack trace after this line is the root cause |
| No `Started` log line | App never completed startup | JVM still loading or crashed during init — check for earlier errors |
| `o.s.b.a.e.web ... Exposing 1 endpoint` then silence | App started but didn't log it | Look for actuator starting — may be healthy |

### kubectl get endpoints — Interpretation

| If You See | It Means | Recommend Next |
|------------|----------|----------------|
| Endpoints field is `<none>` | No pods match service selector | Compare `kubectl get svc <svc> -o jsonpath='{.spec.selector}'` with `kubectl get pods --show-labels` |
| Fewer IPs than expected replicas | Some pods not passing readiness probe | Check readiness probe on non-ready pods |
| Correct IPs listed | Service routing is correct | Issue is application-level, not networking |

---

## KB Cross-Reference — Summary Map

For every investigation, search ALL indexed repos for the active client. Cross-reference findings across Helm charts + Terraform + Harness pipelines together to build a complete picture.

| What You Need | HiveMind Tool | Query Pattern |
|---------------|---------------|---------------|
| Service metadata & repos | `hivemind_get_entity(name="<service>")` | Get all repos/branches |
| Dependency chain (**MANDATORY**) | `hivemind_impact_analysis(entity="<service>")` | Upstream + downstream |
| Pod spec / probes / resources | `hivemind_query_memory(query="<service> helm values deployment probes resources")` | Helm values.yaml |
| Resource limits | `hivemind_query_memory(query="<service> resources limits memory cpu")` | Helm values |
| Secret / mount config | `hivemind_get_secret_flow(secret="<name>")` + `hivemind_query_memory(query="<service> secret volume mount")` | KV→K8s→Helm→Pod |
| Network policies | `hivemind_query_memory(query="<service> networkpolicy ingress egress")` | Helm or TF definitions |
| Node affinity / tolerations | `hivemind_query_memory(query="<service> nodeSelector toleration affinity")` | Helm values scheduling |
| Image / pipeline | `hivemind_get_pipeline(name="<pipeline>")` | Pipeline stages + artifact |
| TF infra resources | `hivemind_search_files(query="<resource>.tf")` + `hivemind_query_memory(query="<resource> terraform")` | TF definitions |
| HPA / autoscaling | `hivemind_query_memory(query="<service> autoscaling HPA minReplicas maxReplicas")` | Helm values |
| Ingress rules | `hivemind_query_memory(query="<service> ingress host path tls")` | Helm ingress template |
| SecretProviderClass | `hivemind_query_memory(query="<service> secretProviderClass keyvaultName")` | Helm SPC template |
| Env vars / configmap | `hivemind_query_memory(query="<service> env SPRING_PROFILES configmap")` | Helm values |

---

## Sherlock Correlation — Summary Map

### Path A (Sherlock Available)

| What You Need | Sherlock Tool |
|---------------|---------------|
| Error rate, latency, throughput | `mcp_sherlock_get_service_golden_signals(service_name="<service>")` |
| Active incidents on service | `mcp_sherlock_get_service_incidents(service_name="<service>")` |
| K8s pod/container health | `mcp_sherlock_get_k8s_health(service_name="<service>")` |
| Error logs from NR | `mcp_sherlock_search_logs(service_name="<service>", severity="ERROR")` |
| Recent deployments | `mcp_sherlock_get_deployments(app_name="<service>")` |
| APM application metrics | `mcp_sherlock_get_app_metrics(app_name="<service>")` |
| Dependency health | `mcp_sherlock_get_service_dependencies(service_name="<service>")` |
| Full parallel investigation | `mcp_sherlock_investigate_service(service_name="<service>")` |
| Node-level NRQL | `mcp_sherlock_run_nrql_query(nrql="SELECT ... FROM K8sNodeSample ...")` |
| All open alerts | `mcp_sherlock_get_incidents(state="open")` |
| Custom NRQL query | `mcp_sherlock_run_nrql_query(nrql="<query>")` — call `mcp_sherlock_get_nrql_context()` first for templates |

### Path B (Sherlock Unavailable) — Fallback Commands

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

| What You Need | Fallback Command |
|---------------|-----------------|
| Pod resource usage | `kubectl top pod <pod> -n <ns>` |
| Node resource usage | `kubectl top nodes` |
| Raw metrics API | `kubectl get --raw /apis/metrics.k8s.io/v1beta1/namespaces/<ns>/pods` |
| Deployment timing | `kubectl rollout history deployment/<svc> -n <ns>` |
| Recent events (timeline) | `kubectl get events -n <ns> --sort-by='.lastTimestamp' \| tail -30` |
| Container logs | `kubectl logs <pod> -n <ns> --tail=200` |
| Connectivity test | `kubectl exec <pod> -n <ns> -- curl -sv http://<target>:<port>/health` |
| All pod statuses | `kubectl get pods -n <ns> -o wide` |

---

## Output Format — K8S DEBUG REPORT

Every k8s-debug response MUST use this structure:

```
## 🔍 K8S DEBUG REPORT

### Pod / Workload Status
| Field | Value |
|-------|-------|
| Service | <service name> |
| Namespace | <namespace> |
| Pod | <pod name or "multiple"> |
| Status | <pod phase / container state> |
| Restarts | <count> |
| Node | <node name> |
| Decision Tree Path | <status → branch → layer> |

### Investigation Path
<Path A (Sherlock data available) or Path B (Sherlock unavailable — command-based)>

### Layer Findings
<findings from the applicable investigation layer, with specific observations from user-pasted command output>

### KB Cross-Reference (HiveMind)
📋 Finding: <what KB revealed — searched ALL repos for active client>
📁 Sources:
  - `<file_path>` [repo: <repo>, branch: <branch>]
  - `<file_path>` [repo: <repo>, branch: <branch>]

### Observability Correlation
**Path A (Sherlock):**
| Signal | Value | Status |
|--------|-------|--------|
| Error Rate | <value> | 🔴 / 🟡 / 🟢 |
| Latency (p99) | <value> | 🔴 / 🟡 / 🟢 |
| Pod Restarts | <count> | 🔴 / 🟡 / 🟢 |
| Recent Deployment | <timestamp + version> | — |
| Active Alerts | <list> | — |

**OR Path B (Sherlock unavailable):**
⚠️ Sherlock unavailable — proceeding with command-based investigation
| Metric | Source | Value |
|--------|--------|-------|
| Pod CPU/Memory | kubectl top pod | <value> |
| Node Resources | kubectl top nodes | <value> |

### Dependency Check
- 🔍 Origin vs Victim: <is this pod the cause or a downstream victim?>
- Upstream: <services that call this service>
- Downstream: <services this service calls>
- Evidence: <what proves origin/victim status>

### Recommended Next Commands
Run these on your jump host and paste the output back:

**1. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

**2. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

### Root Cause Hypothesis
📋 **Category:** <CONFIG_ERROR / APP_BUG / INFRA_ISSUE / DEPENDENCY_FAILURE / DEPLOYMENT_ERROR / SECRET_EXPIRY / RESOURCE_EXHAUSTION>
📋 **Hypothesis:** <specific statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - KB: `<file>` [repo: <repo>, branch: <branch>] — <what it shows>
  - Sherlock/Cmd: <what live data or command output shows>
  - Logs: <what user-pasted logs show>

### Fix
**🔥 Immediate Mitigation:**
<command for user to run now to stop the bleeding>

**🔧 Permanent Fix:**
File: `<file_path>` [repo: <repo>, branch: <branch>]
- Change: `<key>` from `<old>` to `<new>`
- Reason: <why this fixes the root cause>
(User makes this change — Copilot does NOT stage files)

**🔄 Rollback Path:**
<exact rollback command or Harness pipeline step>

---
## All Sources
| Source | Tool | File / Query | Repo | Branch |
|--------|------|-------------|------|--------|
| KB | <hivemind tool> | <file_path> | <repo> | <branch> |
| KB | <hivemind tool> | <file_path> | <repo> | <branch> |
| Live | <sherlock tool> | <tool(params)> | — | — |
| Cmd | User | <kubectl command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```
