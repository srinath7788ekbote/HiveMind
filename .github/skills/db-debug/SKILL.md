---
name: db-debug
description: >
  Deep database and messaging investigation for any platform. Auto-detects data
  store infrastructure from the HiveMind KB (PostgreSQL, MySQL, MongoDB, Redis,
  SQL Server, Oracle, Azure Service Bus, AWS SQS, Kafka, RabbitMQ) and connection
  pool technology (HikariCP, c3p0, DBCP2, pg-pool, SQLAlchemy) and migration tool
  (Flyway, Liquibase, Alembic). Covers 8 failure modes with playbooks for each.
triggers:
  - database
  - db
  - postgres
  - postgresql
  - jdbc
  - datasource
  - connection pool
  - HikariCP
  - connection refused
  - connection timeout
  - too many connections
  - connection leak
  - slow query
  - query timeout
  - deadlock
  - lock timeout
  - transaction
  - rollback
  - flyway
  - liquibase
  - migration failed
  - service bus
  - servicebus
  - dead letter
  - DLQ
  - message processing
  - queue depth
  - poison message
  - AMQP
  - replication lag
  - replica
  - primary failover
  - PoolExhaustedException
  - SQLTimeoutException
  - DataAccessException
  - JdbcSQLException
  - org.postgresql
  - com.zaxxer.hikari
  - HikariPool
  - mysql
  - mongodb
  - redis
  - cosmos
  - sqlserver
  - oracle
  - rabbitmq
  - kafka
  - sqs
slash_command: /db
---

# DB Debug — Database & Messaging Investigation Playbook

> This skill is the DEEP investigation layer for database, connection pool,
> migration, and messaging failures on any platform. It auto-detects the client's
> data store infrastructure from the HiveMind KB before investigating. Activated
> after `incident-triage` or `k8s-debug` identifies a database/messaging problem,
> or directly when the user asks about database issues.
> Auto-detect first. Investigate what exists. Skip nothing.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| DB-C1 | **NEVER run commands.** User is on AVD via jump host. Recommend every `psql`, `mysql`, `mongosh`, `redis-cli`, `kubectl`, `az` command. Wait for paste-back. |
| DB-C2 | **NEVER assume PostgreSQL or Service Bus.** Always auto-detect data store infrastructure from KB first. Never hardcode a specific DB or messaging platform — the KB tells you what exists. |
| DB-C3 | **NEVER skip blast radius check.** DB failures cascade — all services sharing a database or message topic are affected. Always call `hivemind_impact_analysis`. |
| DB-C4 | **NEVER block on Sherlock.** If unavailable, fall back to `kubectl logs` grep commands immediately. |
| DB-C5 | **ALWAYS check pool size × pod count vs DB max_connections.** Connection pool exhaustion is the #1 DB failure mode — always calculate total connections. |
| DB-C6 | **ALWAYS check if deployment coincided with DB issue start.** Most DB issues are caused by code changes, not infrastructure failures. |
| DB-C7 | **ALWAYS check if problem is connection pool OR actual DB.** Pool wait time vs query execution time determines root cause. |
| DB-C8 | **ALWAYS cite file path + repo + branch** for every KB finding. |
| DB-C9 | **ALWAYS provide exact file path + repo + branch + what to change.** User makes all changes — Copilot does NOT stage files. |
| DB-C10 | **Commands MUST be copy-paste ready** with `<placeholder>` markers. `psql` commands marked as "run from DB pod or jump host". `az servicebus` commands marked as "run from jump host with az cli". |

---

## 🔄 SHERLOCK FALLBACK RULE

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use it — correlate DB connection errors, response time, throughput drops, deployment timing |
| **Path B** | Sherlock unavailable or no data | Fall back to `kubectl logs` grep commands, continue seamlessly |

**Path A tools:**
- `mcp_sherlock_search_logs(service_name="<service>", keyword="hikari|connection|jdbc|timeout|deadlock|servicebus|sql")` — DB failure logs
- `mcp_sherlock_get_service_incidents(service_name="<service>")` — active alerts
- `mcp_sherlock_get_deployments(app_name="<service>")` — deployment timing correlation
- `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — throughput drop / error rate spike

**Path B fallback commands:**
```bash
# DB/connection errors in pod logs
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "hikari\|connection\|jdbc\|timeout\|deadlock\|servicebus\|sql\|pool"

# Current container DB errors
kubectl logs <pod-name> -n <namespace> --tail=200 | grep -iE "(HikariPool|SQLException|DataAccessException|ServiceBus|connection refused|pool exhausted)"

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Database Failure Taxonomy — 8 Failure Modes

| ID | Failure Mode | One-Line Signal |
|----|-------------|-----------------|
| **DB-1** | CONNECTION POOL EXHAUSTED | No connections available — requests timing out waiting for pool |
| **DB-2** | SLOW QUERY / TIMEOUT | Query exceeds timeout threshold — statements cancelled or hanging |
| **DB-3** | MIGRATION FAILED | Flyway/Liquibase/Alembic migration error on startup — service won't start |
| **DB-4** | DEADLOCK | Transactions blocking each other — concurrent updates on same rows |
| **DB-5** | REPLICATION LAG | Replica falling behind primary — stale reads from read replicas |
| **DB-6** | PRIMARY FAILOVER | Primary DB unreachable — failover in progress or completed |
| **DB-7** | SERVICE BUS DLQ | Messages accumulating in dead letter queue — not being processed |
| **DB-8** | SERVICE BUS PROCESSING FAILURE | Messages failing to process — retry loops or consumer errors |

---

## Auto-Detection Phase — ALWAYS RUN FIRST

Before investigating ANY database or messaging issue, determine what data store infrastructure this client actually has. **Never assume.**

### Step 1 — Query KB for Data Store Infrastructure

```
STEP 1: Call hivemind_get_active_client()
        → Determines which client KB to search

STEP 2: Query KB for data store config:
  hivemind_query_memory(client=<client>, query="datasource jdbc postgres postgresql")
  hivemind_query_memory(client=<client>, query="hikari connection pool maximum-pool-size")
  hivemind_query_memory(client=<client>, query="flyway liquibase migration")
  hivemind_query_memory(client=<client>, query="service bus servicebus amqp topic subscription")
  hivemind_query_memory(client=<client>, query="redis mongodb cosmos mysql sqlserver")

STEP 3: Read discovered_profile.yaml:
  memory/clients/<client>/discovered_profile.yaml
  → Understand client data store infrastructure, services, environments
```

### Step 2 — Classify Detected Infrastructure

| Platform | Detection Signal | What It Means |
|----------|-----------------|---------------|
| **PLATFORM A — PostgreSQL** | Found `jdbc:postgresql`, `spring.datasource`, `pg_` references in KB | PostgreSQL relational database |
| **PLATFORM B — Azure Service Bus** | Found `servicebus` connection string, topic/subscription config in KB | Azure messaging / event-driven architecture |
| **PLATFORM C — Redis / Cache** | Found `spring.redis`, `azure.cache`, `redis-cli` references in KB | In-memory cache / session store |
| **PLATFORM D — MongoDB / CosmosDB** | Found `spring.data.mongodb`, `cosmos`, `mongosh` references in KB | Document database |
| **PLATFORM E — Other RDBMS** | Found `jdbc:mysql`, `jdbc:sqlserver`, `jdbc:oracle` in KB | MySQL, SQL Server, or Oracle relational database |
| **PLATFORM F — Other Messaging** | Found `rabbitmq`, `kafka`, `sqs`, `amqp` references in KB | Non-Azure messaging platform |

**Multiple platforms can coexist — investigate ALL that are detected.**

### Step 3 — Detect Connection Pool Technology

| Pool | Detection Signal | Config Prefix |
|------|-----------------|---------------|
| **HikariCP** (Spring Boot default) | `spring.datasource.hikari.*`, `com.zaxxer.hikari` | `spring.datasource.hikari.maximum-pool-size` |
| **c3p0** | `com.mchange.v2.c3p0.*`, `c3p0.properties` | `c3p0.maxPoolSize` |
| **DBCP2** | `spring.datasource.dbcp2.*`, `commons-dbcp2` | `spring.datasource.dbcp2.max-total` |
| **Node.js pg-pool** | `pool.max`, `pg-pool`, `node-postgres` | `pool.max`, `pool.idleTimeoutMillis` |
| **Python SQLAlchemy** | `pool_size`, `max_overflow`, `create_engine` | `pool_size`, `max_overflow` |

### Step 4 — Detect Migration Tool

| Tool | Detection Signal | History Table |
|------|-----------------|---------------|
| **Flyway** | `spring.flyway.*`, `V*.sql` migration files, `flyway_schema_history` | `flyway_schema_history` |
| **Liquibase** | `spring.liquibase.*`, `changelog.xml`, `DATABASECHANGELOG` | `DATABASECHANGELOG` |
| **Alembic** (Python) | `alembic.ini`, `alembic/versions/`, `alembic_version` table | `alembic_version` |
| **Raw SQL** | Migration scripts in `db/migrations/` or `sql/` directories | Check for migration scripts in repo |

### Step 5 — State Detection Results

Before proceeding to investigation layers, ALWAYS output detection results:

```
Detected data stores for <client>:
  ✓ PostgreSQL via HikariCP (found in KB: application.yaml, values.yaml)
  ✓ Azure Service Bus (found in KB: servicebus config in values.yaml)
  ✓ Flyway migrations (found in KB: V*.sql files in db/migration/)
  ✗ Redis (not found in KB)
  ✗ MongoDB (not found in KB)
Investigating relevant layers...
```

If a platform is NOT detected in KB but the user's error message suggests it exists (e.g., `HikariPool` implies PostgreSQL + HikariCP), note:
```
⚠️ PostgreSQL not explicitly found in KB — but HikariPool error suggests JDBC + HikariCP is involved.
   Investigating based on error signal. KB may be incomplete.
```

---

## Investigation Layers — Run Only Layers Relevant to Detected Platforms

### LAYER 1 — CONNECTION POOL INVESTIGATION
*(Run if RDBMS + connection pool detected)*

**Signals in logs (what to look for when user pastes logs):**
- `"HikariPool-1 - Connection is not available, request timed out"`
- `"Unable to acquire JDBC Connection"`
- `"Timeout waiting for connection from pool"`
- `"Connection pool exhausted"`
- `"PoolExhaustedException"`

**Step 1 — Check current pool status via JVM metrics if available:**

Check connection pool metrics:
```
Spring Boot/HikariCP: curl localhost:8080/actuator/metrics/hikaricp.connections
Node.js: check /metrics endpoint for pg_pool_* metrics
Python: check SQLAlchemy pool.status()
```

```bash
# Spring Boot Actuator — works if actuator is enabled (run from pod or jump host)
kubectl exec -it <pod> -n <namespace> -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.active
kubectl exec -it <pod> -n <namespace> -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.pending
```

**Step 2 — Check pool config in KB:**
```
hivemind_query_memory(client=<client>, query="<service> hikari maximum-pool-size connection-timeout")
hivemind_query_memory(client=<client>, query="<service> spring.datasource.hikari")
```

Look for: `spring.datasource.hikari.maximum-pool-size`
Default is 10 — if service has high concurrency, this is too low.

**Step 3 — Check for connection leaks:**

If connections active = max but requests timing out = leak.
```bash
# Check if active connections are stuck at maximum
kubectl exec -it <pod> -n <namespace> -- curl -s localhost:8080/actuator/metrics/hikaricp.connections.active
# If active = maximum-pool-size → likely connection leak
```

Look for:
- HikariCP `leak-detection-threshold` not configured (connections never release)
- `@Transactional` on long-running methods holding connections open

**Step 4 — Check DB server connection limit:**

```bash
# Run from DB pod or jump host with psql access:
psql -h <host> -U <user> -d <database> -c "SELECT count(*) FROM pg_stat_activity;"
psql -h <host> -U <user> -d <database> -c "SHOW max_connections;"

# MySQL alternative:
mysql -h <host> -u <user> -p -e "SHOW STATUS LIKE 'Threads_connected';"
mysql -h <host> -u <user> -p -e "SHOW VARIABLES LIKE 'max_connections';"

# MongoDB alternative:
mongosh --host <host> --eval "db.serverStatus().connections"
```

If `pg_stat_activity` count near `max_connections` = server connection limit hit.

**Step 5 — Check if multiple pods competing for connections:**
```bash
kubectl get pods -n <namespace> -l app=<service> | wc -l
```

Total connections = pods × maximum-pool-size.
If 10 pods × 10 pool size = 100 connections → near PostgreSQL default limit (100).

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> datasource hikari pool")
hivemind_impact_analysis(client=<client>, entity="<service>")
  → Find all services sharing the same DB
```

---

### LAYER 2 — SLOW QUERY / TIMEOUT INVESTIGATION
*(Run if RDBMS detected)*

**Signals in logs:**
- `"Query timed out after Xms"`
- `"statement timeout"`
- `"canceling statement due to statement timeout"`
- `"SQLTimeoutException"`
- Spring slow query log warnings

**Step 1 — Check DB config for timeout settings:**
```
hivemind_query_memory(client=<client>, query="<service> statement-timeout query-timeout")
hivemind_query_memory(client=<client>, query="<service> spring.jpa spring.datasource")
```

**Step 2 — Get slow query info from the database:**

```bash
# PostgreSQL — run from DB pod or jump host (requires pg_stat_statements extension):
psql -h <host> -U <user> -d <database> -c "SELECT query, mean_exec_time, calls, total_exec_time
         FROM pg_stat_statements
         ORDER BY mean_exec_time DESC LIMIT 10;"

# MySQL alternative — run from DB pod or jump host:
mysql -h <host> -u <user> -p -e "SELECT * FROM sys.statements_with_runtimes_in_95th_percentile LIMIT 10;"

# MongoDB alternative:
mongosh --host <host> --eval "db.currentOp({'active': true, 'secs_running': {'\$gt': 5}})"
```

**Step 3 — Check for missing indexes:**

```bash
# PostgreSQL — run from DB pod or jump host:
psql -h <host> -U <user> -d <database> -c "SELECT schemaname, tablename, attname, n_distinct, correlation
         FROM pg_stats WHERE tablename = '<table>';"

# PostgreSQL — sequential scan heavy tables:
psql -h <host> -U <user> -d <database> -c "SELECT relname, seq_scan, idx_scan
         FROM pg_stat_user_tables
         WHERE seq_scan > idx_scan ORDER BY seq_scan DESC LIMIT 10;"
```

**Step 4 — Check if load spike caused slowdown:**

Sherlock: query throughput + response time correlation.
Was there a deployment that changed query patterns?

**Step 5 — Check connection pool wait time vs query time:**

If pool wait > query time → pool exhaustion (DB-1), not slow query.
If query time >> normal → slow query is root cause (DB-2).

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> JPA repository query")
```
Look for: N+1 query patterns, missing fetch strategies.

---

### LAYER 3 — MIGRATION FAILURE INVESTIGATION
*(Run if Flyway/Liquibase/Alembic detected OR service fails on startup)*

**Signals in logs:**
- `"FlywayException: Validate failed"`
- `"Migration checksum mismatch"`
- `"Found non-empty schema(s) with no schema history table"`
- `"LiquibaseException"`
- `"Migration V{n} failed"`
- Service starts then immediately crashes (DB migration runs at startup)

**Step 1 — Check migration config in KB:**
```
hivemind_query_memory(client=<client>, query="<service> flyway liquibase migration")
hivemind_query_memory(client=<client>, query="<service> spring.flyway spring.liquibase")
```
Look for: `baseline-on-migrate`, `validate-on-migrate` settings.

**Step 2 — Check migration files in KB:**
```
hivemind_search_files(client=<client>, pattern="V*.sql", repo="<service-repo>")
hivemind_search_files(client=<client>, pattern="*.changelog*", repo="<service-repo>")
```
Look for: recently added migrations that might conflict.

**Step 3 — Check migration history in DB:**

```bash
# Flyway — run from DB pod or jump host:
psql -h <host> -U <user> -d <database> -c "SELECT version, description, success, installed_on
         FROM flyway_schema_history ORDER BY installed_rank DESC LIMIT 10;"

# Liquibase — run from DB pod or jump host:
psql -h <host> -U <user> -d <database> -c "SELECT id, author, filename, dateexecuted, exectype
         FROM databasechangelog ORDER BY dateexecuted DESC LIMIT 10;"

# Alembic (Python) — run from DB pod or jump host:
psql -h <host> -U <user> -d <database> -c "SELECT version_num FROM alembic_version;"
```

Look for: `success = false` → which migration failed.

**Step 4 — Common causes:**
- Migration added in code but DB already has the change (checksum mismatch)
- Two developers added same version number
- Migration applied out of order in different environments
- Non-transactional DDL statement failed mid-migration

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> migration schema")
hivemind_diff_branches(client=<client>, branch_a="<branch>", branch_b="main")
  → Compare migration files across branches
```

---

### LAYER 4 — DEADLOCK INVESTIGATION
*(Run if RDBMS detected + deadlock signals)*

**Signals in logs:**
- `"deadlock detected"`
- `"could not serialize access due to concurrent update"`
- `"LockAcquisitionException"`
- `"TransactionSystemException"`

**Step 1 — Get deadlock details from the database:**

```bash
# PostgreSQL — run from DB pod or jump host:
psql -h <host> -U <user> -d <database> -c "SELECT pid, wait_event_type, wait_event, state, query
         FROM pg_stat_activity WHERE wait_event_type = 'Lock';"

# PostgreSQL — check blocking queries:
psql -h <host> -U <user> -d <database> -c "SELECT blocked_locks.pid AS blocked_pid,
         blocking_locks.pid AS blocking_pid,
         blocked_activity.query AS blocked_query,
         blocking_activity.query AS blocking_query
         FROM pg_catalog.pg_locks blocked_locks
         JOIN pg_catalog.pg_stat_activity blocked_activity ON blocked_activity.pid = blocked_locks.pid
         JOIN pg_catalog.pg_locks blocking_locks ON blocking_locks.locktype = blocked_locks.locktype
         JOIN pg_catalog.pg_stat_activity blocking_activity ON blocking_activity.pid = blocking_locks.pid
         WHERE NOT blocked_locks.granted;"

# MySQL alternative — run from DB pod or jump host:
mysql -h <host> -u <user> -p -e "SHOW ENGINE INNODB STATUS\G" | grep -A 20 "LATEST DETECTED DEADLOCK"
```

**Step 2 — Check transaction patterns in KB:**
```
hivemind_query_memory(client=<client>, query="<service> @Transactional transaction isolation")
```
Look for: nested transactions, multiple table updates in same transaction.

**Step 3 — Check if deadlock is between same service pods or different services:**
```
hivemind_impact_analysis(client=<client>, entity="<service>")
```
Multiple services writing same table = deadlock risk.

**Sherlock correlation:**
Query for transaction rollback rate increase.
Correlate with deployment that changed transaction logic.

---

### LAYER 5 — AZURE SERVICE BUS INVESTIGATION
*(Run if Service Bus detected in KB)*

#### DB-7: Dead Letter Queue

**Signals:** DLQ depth increasing, messages not processing, alerts firing.

**Step 1 — Check Service Bus config in KB:**
```
hivemind_query_memory(client=<client>, query="<service> servicebus topic subscription")
hivemind_query_memory(client=<client>, query="<service> dead-letter maxDeliveryCount")
```
Look for: `maxDeliveryCount` setting (default 10 — after 10 failures → DLQ).

**Step 2 — Get DLQ depth (run from jump host with az cli):**
```bash
# Azure Service Bus:
az servicebus topic subscription show \
   --resource-group <rg> \
   --namespace-name <namespace> \
   --topic-name <topic> \
   --name <subscription> \
   --query deadLetterMessageCount

# AWS SQS alternative:
aws sqs get-queue-attributes \
   --queue-url <queue-url> \
   --attribute-names ApproximateNumberOfMessagesNotVisible

# Kafka alternative:
kafka-consumer-groups.sh --bootstrap-server <broker>:9092 \
   --describe --group <consumer-group>

# RabbitMQ alternative:
rabbitmqctl list_queues name messages_unacknowledged messages_ready
```

**Step 3 — Inspect DLQ messages (run from jump host with az cli):**
```bash
az servicebus message peek \
   --resource-group <rg> \
   --namespace-name <namespace> \
   --topic-name <topic> \
   --subscription-name <sub>/\$DeadLetterQueue
```

**Step 4 — Check DeadLetterReason in message properties:**

Common reasons:
- `MaxDeliveryCountExceeded` — message failed processing N times
- `MessageLockLost` — processing took longer than lock duration
- `TTLExpiredException` — message TTL expired before processing
- `SessionLockLost` — session-based processing lock expired

#### DB-8: Processing Failures

**Signals:** errors in consumer service, message retry loops, DLQ growing.

**Step 1 — Check consumer error logs:**
```bash
kubectl logs <consumer-pod> -n <namespace> --tail=200 | grep -i "servicebus\|message\|error\|exception"
```

**Step 2 — Check message lock timeout:**
```
hivemind_query_memory(client=<client>, query="<service> lockDuration maxLockRenewalDuration")
```
If processing takes longer than `lockDuration` → `MessageLockLost` → DLQ.

**Step 3 — Check for poison messages:**

Single message causing all consumers to fail → DLQ accumulating.
Check: is DLQ depth growing by 1 per processing attempt?

**Step 4 — Check Service Bus connection and auth:**
```
hivemind_get_secret_flow(client=<client>, secret="<servicebus-connection-string-secret>")
```
Verify managed identity has correct role on Service Bus namespace.

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> ServiceBusListener @ServiceBusListener")
hivemind_query_memory(client=<client>, query="<service> topic subscription queue")
```

**Generic messaging alternatives:**

| Platform | DLQ Check Command | Consumer Lag Command |
|----------|-------------------|---------------------|
| Service Bus (Azure) | `az servicebus topic subscription show --query deadLetterMessageCount` | `az servicebus topic subscription show --query messageCount` |
| SQS (AWS) | `aws sqs get-queue-attributes --attribute-names ApproximateNumberOfMessagesNotVisible` | `aws sqs get-queue-attributes --attribute-names ApproximateNumberOfMessages` |
| Kafka | N/A (use retention-based replay) | `kafka-consumer-groups.sh --describe --group <group>` |
| RabbitMQ | `rabbitmqctl list_queues name messages_unacknowledged` | `rabbitmqctl list_queues name messages_ready` |

---

### LAYER 6 — REPLICATION / AVAILABILITY INVESTIGATION
*(Run if RDBMS detected + replication signals)*

**Signals:**
- `"could not connect to the primary server"`
- Replica returning stale data
- Read replica queries failing
- Azure Database for PostgreSQL failover alert

**Step 1 — Check replication config in KB:**
```
hivemind_query_memory(client=<client>, query="<service> read-replica secondary replica datasource")
```
Look for: separate datasource config for reads vs writes.

**Step 2 — Check replication lag:**

```bash
# PostgreSQL — on primary (run from DB pod or jump host):
psql -h <host> -U <user> -d <database> -c "SELECT application_name, write_lag, flush_lag,
         replay_lag FROM pg_stat_replication;"

# PostgreSQL — on replica (run from DB pod or jump host):
psql -h <replica-host> -U <user> -d <database> -c "SELECT now() - pg_last_xact_replay_timestamp()
         AS replication_delay;"

# MySQL alternative — on replica:
mysql -h <replica-host> -u <user> -p -e "SHOW SLAVE STATUS\G" | grep "Seconds_Behind_Master"

# MongoDB alternative:
mongosh --host <host> --eval "rs.printSecondaryReplicationInfo()"
```

**Step 3 — Check if app is routing reads to replica correctly:**
```
hivemind_query_memory(client=<client>, query="<service> @Transactional readOnly routing datasource")
```
If `readOnly=true` transactions go to replica → replica lag = stale reads.

**Step 4 — Check Azure Database for PostgreSQL status (run from jump host with az cli):**
```bash
az postgres flexible-server show --name <server> --resource-group <rg> --query "{state:state, haState:highAvailability.state}"
```
Look for: `state` (Ready/Updating/Failing), `highAvailability.state`.

---

## Sherlock Correlation

### Path A — Sherlock Available

```
mcp_sherlock_search_logs(service_name="<service>", keyword="hikari|connection|jdbc|timeout|deadlock|servicebus|sql|pool")
mcp_sherlock_get_service_incidents(service_name="<service>")
mcp_sherlock_get_service_golden_signals(service_name="<service>")
mcp_sherlock_get_deployments(app_name="<service>")
```

Look for:
- `HikariPool`, `SQLException`, `DataAccessException` errors in logs
- Response time increase correlating with DB connection errors
- Throughput drop (connection pool exhausted = requests backing up)
- Service Bus DLQ depth metric if available
- Deployment timing — did DB issues start with a deployment?

### Path B — Sherlock Unavailable

```bash
# DB/connection errors in previous container logs
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "hikari\|connection\|jdbc\|timeout\|deadlock\|servicebus\|pool"

# Current container DB errors
kubectl logs <pod-name> -n <namespace> --tail=200 | grep -iE "(HikariPool|SQLException|DataAccessException|ServiceBus|connection refused|pool exhausted)"

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Blast Radius Check — NEVER SKIP

DB failures cascade — all services sharing a database or message topic are affected simultaneously.

**After identifying ANY DB or messaging issue:**

```
# 1. Impact analysis on affected service
hivemind_impact_analysis(client=<client>, entity="<service>")

# 2. Find all services sharing the same datasource URL
hivemind_query_memory(client=<client>, query="<datasource-url> datasource jdbc spring.datasource")

# 3. Find all services consuming the same Service Bus topic
hivemind_query_memory(client=<client>, query="<topic-name> servicebus topic subscription consumer")
```

**Report format:**
```
### Blast Radius
| Affected Service | Same DB? | Same Topic? | Connection Pool Config | Risk |
|-----------------|----------|------------|----------------------|------|
| <service-1> | Yes | Yes | 10 pool / 3 pods = 30 conns | 🔴 |
| <service-2> | Yes | No | 10 pool / 2 pods = 20 conns | 🔴 |
| <service-3> | No | Yes | — | 🟡 |
| <service-4> | No | No | — | 🟢 |

Total services sharing DB: <N> (total connections: <N>)
Total services sharing topic: <N>
DB max_connections: <N>
Utilization: <total connections> / <max_connections> = <N>%
```

---

## Failure Mode Playbooks

### DB-1: CONNECTION POOL EXHAUSTED

**How to confirm:** Logs show `"Connection is not available, request timed out"`, `PoolExhaustedException`, or `"Unable to acquire JDBC Connection"`. HikariCP active connections = maximum-pool-size with pending requests > 0.

**Investigation layers to run:** Layer 1 (Connection Pool)

**Most likely root cause:** Pool size too small for request volume, or connection leak (connections acquired but never returned to pool). Scaling pods makes this WORSE — more pods × same pool size = more total connections hitting DB limit.

**File to fix:** Connection pool config in application properties or Helm values.
Typical path: `charts/<service>/values.yaml` → `spring.datasource.hikari.maximum-pool-size` or `src/main/resources/application.yaml` [repo: service repo, branch: environment branch]

**Remediation:**
- **Immediate:** Reduce pod count if total connections exceed DB `max_connections`. Check for and kill leaked connections: `SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE state = 'idle' AND query_start < now() - interval '1 hour';` (run from DB pod or jump host — use with caution)
- **Permanent:** Set `leak-detection-threshold` in HikariCP config. Right-size pool: `pool size = (2 × CPU cores) + disk spindles` (HikariCP recommendation). Increase DB `max_connections` if needed.

**Common gotcha:** Increasing pod replicas makes pool exhaustion WORSE — more pods × same pool size = more total connections to DB. If 10 pods × 10 pool = 100 connections and DB `max_connections` = 100, adding 1 more pod breaks everything.

---

### DB-2: SLOW QUERY / TIMEOUT

**How to confirm:** Logs show `SQLTimeoutException`, `"canceling statement due to statement timeout"`, or `"Query timed out after Xms"`. Response times elevated. `pg_stat_statements` shows high `mean_exec_time`.

**Investigation layers to run:** Layer 2 (Slow Query), Layer 1 (check if pool wait, not query)

**Most likely root cause:** Missing database index, N+1 query pattern in JPA/ORM, or table scan on large table. May also be caused by lock contention (check Layer 4).

**File to fix:** JPA repository or query definition, or add database index migration.
Typical path: `src/main/java/.../repository/<Entity>Repository.java` or `src/main/resources/db/migration/V<N>__add_index.sql` [repo: service repo]

**Remediation:**
- **Immediate:** Identify and terminate long-running queries: `SELECT pid, now() - query_start AS duration, query FROM pg_stat_activity WHERE state = 'active' ORDER BY duration DESC;` (run from DB pod or jump host)
- **Permanent:** Add missing indexes. Fix N+1 queries with `@EntityGraph` or `JOIN FETCH`. Set `spring.jpa.properties.hibernate.jdbc.batch_size`.

**Common gotcha:** Spring Boot default statement timeout may not be set — a query can run forever without timing out, holding a connection from the pool indefinitely. Always set `spring.datasource.hikari.connectionTimeout` AND `spring.jpa.properties.jakarta.persistence.query.timeout`.

---

### DB-3: MIGRATION FAILED

**How to confirm:** Service fails on startup with `FlywayException`, `"Migration checksum mismatch"`, or `"Validate failed"`. Pod shows `CrashLoopBackOff` with migration error in previous logs.

**Investigation layers to run:** Layer 3 (Migration)

**Most likely root cause:** Migration file modified after being applied (checksum mismatch), duplicate version number, or migration applied out of order across environments.

**File to fix:** Migration file in service repo.
Typical path: `src/main/resources/db/migration/V<version>__<description>.sql` (Flyway) or `src/main/resources/db/changelog/changelog.xml` (Liquibase) [repo: service repo]

**Remediation:**
- **Immediate:** If checksum mismatch on already-applied migration, repair: `flyway repair` or manually update `flyway_schema_history` checksum (run from DB pod or jump host with caution)
- **Permanent:** Never modify applied migrations — always create new migration files. Use Flyway `ignoreMigrationPatterns` for emergency bypasses.

**Common gotcha:** Flyway `validate-on-migrate=true` (default) will prevent startup if migration files are modified after being applied. Two developers adding same version number causes conflicts only in environments that run both branches.

---

### DB-4: DEADLOCK

**How to confirm:** Logs show `"deadlock detected"`, `LockAcquisitionException`, or `"could not serialize access due to concurrent update"`. Transaction rollback rate increasing.

**Investigation layers to run:** Layer 4 (Deadlock), Layer 1 (check pool impact)

**Most likely root cause:** Two services or pod instances updating the same rows in different order, or long-running `@Transactional` methods holding locks across multiple tables.

**File to fix:** Transaction scope in service code.
Typical path: `src/main/java/.../service/<Service>Service.java` → `@Transactional` method [repo: service repo]

**Remediation:**
- **Immediate:** Identify and terminate blocking queries (see Layer 4 commands).
- **Permanent:** Ensure consistent lock ordering across services. Reduce transaction scope. Use `SELECT ... FOR UPDATE SKIP LOCKED` for queue-like patterns.

**Common gotcha:** `@Transactional` on REST controller methods causes long transactions holding locks for the entire HTTP request duration — move transaction boundary to service layer with minimal scope.

---

### DB-5: REPLICATION LAG

**How to confirm:** Replica shows `replay_lag` > 0 in `pg_stat_replication`. Application serving stale data from read replica. Users report "I just updated X but it still shows old value."

**Investigation layers to run:** Layer 6 (Replication)

**Most likely root cause:** Heavy write workload on primary, replica resource constraints, or network latency between primary and replica.

**File to fix:** Read/write routing config in application properties.
Typical path: `src/main/resources/application.yaml` → read-replica datasource or `@Transactional(readOnly=true)` routing [repo: service repo]

**Remediation:**
- **Immediate:** Route critical reads to primary temporarily by adjusting datasource config.
- **Permanent:** Add replication lag monitoring. Implement read-after-write consistency for critical paths. Consider increasing replica resources.

**Common gotcha:** Azure PostgreSQL Flexible Server — replica lag alert threshold may be too tight (< 1 second), causing false pages during normal write bursts. Set realistic thresholds based on workload.

---

### DB-6: PRIMARY FAILOVER

**How to confirm:** Application logs show `"Connection refused"` or `"The connection attempt failed"` to primary DB. Azure portal shows failover event. App may recover automatically or may need restart.

**Investigation layers to run:** Layer 6 (Replication/Availability), Layer 1 (connection pool after failover)

**Most likely root cause:** Azure-initiated failover (maintenance, zone outage), or primary instance unhealthy. Connection pool may cache stale connection to old primary.

**File to fix:** Connection retry config and pool validation.
Typical path: `charts/<service>/values.yaml` → `spring.datasource.hikari.connectionTestQuery` or `spring.datasource.hikari.validationTimeout` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Restart pods to force new connections: `kubectl rollout restart deployment/<service> -n <namespace>` (with user approval)
- **Permanent:** Configure connection validation: `spring.datasource.hikari.connectionTestQuery=SELECT 1`. Enable retry on connection failure. Use Azure DNS endpoint (not IP) for automatic failover resolution.

**Common gotcha:** Spring Boot app with no retry on connection failure will crash on primary failover even if failover takes only 30 seconds. HikariCP caches connections — stale connections to old primary cause errors until pool recycles them.

---

### DB-7: SERVICE BUS DLQ

**How to confirm:** DLQ message count increasing in Azure Portal or via `az servicebus` command. Messages not being processed. Alert firing for DLQ depth.

**Investigation layers to run:** Layer 5 (Service Bus — DB-7 section)

**Most likely root cause:** Consumer failing to process messages after max delivery attempts. Common causes: deserialization error (message format changed), downstream dependency unavailable, or processing timeout exceeding lock duration.

**File to fix:** Consumer error handling or Service Bus config.
Typical path: `src/main/java/.../listener/<Topic>Listener.java` or `charts/<service>/values.yaml` → `maxDeliveryCount`, `lockDuration` [repo: service repo]

**Remediation:**
- **Immediate:** Inspect DLQ messages for DeadLetterReason. Fix consumer bug if identified. Replay DLQ messages via Azure Portal or custom replay logic.
- **Permanent:** Add proper error handling in consumer. Set up DLQ monitoring alerts. Implement dead letter processor service.

**Common gotcha:** DLQ messages cannot be automatically retried — they require explicit replay logic or manual Azure Portal action. Unlike a regular queue, DLQ messages stay forever until explicitly consumed or purged.

---

### DB-8: SERVICE BUS PROCESSING FAILURE

**How to confirm:** Consumer service logging errors on message processing. Messages being retried repeatedly. DLQ growing by 1 per processing cycle = poison message.

**Investigation layers to run:** Layer 5 (Service Bus — DB-8 section)

**Most likely root cause:** Processing time exceeds message lock duration → `MessageLockLost` → message returns to queue → retried → eventually DLQ. Or: single poison message causing all processing attempts to fail.

**File to fix:** Lock duration config or consumer processing code.
Typical path: `charts/<service>/values.yaml` → `lockDuration` or `src/main/java/.../listener/<Topic>Listener.java` [repo: service repo]

**Remediation:**
- **Immediate:** Identify and isolate poison messages (check DLQ for repeated message IDs). Scale down consumers to 1 to reduce lock contention.
- **Permanent:** Increase `lockDuration` to exceed worst-case processing time. Add `maxLockRenewalDuration` for long-running processing. Implement circuit breaker for downstream failures.

**Common gotcha:** Message lock duration < processing time = infinite retry loop filling DLQ — fix is to increase `lockDuration`, not add more retries. Adding retries on `MessageLockLost` makes it worse because the message is already back in the queue.

---

## Spring Boot / JVM Specific Gotchas

> **Note:** This section applies to Spring Boot / JVM platform services.
> For non-JVM platforms, equivalent patterns exist — search KB for connection pool
> config in your stack (Node.js pg-pool, Python SQLAlchemy, etc.).

| Gotcha | What Happens | How to Detect | Fix |
|--------|-------------|--------------|-----|
| **N+1 Query Problem** | `@OneToMany` without fetch strategy = N separate queries | Enable `spring.jpa.show-sql=true` in dev, check `pg_stat_statements` call count | Use `@EntityGraph` or `JOIN FETCH` in repository query |
| **LazyInitializationException** | Accessing lazy collection outside `@Transactional` scope | `LazyInitializationException` in logs | Use `@EntityGraph` to eagerly fetch needed associations, or ensure access within transaction |
| **Open Session in View** | `spring.jpa.open-in-view=true` (default!) keeps DB connection for entire HTTP request | Connection pool holds connections longer than needed, pool exhaustion under load | Set `spring.jpa.open-in-view=false` — access all lazy collections in service layer |
| **@Transactional on private methods** | Spring AOP proxy doesn't intercept private methods → no transaction | Silent data inconsistency, no rollback on error | Make methods `public` or use `@Transactional` on the calling public method |
| **Multiple DataSource config** | Wrong bean qualifier → connect to wrong database | Data appears in wrong DB, cross-DB queries fail | Verify `@Qualifier` annotations match `@Bean` names in DataSource config |
| **HikariCP leak detection** | Connections acquired but never returned to pool | Set `spring.datasource.hikari.leak-detection-threshold=30000` (30s) → logs warn on leaked connections | Fix the code path not closing connections (usually missing `@Transactional` or manual connection management) |
| **Spring Boot Actuator pool metrics** | `/actuator/metrics/hikaricp.connections.active` not available | Actuator not enabled or HikariCP metrics not exposed | Add `management.endpoints.web.exposure.include=health,metrics` and `spring.datasource.hikari.register-mbeans=true` |
| **Flyway + multiple pods** | Both pods run migrations on startup → race condition | `FlywayException` on startup, migration locks, advisory lock failures | Flyway uses advisory locks but cloud DB sometimes has issues — use init container for migrations or leader election |

---

## Output Format — DB DEBUG REPORT

Every db-debug response MUST use this structure:

```
## 🗄️ DB DEBUG REPORT

### Detected Data Stores
| Platform | Detected? | Evidence | Technology |
|----------|----------|---------|------------|
| PostgreSQL | ✓/✗ | <what was found in KB> | HikariCP / c3p0 / DBCP2 |
| Azure Service Bus | ✓/✗ | <what was found in KB> | — |
| Redis | ✓/✗ | <what was found in KB> | — |
| MongoDB | ✓/✗ | <what was found in KB> | — |
| Migration Tool | ✓/✗ | <what was found in KB> | Flyway / Liquibase / Alembic |

### Failure Mode Classification
| Field | Value |
|-------|-------|
| Failure Mode | <DB-1 through DB-8: label> |
| Service | <service name> |
| Namespace | <namespace> |
| Database | <DB identifier or topic name> |
| Platform | <which data store platform(s) affected> |
| Investigation Path | <Path A (Sherlock) or Path B (command-based)> |

### Layer Findings
<findings from each investigated layer with KB citations>
📁 Sources:
  - `<file_path>` [repo: <repo>, branch: <branch>]

### Blast Radius
| Affected Service | Same DB? | Same Topic? | Pool Config | Risk |
|-----------------|----------|------------|-------------|------|
| <service> | Yes/No | Yes/No | <pool × pods> | 🔴/🟡/🟢 |

Total services sharing DB: <N> (total connections: <N>)
DB max_connections: <N>

### Observability Correlation
**Path A (Sherlock):**
| Signal | Value |
|--------|-------|
| DB errors in logs | <count / pattern> |
| Response time since incident | <value> |
| Throughput change | <value> |
| Last deployment | <timestamp> |

**OR Path B (Sherlock unavailable):**
⚠️ Sherlock unavailable — proceeding with command-based investigation
Recommended log check:
```bash
kubectl logs <pod> -n <ns> --previous --tail=300 | grep -i "hikari|connection|jdbc|timeout|deadlock|servicebus"
```

### Recommended Commands
Run these on your jump host and paste the output back:

**1. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

### Root Cause
📋 **Failure Mode:** DB-<N>: <label>
📋 **Root Cause:** <specific statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - KB: `<file>` [repo: <repo>, branch: <branch>] — <what it shows>
  - Command output: <what user-pasted output confirmed>

### Fix
**🔥 Immediate Mitigation:**
<command or action to restore connectivity now>

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
| KB | hivemind_get_secret_flow | <secret> | — | — |
| Live | <sherlock tool> | <tool(params)> | — | — |
| Cmd | User | <kubectl/psql command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```
