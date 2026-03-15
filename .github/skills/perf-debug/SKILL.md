---
name: perf-debug
description: >
  Performance degradation investigation for any platform. Auto-detects
  observability infrastructure from the HiveMind KB (Sherlock/New Relic APM,
  Spring Boot Actuator, kubectl top, JVM metrics) and application stack
  (Spring Boot, Node.js, Python, Go). Covers 8 failure modes — latency
  degradation, throughput drops, memory leaks, CPU throttling, GC pressure,
  thread exhaustion, dependency slowdown, and resource saturation — with
  playbooks for each. Correlates multiple signals (Golden Signals) and
  pinpoints the deployment or change that caused degradation.
triggers:
  - slow
  - latency
  - performance
  - degraded
  - p99
  - p95
  - p50
  - response time
  - throughput
  - requests per second
  - RPS
  - TPS
  - timeout
  - high CPU
  - CPU throttling
  - memory leak
  - OOM
  - heap
  - GC
  - garbage collection
  - GC pause
  - thread pool
  - thread exhaustion
  - thread dump
  - heap dump
  - profiling
  - slow query
  - N+1
  - cache miss
  - cache hit rate
  - cache eviction
  - memory pressure
  - resource exhaustion
  - saturation
  - burn rate
  - error budget
  - SLO breach
  - slow endpoint
  - high latency
  - latency spike
  - latency percentile
  - apdex
  - apdex score drop
  - New Relic alert
  - NR alert
  - throughput drop
  - traffic drop
  - request rate drop
  - connection pool
  - pool exhaustion
  - circuit breaker
  - retry storm
  - thundering herd
  - backpressure
  - jvm memory
  - heap space
  - metaspace
  - off-heap
  - full gc
  - major gc
  - stop the world
  - gc overhead limit
slash_command: /perf
---

# Perf Debug — Performance Degradation Investigation Playbook

> This skill is the DEEP investigation layer for performance degradation —
> soft failures where things are "working" but not working well. It auto-detects
> the client's observability infrastructure and application stack from the
> HiveMind KB before investigating. Activated after `incident-triage` identifies
> a performance problem, or directly when the user asks about latency, throughput,
> memory leaks, CPU throttling, or any degraded-but-not-crashed condition.
> Auto-detect first. Correlate multiple signals. Skip nothing.
>
> **KEY DISTINCTION:** `incident-triage` and `k8s-debug` handle HARD failures
> (crash, OOM kill, 503). `perf-debug` handles SOFT failures — slow, degraded,
> leaking. Things that are "working" but not working well. These are the hardest
> to debug because nothing is obviously broken.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| PD-1 | **NEVER run commands.** User is on AVD via jump host. Recommend every `kubectl`, `curl`, `jcmd`, `az` command. Wait for paste-back. |
| PD-2 | **NEVER skip Sherlock for perf investigation.** Performance requires time-series data, not just current state. Always query Sherlock first — kubectl top + Actuator are fallback only. |
| PD-3 | **NEVER conclude root cause from single metric.** Always correlate latency + throughput + resources. A single metric can mislead. |
| PD-4 | **NEVER recommend heap dump without explicit user approval.** Heap dumps are disruptive to production pods — always warn and wait for confirmation. |
| PD-5 | **NEVER skip change correlation.** Performance issues almost always start with a deployment or config change. Always check what changed. |
| PD-6 | **NEVER skip dependency analysis.** The service may be a victim, not the cause — always call `hivemind_impact_analysis` to check upstream/downstream. |
| PD-7 | **ALWAYS check if issue is gradual (leak) vs sudden (deployment).** This distinction drives the entire investigation path. |
| PD-8 | **ALWAYS cite file path + repo + branch** for every KB finding. |
| PD-9 | **NEVER block on Sherlock unavailability.** kubectl top + Actuator fallback always ready. |
| PD-10 | **NEVER diagnose hard failure (OOM kill, crash) with this skill.** Redirect to `incident-triage` or `k8s-debug` for hard failures. |

---

## 🔄 SHERLOCK FALLBACK RULE

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use it — correlate p99 latency, throughput, JVM metrics, deployment timing, Golden Signals |
| **Path B** | Sherlock unavailable or no data | Fall back to `kubectl top` + Actuator endpoints, continue seamlessly |

**Path A tools:**
- `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — latency, throughput, error rate, saturation (THE primary tool for perf)
- `mcp_sherlock_search_logs(service_name="<service>", keyword="slow|timeout|latency|gc|heap|thread|pool|exhausted|throttle")` — performance-related logs
- `mcp_sherlock_get_service_incidents(service_name="<service>")` — active NR alerts
- `mcp_sherlock_get_deployments(app_name="<service>")` — deployment timing correlation

**Path B fallback commands:**
```bash
# Current resource usage per pod
kubectl top pods -n <namespace> -l app=<service>

# Node-level resource usage
kubectl top nodes

# Spring Boot Actuator metrics (run from pod or jump host)
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.memory.used
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.gc.pause
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/executor.pool.size

# Performance-related errors in logs
kubectl logs <pod-name> -n <namespace> --tail=300 | grep -iE "slow|timeout|latency|gc|heap|thread|pool|exhausted|throttle"
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Performance Failure Taxonomy — 8 Failure Modes

| ID | Failure Mode | One-Line Signal |
|----|-------------|-----------------|
| **PF-1** | LATENCY DEGRADATION | p99/p95 increasing, responses slowing — all or specific endpoints |
| **PF-2** | THROUGHPUT DROP | RPS/TPS falling without error rate increase — capacity or upstream issue |
| **PF-3** | MEMORY LEAK | Heap growing steadily, GC not reclaiming — monotonic memory increase over time |
| **PF-4** | CPU THROTTLING | Container CPU limit hit, requests queuing — throttled_cpu_seconds increasing |
| **PF-5** | GC PRESSURE | Java GC pauses causing latency spikes — periodic latency spikes correlating with GC events |
| **PF-6** | THREAD EXHAUSTION | Thread pool full, requests queuing — executor.queue.size growing, throughput dropping |
| **PF-7** | DEPENDENCY SLOWDOWN | DB/Service Bus/external API is the bottleneck — service is a victim, not the cause |
| **PF-8** | RESOURCE SATURATION | Approaching limits before hard failure — proactive signal of imminent crash |

---

## Golden Signals — ALWAYS START HERE

Before diving into any specific failure mode, collect the 4 Golden Signals from Sherlock/New Relic:

| Signal | What to Measure | Sherlock Source |
|--------|----------------|-----------------|
| **Latency** | p50/p95/p99 response times | `mcp_sherlock_get_service_golden_signals` |
| **Traffic** | Requests per second (RPS) — is traffic normal or spiking? | `mcp_sherlock_get_service_golden_signals` |
| **Errors** | Error rate — is this a performance issue or error cascade? | `mcp_sherlock_get_service_golden_signals` |
| **Saturation** | CPU%, memory%, thread pool utilization | `mcp_sherlock_get_service_golden_signals` + kubectl top |

**From these 4 signals, classify the failure mode BEFORE diving deep.**

### Decision Matrix — Golden Signals to Failure Mode

| Latency | Traffic | Errors | Saturation | → Failure Mode |
|---------|---------|--------|------------|----------------|
| ↑ | Normal | Normal | Normal | **PF-1** (latency degradation) or **PF-5** (GC) or **PF-7** (dependency) |
| ↑ | ↑ | Normal | ↑ | **PF-4** (CPU throttling) or **PF-6** (thread exhaustion) or **PF-8** (saturation) |
| Normal | ↓ | Normal | Normal | **PF-2** (throughput drop) or **PF-6** (thread exhaustion — upstream drop) |
| ↑ over time | Normal | Normal | Memory ↑ | **PF-3** (memory leak) |
| Spiky (not sustained) | Normal | Normal | GC spikes | **PF-5** (GC pressure) |
| ↑ on specific endpoints | Normal | Normal | Normal | **PF-7** (dependency slowdown) |

---

## Sherlock-First Approach — Mandatory Queries

Unlike other skills where Sherlock is optional (Path A/B), perf-debug makes Sherlock PRIMARY because:
- Performance issues require time-series data
- kubectl can't show historical metrics
- New Relic has p99 latency, throughput, JVM metrics

**MANDATORY Sherlock queries (run ALL at start of every investigation):**

| # | Query | Purpose |
|---|-------|---------|
| S-1 | p99 response time for affected service (last 1h, 24h, 7d) | Establish latency baseline and trend |
| S-2 | throughput (RPS) for affected service (same windows) | Determine if traffic changed |
| S-3 | error rate for affected service | Distinguish performance issue from error cascade |
| S-4 | CPU + memory utilization for affected service pods | Resource saturation check |
| S-5 | JVM heap utilization if Java service (GC metrics) | Memory leak / GC pressure detection |
| S-6 | DB query time from APM (downstream dependency) | Is the DB the bottleneck? |
| S-7 | When did degradation start? (find the inflection point) | Critical for change correlation |
| S-8 | Did a deployment coincide with degradation start? | Deployment-caused regression check |

**IF Sherlock unavailable — fallback commands (kubectl):**
```bash
# Current resource usage
kubectl top pods -n <namespace> -l app=<service>
kubectl top nodes

# Spring Boot Actuator JVM metrics
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.memory.used
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.gc.pause
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/executor.pool.size

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

---

## Auto-Detection Phase — ALWAYS RUN FIRST

Before investigating ANY performance issue, determine what observability and stack this client has. **Never assume.**

### Step 1 — Query KB for Observability & Stack

```
STEP 1: Call hivemind_get_active_client()
        → Determines which client KB to search

STEP 2: Query KB for observability and stack:
  hivemind_query_memory(client=<client>, query="<service> new relic sherlock APM observability")
  hivemind_query_memory(client=<client>, query="<service> actuator spring-boot jvm metrics")
  hivemind_query_memory(client=<client>, query="<service> resources limits requests cpu memory")
  hivemind_query_memory(client=<client>, query="<service> thread pool executor async")
  hivemind_query_memory(client=<client>, query="<service> cache caffeine redis ehcache")
  hivemind_query_memory(client=<client>, query="<service> circuit breaker resilience4j retry")

STEP 3: Read discovered_profile.yaml:
  memory/clients/<client>/discovered_profile.yaml
  → Understand client stack, services, environments
```

### Step 2 — Classify Detected Stack

| Platform | Detection Signal | What It Means |
|----------|-----------------|---------------|
| **Spring Boot / JVM** | Found `spring-boot`, `jvm`, `actuator`, `Xmx` in KB | Java application — JVM metrics available |
| **Node.js** | Found `node`, `express`, `package.json`, `event loop` in KB | Node.js — event loop metrics, V8 heap |
| **Python** | Found `django`, `flask`, `fastapi`, `uvicorn` in KB | Python — asyncio, memory_profiler |
| **Go** | Found `go`, `pprof`, `goroutine` in KB | Go — pprof endpoints, goroutine metrics |

### Step 3 — State Detection Results

Before proceeding to investigation layers, ALWAYS output detection results:

```
Detected observability for <client>/<service>:
  ✓ Sherlock/New Relic APM (found NR agent config in KB)
  ✓ Spring Boot Actuator (found actuator endpoints in KB)
  ✓ JVM metrics (found Xmx/GC config in KB)
  ✗ Custom metrics endpoint (not found in KB)
Stack: Spring Boot / JVM (detected from KB)
Investigating relevant layers...
```

---

## Investigation Layers — Run Based on Golden Signal Classification

### LAYER 1 — LATENCY INVESTIGATION (PF-1)

**Signals:** p99/p95/p50 response times increasing. All percentiles up = systemic. Only p99 up = outlier requests.

**Step 1 — Sherlock — get latency breakdown:**

```
mcp_sherlock_get_service_golden_signals(service_name="<service>")
```

- p99 vs p95 vs p50 — are all percentiles up, or just p99?
- If only p99 up → outlier requests, not systemic
- If all percentiles up → systemic slowdown
- Which endpoints are slowest? (NR transaction breakdown)

**Step 2 — Find the slow component:**

- Is latency from the service itself, or waiting for DB/external?
- NR APM distributed tracing: which span is slowest?
- If DB span slow → **PF-7**, investigate with `db-debug` skill
- If service span slow → **PF-4** or **PF-5** or **PF-6**

**Step 3 — KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> timeout connection-timeout")
hivemind_query_memory(client=<client>, query="<service> async CompletableFuture")
hivemind_query_memory(client=<client>, query="<service> circuit breaker resilience4j")
```
Look for: timeout values, retry configs, circuit breaker thresholds

**Step 4 — Check for recent changes:**
```
hivemind_diff_branches(client=<client>, repo="<service-repo>", base="<previous-release>", compare="<current-release>")
```
Look for: new dependencies, changed timeout values, new DB queries

**Sherlock fallback:**
```bash
kubectl logs <pod-name> -n <namespace> --tail=500 | grep -iE "took [0-9]+ ms|elapsed|duration|slow"
```

---

### LAYER 2 — THROUGHPUT DROP INVESTIGATION (PF-2)

**Signals:** RPS/TPS falling without error rate increase. Processed requests declining.

**Step 1 — Sherlock — distinguish traffic drop from throughput drop:**

- Is incoming traffic also down? (external traffic drop = not our problem)
- Is only processed throughput down while traffic is normal? (our problem)
- Check upstream services: are THEY seeing throughput drop?

**Step 2 — Check for circuit breaker open:**
```
hivemind_query_memory(client=<client>, query="<service> CircuitBreaker resilience4j")
```
Sherlock: look for sudden drop to near-zero (circuit breaker open pattern)
```bash
kubectl logs <pod-name> -n <namespace> --tail=200 | grep -i "circuit breaker\|CircuitBreakerOpen"
```

**Step 3 — Check for thread pool / queue backup:**
```bash
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/executor.pool.size
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/executor.queue.size
```
If queue full → requests being rejected → throughput drop

**Step 4 — Check for backpressure from dependencies:**
```
hivemind_impact_analysis(client=<client>, entity="<service>")
```
If downstream dependency slow → upstream backs up → throughput drop

---

### LAYER 3 — MEMORY LEAK INVESTIGATION (PF-3)

**Signals:** Heap growing monotonically over time. GC frequency increasing but not reclaiming. Pod restarts (OOMKilled) in last 7 days.

Memory leaks are time-based — requires historical data.

**Step 1 — Sherlock — establish leak pattern:**

- JVM heap used over 24h/7d: is it growing monotonically?
- GC frequency: increasing? (sign of leak — GC runs more often)
- Memory released after GC: is it returning to baseline?
- Pod restarts: OOMKilled in last 7 days? (leak reaching limit)

**Step 2 — Check heap config vs container limit:**
```
hivemind_query_memory(client=<client>, query="<service> Xmx Xms heap")
hivemind_query_memory(client=<client>, query="<service> memory limits resources")
```
Calculate: Xmx + metaspace + off-heap overhead vs container limit
If Xmx is unset → JVM uses 25% of container memory (often too low)

**Step 3 — Identify leak source type:**

| Type | Symptoms | Common Causes |
|------|----------|---------------|
| **Heap leak** | Application objects not being GC'd | Cache without eviction, session accumulation, static collection refs |
| **Metaspace leak** | Class loader leak | Reflection-heavy frameworks, dynamic proxy generation |
| **Off-heap leak** | Native memory, direct ByteBuffers | Thread stacks, NIO direct buffers, JNI |

**Step 4 — Recommend heap dump if leak confirmed:**

> ⚠️ **DISRUPTIVE OPERATION — requires explicit user approval before recommending.**
> Heap dump freezes the JVM. Run on non-live pod if possible.

```bash
# GET USER APPROVAL BEFORE RECOMMENDING THIS COMMAND
kubectl exec <pod-name> -n <namespace> -- jcmd 1 GC.heap_dump /tmp/heapdump.hprof
kubectl cp <pod-name>:/tmp/heapdump.hprof ./heapdump.hprof -n <namespace>
```

**Step 5 — KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> cache Caffeine Ehcache")
hivemind_query_memory(client=<client>, query="<service> static singleton")
hivemind_query_memory(client=<client>, query="<service> ThreadLocal")
```

**Sherlock fallback:**
```bash
# Watch memory over time (run multiple times, minutes apart)
kubectl top pod <pod-name> -n <namespace>

# Spring Boot Actuator JVM memory
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.memory.used
```
Compare calls over time to see growth.

---

### LAYER 4 — CPU THROTTLING INVESTIGATION (PF-4)

**Signals:** Container CPU% approaching limit. Latency correlating with CPU spikes. Kubernetes throttled_cpu_seconds_total increasing.

**Step 1 — Sherlock — confirm CPU throttling:**

- Container CPU% approaching limit?
- Kubernetes `throttled_cpu_seconds_total` metric (if available)
- Request latency correlating with CPU spikes?

**Step 2 — Check CPU limits in KB:**
```
hivemind_query_memory(client=<client>, query="<service> cpu limits resources requests")
```
Look for: requests vs limits ratio
If cpu limit = cpu request → burst not possible → any spike = throttle

**Step 3 — Check what's consuming CPU:**
```bash
kubectl exec <pod-name> -n <namespace> -- top -b -n 1
kubectl exec <pod-name> -n <namespace> -- jcmd 1 Thread.print
```
High CPU + many threads = thread contention
High CPU + few threads = CPU-intensive code path

**Step 4 — Check for CPU-intensive operations triggered by recent deploy:**
```
hivemind_diff_branches(client=<client>, repo="<service-repo>", base="<prev-release>", compare="<current-release>")
```
Look for: new serialization, new encryption, new compression, regex

**Step 5 — Check Istio sidecar CPU overhead:**
```bash
kubectl top pod <pod-name> --containers -n <namespace>
```
If istio-proxy consuming significant CPU → Istio config issue

---

### LAYER 5 — GC PRESSURE INVESTIGATION (PF-5, Java only)

*(Skip if non-JVM stack detected in KB)*

GC pressure signature: latency is spiky, not sustained. Spikes correlate with GC pause events.

**Step 1 — Sherlock — GC correlation:**

- Are latency spikes periodic? (matches GC schedule)
- JVM GC pause time metric — is it increasing?
- Full GC events — frequency and duration

**Step 2 — Check GC configuration in KB:**
```
hivemind_query_memory(client=<client>, query="<service> GC garbage JVM_OPTS")
```
Look for: GC algorithm (G1GC default for Java 11+), heap size, GC tuning flags

**Step 3 — Identify GC type:**

| GC Type | Frequency | Duration | Concern Level |
|---------|-----------|----------|---------------|
| **Minor GC** (Young Gen) | Frequent | Short (ms) | Normal unless extremely frequent |
| **Major GC** (Old Gen) | Less frequent | Longer (100s of ms) | Concerning if frequent |
| **Full GC** | Rare | Stop-the-world (seconds) | Always investigate — service freezes |

**Step 4 — Recommend GC log analysis:**
```bash
kubectl exec <pod-name> -n <namespace> -- jcmd 1 GC.heap_info
kubectl logs <pod-name> -n <namespace> --tail=200 | grep -iE "GC|pause|safepoint"
```
(if `-Xlog:gc*` or `-verbose:gc` is in JVM args)

**Step 5 — Common GC fixes:**
- Increase heap: raise Xmx (but check container limit)
- Switch GC: G1GC → ZGC for lower pause times
- Tune G1GC: `-XX:MaxGCPauseMillis=200`
- Reduce allocation rate: find hot allocation paths in Sherlock APM

---

### LAYER 6 — THREAD EXHAUSTION INVESTIGATION (PF-6)

**Signals:** executor.pool.size at maximum, executor.queue.size growing, throughput dropping while requests back up.

**Step 1 — Sherlock — thread pool metrics:**

- `executor.pool.size` vs `executor.active.count`
- `executor.queue.size` (requests waiting)
- If queue growing → throughput drop but requests backing up

**Step 2 — Check thread pool config in KB:**
```
hivemind_query_memory(client=<client>, query="<service> ThreadPoolTaskExecutor thread-pool")
hivemind_query_memory(client=<client>, query="<service> server.tomcat.threads spring.task")
```
Look for: max-threads, core-pool-size, queue-capacity

**Step 3 — Get thread dump if pool full:**
```bash
kubectl exec <pod-name> -n <namespace> -- jcmd 1 Thread.print
```
Look for: threads all in WAITING or BLOCKED state
If many threads waiting on DB connection → pool exhaustion (→ `db-debug`)
If many threads in BLOCKED → lock contention

**Step 4 — Check async patterns in KB:**
```
hivemind_query_memory(client=<client>, query="<service> @Async CompletableFuture")
```
Uncontrolled async → thread explosion

---

### LAYER 7 — DEPENDENCY SLOWDOWN INVESTIGATION (PF-7)

Most common cause of latency: the service is fine, its dependency is slow.

**Step 1 — Sherlock — distributed trace analysis:**

- NR APM: which downstream call is adding latency?
- Database call time: is it exceeding normal?
- External HTTP calls: which upstream is slow?

**Step 2 — Identify the slow dependency:**
```
hivemind_impact_analysis(client=<client>, entity="<service>")
```
For each slow dependency found in traces:
→ If DB slow: invoke `db-debug` skill
→ If another service slow: invoke this skill recursively for that service
→ If external API slow: check if timeout/retry is configured

**Step 3 — Check for missing caching:**
```
hivemind_query_memory(client=<client>, query="<service> cache @Cacheable")
```
If expensive DB call has no caching → every request hits DB

**Step 4 — Check for N+1 queries:**

Sherlock: DB call count per transaction — is it very high?
```
hivemind_query_memory(client=<client>, query="<service> @OneToMany FetchType.LAZY")
```
N+1 pattern: 1 parent query + N child queries per request

---

### LAYER 8 — RESOURCE SATURATION INVESTIGATION (PF-8)

Saturation: approaching limits before hitting them. This is proactive investigation — service is degrading before crashing.

**Step 1 — Sherlock — resource utilization trends:**

- CPU: approaching limit? (> 80% consistently)
- Memory: approaching limit? (> 85% — OOMKill risk)
- Pod restarts in last 7 days (leading indicator)
- HPA: is autoscaling triggered? (means demand > capacity)

**Step 2 — Check limits and requests in KB:**
```
hivemind_query_memory(client=<client>, query="<service> resources limits requests")
```
Check: limits set? requests set? ratio of limit to request

**Step 3 — Check HPA configuration:**
```
hivemind_query_memory(client=<client>, query="<service> HorizontalPodAutoscaler hpa")
```
```bash
kubectl get hpa -n <namespace>
```
If HPA maxReplicas reached → can't scale further → saturation

**Step 4 — Check node capacity:**
```bash
kubectl describe node <node-name> | grep -A5 "Allocated resources"
```
If node at 90%+ → pods can't get more resources even if limits allow

---

## Change Correlation — MANDATORY FOR EVERY PERF INVESTIGATION

Performance issues almost always start with a change. Always run this sequence:

**Step 1:** Find when degradation started (from Sherlock inflection point)

**Step 2:** Check what changed around that time:
```
hivemind_diff_branches(client=<client>, repo="<service-repo>", base="<prev-release>", compare="<current-release>")
```
Sherlock: deployment marker at degradation start?

**Step 3:** Check if it's gradual (leak/saturation) or sudden (deployment):
- **Sudden** = deployment introduced regression
- **Gradual** = leak or growing load

**Step 4:** If deployment-correlated:
```
hivemind_get_pipeline(client=<client>, name="<pipeline>")
```
What image/version was deployed at that time?

---

## KB Cross-Reference Map — For All Performance Investigations

```
hivemind_query_memory(client=<client>, query="<service> resources limits requests")
hivemind_query_memory(client=<client>, query="<service> timeout connection-timeout")
hivemind_query_memory(client=<client>, query="<service> thread pool executor")
hivemind_query_memory(client=<client>, query="<service> cache caffeine redis")
hivemind_query_memory(client=<client>, query="<service> circuit breaker resilience4j")
hivemind_query_memory(client=<client>, query="<service> retry backoff")
hivemind_impact_analysis(client=<client>, entity="<service>")
hivemind_diff_branches(client=<client>, repo="<repo>", base="<base>", compare="<compare>")
```

---

## Blast Radius Check — NEVER SKIP

Performance degradation cascades via:
- Slow service holding connections from callers → callers degrade
- Memory leak → eventual OOMKill → downstream sees errors
- Thread exhaustion → requests queue → timeouts cascade upstream

**After identifying ANY performance issue:**

```
# 1. Impact analysis on affected service
hivemind_impact_analysis(client=<client>, entity="<service>")

# 2. Check if caller services also show latency increase
# Sherlock: query Golden Signals for each caller service

# 3. Determine cascade direction
# Is this service the CAUSE or a VICTIM?
```

**Report format:**
```
### Blast Radius
| Affected Service | Relationship | Latency Impact? | Cascade Risk |
|-----------------|-------------|-----------------|-------------|
| <service-1> | Calls <degraded-service> | Yes — p99 up | 🔴 HIGH |
| <service-2> | Calls <degraded-service> | Not yet | 🟡 MEDIUM |
| <service-3> | Independent | No | 🟢 LOW |

Cascade risk level: HIGH / MEDIUM / LOW
Direction: <degraded-service> is CAUSE / VICTIM
```

---

## Sherlock Correlation

### Path A — Sherlock Available

```
mcp_sherlock_get_service_golden_signals(service_name="<service>")
mcp_sherlock_search_logs(service_name="<service>", keyword="slow|timeout|latency|gc|heap|thread|pool|exhausted|throttle")
mcp_sherlock_get_service_incidents(service_name="<service>")
mcp_sherlock_get_deployments(app_name="<service>")
```

Look for:
- p99/p95/p50 latency trends over 1h, 24h, 7d
- Throughput (RPS) changes — load spike or drop?
- JVM heap/GC metrics — memory leak or GC pressure?
- Error rate — performance issue or error cascade?
- Deployment timing — did perf degrade after a deploy?

### Path B — Sherlock Unavailable

```bash
# Resource usage
kubectl top pods -n <namespace> -l app=<service>
kubectl top nodes

# JVM metrics via Actuator
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.memory.used
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.gc.pause
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/executor.pool.size
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.active

# Performance-related logs
kubectl logs <pod-name> -n <namespace> --tail=300 | grep -iE "slow|timeout|latency|gc|heap|thread|pool|exhausted|throttle"

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Failure Mode Playbooks

### PF-1: LATENCY DEGRADATION

**How to confirm:** p99/p95 response times increasing. Sherlock Golden Signals show latency trend upward. If all percentiles up → systemic. If only p99 → outlier requests.

**Investigation layers to run:** Layer 1 (Latency), Layer 7 (Dependency — is the service or its dependency slow?)

**Most likely root cause:** New code path adding latency, missing cache causing repeated expensive operations, or dependency (DB, external API) response time increase.

**File to fix:** Application code or dependency config.
Typical path: `src/main/java/.../service/<Service>Service.java` or `charts/<service>/values.yaml` → timeout config [repo: service repo, branch: environment branch]

**Remediation:**
- **Immediate:** Check if specific endpoints are slow (NR transaction breakdown). If dependency slow → address dependency first.
- **Permanent:** Add caching for expensive operations. Optimize slow DB queries (invoke `db-debug`). Tune timeout values to fail fast instead of hanging.

**Common gotcha:** p99 latency can be outliers — check p95 too before panicking. A handful of slow requests can skew p99 while p95 and p50 remain healthy. Always compare multiple percentiles.

---

### PF-2: THROUGHPUT DROP

**How to confirm:** RPS/TPS falling in Sherlock but error rate NOT increasing. Requests are being processed slower, not failing.

**Investigation layers to run:** Layer 2 (Throughput), Layer 6 (Thread Exhaustion)

**Most likely root cause:** Thread pool saturated, circuit breaker open on a dependency, or upstream sending less traffic (not our problem).

**File to fix:** Thread pool config or circuit breaker config.
Typical path: `charts/<service>/values.yaml` → `spring.task.execution.pool` or `resilience4j.circuitbreaker` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Check if upstream traffic actually dropped (compare external LB metrics). Check circuit breaker state.
- **Permanent:** Right-size thread pools. Configure circuit breaker with appropriate thresholds.

**Common gotcha:** Throughput drop can be upstream sending less traffic — check if it's our problem or theirs first. Compare incoming request rate at the load balancer vs processed rate at the service.

---

### PF-3: MEMORY LEAK

**How to confirm:** JVM heap used grows monotonically over hours/days. GC runs more frequently but reclaims less each time. Eventually OOMKilled pod restarts.

**Investigation layers to run:** Layer 3 (Memory Leak)

**Most likely root cause:** Cache without eviction policy, session objects accumulating, static collections growing unbounded, or ThreadLocal values not cleaned up.

**File to fix:** Application code adding to unbounded collections.
Typical path: `src/main/java/.../service/<Service>Service.java` or `src/main/java/.../config/<Cache>Config.java` [repo: service repo]

**Remediation:**
- **Immediate:** Restart pods to reclaim memory (buys time). Scale horizontally if needed.
- **Permanent:** Add cache eviction policy (`maximumSize` or `expireAfterWrite` in Caffeine). Fix ThreadLocal cleanup. Add `leak-detection-threshold` for connection pools.

> ⚠️ **Heap dump warning:** Getting a heap dump is disruptive — JVM freezes during dump. Always get explicit user approval. Run on non-live pod if possible.

**Common gotcha:** Heap dump on production pod is disruptive — always get user approval, run on non-live pod if possible. A 4GB heap dump can take 30+ seconds during which the service is frozen.

---

### PF-4: CPU THROTTLING

**How to confirm:** Container CPU usage at or near limit. Kubernetes `throttled_cpu_seconds_total` increasing. Latency spikes correlating with CPU spikes.

**Investigation layers to run:** Layer 4 (CPU Throttling)

**Most likely root cause:** CPU limit set too low for actual workload, or new code path introduced CPU-intensive operation (serialization, encryption, compression, regex).

**File to fix:** CPU limits in Helm values or application code.
Typical path: `charts/<service>/values.yaml` → `resources.limits.cpu` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Increase CPU limit temporarily (after profiling).
- **Permanent:** Profile the CPU-intensive code path. Optimize before raising limits. Check if Istio sidecar is consuming significant CPU.

**Common gotcha:** Increasing CPU limit doesn't fix bad code — profile first, optimize second, raise limit last. Raising limits masks the real problem and costs more infrastructure spend.

---

### PF-5: GC PRESSURE

**How to confirm:** Latency spikes are periodic (not sustained), correlating with GC pause events. Full GC events visible in JVM metrics. Stop-the-world pauses in GC logs.

**Investigation layers to run:** Layer 5 (GC Pressure)

**Most likely root cause:** Heap too small for allocation rate, objects promoted to Old Gen too quickly, or excessive object creation per request.

**File to fix:** JVM GC configuration.
Typical path: `charts/<service>/values.yaml` → `JAVA_OPTS` or `JVM_OPTS` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Increase heap (raise `-Xmx`) if container limit allows.
- **Permanent:** Switch to ZGC for lower pause times (`-XX:+UseZGC`). Tune G1GC pause target (`-XX:MaxGCPauseMillis=200`). Reduce allocation rate by optimizing hot paths.

**Common gotcha:** Switching to ZGC reduces pauses but uses more CPU — don't switch if already CPU throttled (PF-4). Check CPU headroom before changing GC algorithm.

---

### PF-6: THREAD EXHAUSTION

**How to confirm:** `executor.pool.size` = max, `executor.queue.size` growing, throughput dropping. Thread dump shows most threads in WAITING or BLOCKED state.

**Investigation layers to run:** Layer 6 (Thread Exhaustion)

**Most likely root cause:** All threads waiting on a slow dependency (DB, external API), lock contention, or uncontrolled `@Async` creating too many threads.

**File to fix:** Thread pool configuration or async code.
Typical path: `src/main/resources/application.yaml` → `spring.task.execution.pool` or `server.tomcat.threads.max` [repo: service repo]

**Remediation:**
- **Immediate:** Take thread dump to identify what threads are waiting on. If all waiting on DB → investigate DB pool.
- **Permanent:** Fix the blocking call (make async, add timeout). Right-size thread pool based on workload.

**Common gotcha:** Increasing thread pool size can make DB pool exhaustion worse — check what threads are waiting on before increasing pool. If 200 threads all waiting on a 10-connection DB pool, adding more threads just adds more waiters.

---

### PF-7: DEPENDENCY SLOWDOWN

**How to confirm:** Service latency up, but NR APM distributed tracing shows the slow span is a downstream call (DB, another service, external API). Service's own processing time is normal.

**Investigation layers to run:** Layer 7 (Dependency Slowdown)

**Most likely root cause:** The service is a VICTIM, not the cause. Its dependency became slow — DB query regression, downstream service degradation, or external API latency increase.

**File to fix:** Dependency timeout/retry config, or fix the dependency itself.
Typical path: `charts/<service>/values.yaml` → timeout configs or `src/main/java/.../config/<Client>Config.java` [repo: service repo]

**Remediation:**
- **Immediate:** Identify which dependency is slow (from NR distributed trace). Investigate that dependency directly.
- **Permanent:** Add caching to reduce dependency calls (`@Cacheable`). Add appropriate timeouts to fail fast. Configure circuit breaker to stop calling failing dependency.

**Common gotcha:** Adding retry on slow dependency causes retry storms — check if retry is configured with backoff and jitter. Retrying a slow call 3 times means 3x the load on an already-struggling dependency.

---

### PF-8: RESOURCE SATURATION

**How to confirm:** Resource utilization consistently > 80% CPU or > 85% memory. HPA scaling triggered. Pod restarts in last 7 days. This is a leading indicator before hard failure.

**Investigation layers to run:** Layer 8 (Resource Saturation)

**Most likely root cause:** Growth in traffic beyond current capacity, or resource limits not adjusted after feature additions. HPA maxReplicas may be reached.

**File to fix:** Resource limits and HPA config.
Typical path: `charts/<service>/values.yaml` → `resources.limits` and `autoscaling` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Scale up (increase replicas or resource limits). Check HPA max.
- **Permanent:** Right-size resources based on load testing. Increase HPA maxReplicas. Consider node pool scaling.

**Common gotcha:** HPA scaling takes 2-3 minutes — saturation can cause cascading failures during the scale-up window. If the service is already saturated when HPA triggers, requests queue and time out before new pods are ready.

---

## Spring Boot / JVM Performance Patterns

> **Note:** This section applies to Spring Boot / JVM platform services.
> For non-JVM platforms, equivalent patterns exist — search KB for equivalent
> config in your stack.

### Actuator Endpoints for Performance

| Endpoint | What It Shows |
|----------|--------------|
| `/actuator/metrics/jvm.memory.used` | Current JVM heap usage |
| `/actuator/metrics/jvm.gc.pause` | GC pause times |
| `/actuator/metrics/executor.pool.size` | Thread pool size |
| `/actuator/metrics/executor.active` | Active threads |
| `/actuator/metrics/executor.queue.size` | Queued tasks |
| `/actuator/metrics/hikaricp.connections.active` | Active DB connections |
| `/actuator/health` | Application health status |
| `/actuator/threaddump` | Thread states without exec |

### Key JVM Flags

| Flag | Purpose |
|------|---------|
| `-Xmx` / `-Xms` | Heap size (max / initial) |
| `-XX:+UseG1GC` | G1 garbage collector (default Java 11+) |
| `-XX:+UseZGC` | ZGC — low-pause GC (Java 15+) |
| `-XX:MaxGCPauseMillis=200` | G1GC pause time target |
| `-Xlog:gc*` | Enable GC logging |
| `-XX:+HeapDumpOnOutOfMemoryError` | Auto-dump on OOM |

### Diagnostic Commands (JVM)

```bash
# Thread dump (shows thread states)
kubectl exec <pod-name> -n <namespace> -- jcmd 1 Thread.print

# Heap info (shows GC stats)
kubectl exec <pod-name> -n <namespace> -- jcmd 1 GC.heap_info

# Heap dump (⚠️ DISRUPTIVE — get user approval first)
kubectl exec <pod-name> -n <namespace> -- jcmd 1 GC.heap_dump /tmp/heapdump.hprof

# Thread dump via Actuator (non-disruptive)
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/threaddump
```

### Spring Boot Performance Gotchas

| Gotcha | What Happens | How to Detect | Fix |
|--------|-------------|--------------|-----|
| **Open Session in View** | `spring.jpa.open-in-view=true` (default!) holds DB connection for entire HTTP request | Connection pool holds connections longer → pool exhaustion under load | Set `spring.jpa.open-in-view=false` |
| **N+1 Query Problem** | `@OneToMany` without fetch strategy = N separate queries per request | Enable `spring.jpa.show-sql=true` in dev, check NR DB call count per transaction | Use `@EntityGraph` or `JOIN FETCH` |
| **Uncontrolled @Async** | `@Async` without custom executor uses `SimpleAsyncTaskExecutor` (unbounded threads) | Thread count grows unbounded → OOM | Configure `ThreadPoolTaskExecutor` with max size |
| **Missing cache eviction** | `@Cacheable` without `maximumSize` or TTL → cache grows forever | Heap grows monotonically → PF-3 | Add `Caffeine` with `maximumSize` and `expireAfterWrite` |
| **Tomcat thread default** | `server.tomcat.threads.max=200` (default) may be too low or too high | 200 threads × blocking DB calls = 200 DB connections needed | Right-size based on DB pool and workload |
| **Virtual threads (Java 21)** | If enabled, thread exhaustion (PF-6) looks different — no traditional pool saturation | Check for `spring.threads.virtual.enabled=true` | Virtual threads still block on synchronized — check for pinning |

### Non-JVM Platform Equivalents

| Platform | Profiling | Memory | Event Loop / Threading |
|----------|-----------|--------|----------------------|
| **Node.js** | `--inspect` flag, clinic.js | V8 heap snapshot, `process.memoryUsage()` | Event loop lag (`perf_hooks`) |
| **Python** | py-spy, cProfile | memory_profiler, tracemalloc | asyncio debug mode, `asyncio.get_event_loop().slow_callback_duration` |
| **Go** | pprof endpoints (`/debug/pprof/`) | `GODEBUG=gctrace=1` | goroutine count (`/debug/pprof/goroutine`) |

---

## Output Format — PERF DEBUG REPORT

Every perf-debug response MUST use this structure:

```
## 📊 PERF DEBUG REPORT

### Golden Signals Summary
| Signal | Current | Baseline | Trend |
|--------|---------|----------|-------|
| Latency (p99) | <value> | <baseline> | ↑/↓/→ |
| Traffic (RPS) | <value> | <baseline> | ↑/↓/→ |
| Error Rate | <value> | <baseline> | ↑/↓/→ |
| Saturation (CPU%) | <value> | <limit> | ↑/↓/→ |
| Saturation (Mem%) | <value> | <limit> | ↑/↓/→ |

### Failure Mode Classification
| Field | Value |
|-------|-------|
| Failure Mode | <PF-1 through PF-8: label> |
| Service | <service name> |
| Namespace | <namespace> |
| Stack | <Spring Boot / Node.js / Python / Go> |
| Onset | <sudden (deployment) / gradual (leak/growth)> |
| Investigation Path | <Path A (Sherlock) or Path B (command-based)> |

### Change Correlation
| Field | Value |
|-------|-------|
| Degradation start | <timestamp or "unknown"> |
| Coinciding deployment | <version/image or "none found"> |
| Change type | <code change / config change / traffic change / none> |

### Layer Findings
<findings from each investigated layer with KB citations>
📁 Sources:
  - `<file_path>` [repo: <repo>, branch: <branch>]

### Dependency Analysis
| Field | Value |
|-------|-------|
| Service role | CAUSE / VICTIM |
| Slow dependency | <dependency name or "none — service itself is slow"> |
| Evidence | <NR trace span times or kubectl output> |

### Blast Radius
| Affected Service | Relationship | Latency Impact? | Cascade Risk |
|-----------------|-------------|-----------------|-------------|
| <service> | Calls <degraded> | Yes/No | 🔴/🟡/🟢 |

Cascade risk level: HIGH / MEDIUM / LOW

### Observability Correlation
**Path A (Sherlock):**
| Signal | Value |
|--------|-------|
| p99 latency trend | <increasing/stable/decreasing> |
| Throughput trend | <increasing/stable/decreasing> |
| Error rate | <value> |
| Last deployment | <timestamp> |
| JVM heap trend | <growing/stable> (if JVM) |
| GC pause frequency | <increasing/stable> (if JVM) |

**OR Path B (Sherlock unavailable):**
⚠️ Sherlock unavailable — proceeding with command-based investigation
Recommended commands:
```bash
kubectl top pods -n <namespace> -l app=<service>
kubectl exec <pod-name> -n <namespace> -- curl -s localhost:8080/actuator/metrics/jvm.memory.used
```

### Recommended Commands
Run these on your jump host and paste the output back:

**1. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

### Root Cause
📋 **Failure Mode:** PF-<N>: <label>
📋 **Root Cause:** <specific statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - KB: `<file>` [repo: <repo>, branch: <branch>] — <what it shows>
  - Sherlock: <metric name> — <what it shows>
  - Command output: <what user-pasted output confirmed>

### Fix
**🔥 Immediate Mitigation:**
<command or action to buy time now>

**🔧 Permanent Fix:**
File: `<file_path>` [repo: <repo>, branch: <branch>]
- Change: `<field>` from `<old>` to `<new>`
- Reason: <why this fixes the root cause>
(User makes this change — Copilot does NOT stage files)

**♻️ Pod Restart (after fix applied):**
```bash
kubectl rollout restart deployment/<service> -n <namespace>
```

---
## All Sources
| Source | Tool | File / Query | Repo | Branch |
|--------|------|-------------|------|--------|
| KB | hivemind_query_memory | <file_path> | <repo> | <branch> |
| KB | hivemind_impact_analysis | <entity> | — | — |
| KB | hivemind_diff_branches | <repo> | <base> | <compare> |
| Live | <sherlock tool> | <tool(params)> | — | — |
| Cmd | User | <kubectl/curl command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```
