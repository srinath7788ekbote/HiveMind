# HiveMind Manual Benchmark — DFIN Client
Date: 
Tester: Srinath
HiveMind version: main (22 tools, 782 tests)
Scoring: 3=correct+citation+path | 2=correct+citation | 1=correct only | 0=wrong/missing

---

## CATEGORY A — HTI Structural Queries (target: 88-95%)
These MUST use hti_get_skeleton + hti_fetch_nodes

### A1. Pipeline stage steps
Q: "What are all the steps in the Deploy stage of cd_deploy_env pipeline?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Expected file: newad/cd/cd_deploy_env/pipeline.yaml
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes: Used hti_get_skeleton + hti_fetch_nodes correctly. Returned all 49 stages
       across 7 stage groups with exact service names and correct file citation.
       Confidence: HIGH

### A2. Approval gates
Q: "Show all approval gates across all Harness pipelines"
Tool expected: hti_get_skeleton (multiple files)
Score: [ ] 0 [ ] 1 [ ] 2 [3] 3
Notes: ✅ Found 25 pipeline files via search
✅ Got skeletons for 7 CD pipelines via hti_get_skeleton
✅ Identified approval node paths in each skeleton
✅ Fetched full approval content from 6 pipelines
✅ Found the ONE pipeline WITHOUT an approval gate (frontend_rollout)
✅ Cross-pipeline comparison table showing deviations
✅ All 7 files cited with repo + branch
✅ Confidence: HIGH

### A3. Pipeline variables
Q: "What pipeline variables are defined in cd_deploy_env?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Expected: root.pipeline.variables path
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes: ✅ Called hti_get_skeleton directly (no unnecessary query_memory first)
✅ Identified root.pipeline.variables immediately from skeleton
✅ Fetched all 12 variables with full content
✅ Correctly identified the auto-calculated parser_* variables
✅ Noted the only required variable (db_host)
✅ Noted the only secret variable (maven_token)
✅ Correct file citation with repo + branch
✅ Confidence: HIGH

### A4. Helm resource limits
Q: "What are the CPU and memory limits for presentation-service in Helm?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Expected file: charts/presentation-service/values.yaml or templates/
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Used hti_get_skeleton + read_file on correct repo (newAd_Artifacts)
✅ Searched across multiple values files (dev, qa, predemo)
✅ Correct answer: NO CPU/memory limits on main app container
✅ Found the deployment template showing the missing .Values reference
✅ Found init container resources that ARE defined
✅ Identified the BestEffort QoS class risk
✅ All files cited with repo + branch
✅ Confidence: HIGH

### A5. Terraform variables
Q: "What Terraform variables are defined in Eastwood-terraform main?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Expected: variable blocks in .tf files
Score: [ ] 0 [ ] 1 [x] 2 [ ] 3
Notes:✅ Found Eastwood-terraform repo correctly
✅ Used hti_get_skeleton for Terraform files
✅ Found 25 variables.tf files in KB, 85 on disk
✅ Correct layer structure (layer_0 through layer_7 + modules)
✅ All files cited with repo + branch
✅ Confidence: HIGH

⚠️ One issue: HTI fetch_nodes had a path format problem for HCL
   → Fell back to disk read (read_file + terminal commands)
   → This means HTI structural navigation for Terraform isn't fully working
   → BM25/disk read saved it — answer is still correct
   → Score 2 not 3: right answer + right file, but HTI path resolution failed

### A6. Rollback config
Q: "What is the rollback strategy for presentation-service deployment?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Score: [ ] 0 [ ] 1 [ ] 2 [3] 3
Notes:✅ Cross-repo investigation (newAd_Artifacts + dfin-harness-pipelines)
✅ Found the rollout_0.0.3.yaml template (the actual rollback logic)
✅ Discovered critical finding: auto-rollback ONLY for dev/qa, NOT prod
✅ Found the migration-aware rollback gate (blocks rollback if new DB migration applied)
✅ Identified 3-layer rollback strategy
✅ 5 files cited across 2 repos
✅ Confidence: HIGH

### A7. Stage dependencies
Q: "What stages run in parallel in the cd_deploy_env versioning stage?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found versioning stage at correct path root.pipeline.stages[0].parallel[2]
✅ Identified both levels of parallelism (outer 3-stage parallel + inner 4-step parallel)
✅ Named all 4 inner steps with their output variables
✅ Correct file citation

### A8. Helm probe config
Q: "What are the liveness probe settings for tagging-service?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found probe hardcoded in template (not in values.yaml)
✅ Returned exact probe values (failureThreshold:3, periodSeconds:10, etc.)
✅ Identified mTLS-secured exec probe (important platform detail)
✅ Identified 30-second kill timeline
✅ Correct file citations for both values.yaml and deployments.yaml

### A9. Terraform outputs
Q: "What outputs are defined in Eastwood-terraform?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Score: [ ] 0 [ ] 1 [x] 2 [ ] 3
Notes:✅ Found all 40 outputs.tf files (same disk fallback as A5)
✅ 125 distinct outputs catalogued with full detail
✅ All files cited
⚠️ HTI pagination limit: only 5/40 skeletons returned, disk read for rest
   Same HCL pagination issue as A5 — fixable

### A10. Pipeline connectors
Q: "What connectors does Orchestrator pipeline use?"
Tool expected: hti_get_skeleton → hti_fetch_nodes
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Searched both orchestrator pipelines
✅ Correctly identified ZERO connectorRef at orchestrator level
✅ Explained why: meta-pipelines delegate to child pipelines
✅ Found the one MsTeams webhook
✅ Listed all 10 child pipelines to investigate next
✅ Confidence: HIGH with correct reasoning

CATEGORY A SCORE: __ / 30

---

## CATEGORY B — ChromaDB/BM25 Broad Search (target: 65-75%)
These use query_memory

### B1. Find by pattern
Q: "Which services have blue-green deployment configured?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Correctly found ONLY frontend-v4 uses blue-green (not other services)
✅ Found feature flag-based traffic routing mechanism
✅ Found 4 pipelines with blue-green case logic
✅ Exhaustive search confirmed zero other services
✅ Confidence: HIGH with correct negative finding

### B2. Find by config key
Q: "Which services have readinessProbe configured?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [x] 2 [ ] 3
Notes:✅ Found 28/31 services WITH probe, 3 WITHOUT
✅ Identified two probe types (exec mTLS vs httpGet)
✅ Found Sledgehammer infra services too
⚠️ rank_bm25 module missing caused query_memory failure
   → fell back to disk search (correct answer, wrong path)
   → Score 2 not 3: answer correct, KB tool failure

### B3. Find by error pattern
Q: "Which pipelines reference the acreus2npdeswdalec container registry?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [x] 2 [ ] 3
Notes:✅ Found 58 pipeline files referencing acreus2npdeswdalec
✅ Found conditional prod vs non-prod ACR routing
✅ Complete coverage across CI/CD/utility pipelines
⚠️ query_memory and search_files both failed (rank_bm25 missing)
   → disk grep saved it
   → Score 2: correct answer, KB tools failed

### B4. Cross-repo search
Q: "Find all services that reference KeyVault in their Helm charts"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Discovered the indirect chain: KV → Terraform → K8s Secret → Helm secretKeyRef
✅ Found 32 services with dedicated secrets_*.tf files
✅ Found shared secrets consumed by ALL services
✅ Verified the pattern in actual deployment template
✅ Multiple files cited across two repos

### B5. Environment config
Q: "Which services have different replica counts for QA vs production?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Discovered T-shirt sizing architecture (S/M/L)
✅ Found 15 services with different QA vs prod replica counts
✅ Found environment-to-size mapping from Harness overrides
✅ Identified 5 services with NO HPA in QA (real finding)
✅ Multiple files cited

### B6. Semantic search
Q: "Find services with JVM memory configuration"
Tool expected: query_memory (ChromaDB semantic)
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found all services with MaxRAMPercentage values
✅ Found the shared base image with NR agent (ALL services inherit)
✅ Found per-service JAVA_OPTS overrides in Sledgehammer
✅ Notable finding: message-relay at 75%, edgar is only one with K8s memory limits
✅ Cross-repo coverage (newAd_Artifacts + Sledgehammer + harness-pipelines)

### B7. Template search
Q: "Which pipelines use the sledgehammer versioning template?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 14 total consumers (6 direct + 8 indirect via ci_sledgehammer_java_service)
✅ Found 3 different active versions (0.1.1, 0.2.2, 0.2.6)
✅ Correct two-level consumer analysis
✅ All pipeline files cited with repo + branch

### B8. Infrastructure pattern
Q: "Find all Azure Service Bus configurations across repos"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found ASB across 5 repos (Eastwood, Sledgehammer-asb-management, Sledgehammer-devops, newAd_Artifacts, harness-pipelines)
✅ Correct architecture: namespace provisioning + queue definitions + service consumers
✅ Found 6 services consuming ASB via Helm
✅ Found RBAC roles assigned
✅ All files cited across multiple repos

### B9. Security config
Q: "Which services mount secrets from KeyVault via CSI driver?"
Tool expected: query_memory + get_secret_flow
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Correctly found ZERO services using CSI driver for secrets
✅ Correctly identified the actual pattern: Terraform → K8s Secret → Helm
✅ Found the commented-out Grafana example (only reference)
✅ Distinguished 3 different CSI drivers (Azure File, cert-manager, none for KeyVault secrets)
✅ High confidence negative finding with exhaustive search

### B10. Monitoring config
Q: "Which services have New Relic monitoring configured?"
Tool expected: query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 4 layers of NR monitoring (base image, Helm, Kustomize, Terraform)
✅ Found ALL Java services inherit NR agent via shared base image
✅ Found 6 Helm-charted services with explicit per-service NR config
✅ Found Global-SRE-Monitoring Terraform module
✅ Cross-repo coverage across 5 repos

CATEGORY B SCORE: __ / 30

---

## CATEGORY C — Cross-repo Dependencies (target: 70-80%)
These use impact_analysis + query_graph

### C1. Blast radius
Q: "If I change tagging-service, what other services are affected?"
Tool expected: impact_analysis
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 37 affected entities across 31 files in 3 repos
✅ Correctly identified 3 tiers (direct, shared secrets, shared CI template)
✅ Found dedicated RabbitMQ secret chain
✅ Found deployment-controller RBAC role (self-patching)
✅ Risk correctly assessed as HIGH
✅ All files cited across 3 repos

### C2. Dependency chain
Q: "What does presentation-service depend on?"
Tool expected: query_graph + get_entity
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 10 distinct dependency categories
✅ Spring Cloud Config Server, Azure Blob, Azure File, ASB, Workload Identity,
   cert-manager mTLS, New Relic, Harness FF SDK, container images, PVC
✅ Found the wait-for-termination sidecar (cert expiry watchdog — real detail)
✅ 6 Kubernetes secrets traced with their keys
✅ All files cited across 2 repos

### C3. Secret dependency
Q: "How does tagging-service get its database credentials?"
Tool expected: get_secret_flow
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found TWO separate credential chains (migration user + runtime app user)
✅ Full flow diagram: KV → Terraform → K8s Secret → Helm → Pod
✅ Different PostgreSQL usernames for migration vs runtime
✅ Found Managed Identity auth as alternative path
✅ Files cited across 2 repos in exact Terraform files

### C4. Pipeline dependency
Q: "Which Harness pipelines deploy presentation-service?"
Tool expected: get_pipeline + query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 6 pipelines total (4 direct + 2 orchestrators)
✅ Correctly found both tier 1 and tier 2 pipelines
✅ Harness serviceId presentation_service_v4 identified
✅ Cross-verified across 4 branches
✅ All files cited

### C5. Terraform dependency
Q: "What Azure resources does Eastwood-terraform create?"
Tool expected: query_memory + hti_get_skeleton
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Catalogued ~70+ Azure resources across 6 layers
✅ Correct layer-by-layer breakdown
✅ Found 12 layer/module main.tf files
✅ Found backup vaults (prod only) detail
✅ Found 32+ K8s secrets per environment
✅ All files cited

### C6. Branch comparison
Q: "What changed in Harness pipelines between release_26_2 and release_26_3?"
Tool expected: diff_branches
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Used diff_branches tool correctly
✅ 52 files changed (18 added, 34 modified, 0 deleted)
✅ Found 3 new pipelines (combined_parser, active-disclosure-ui-libs, authoring-mfe)
✅ Found new copy_acr_image template
✅ Found new cd_keyvault_harness_sync with scheduled triggers
✅ All files cited with repo + branch

### C7. Multi-service impact
Q: "Which services share the same managed identity in Eastwood-terraform?"
Tool expected: query_memory + impact_analysis
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found the ONE sharing group: content-processor identity shared by 4 other services
✅ Identified action-processor, service-operations, layout-processor, full-layout-processor
✅ Found 12 db-migration identities sharing same PostgreSQL role grant
✅ Found SP fallback pattern for services without workload identity
✅ Security risk noted: RBAC permissions silently apply to all 5 services
✅ All Terraform files cited

### C8. Entity lookup
Q: "Show me everything HiveMind knows about sifi-adapter"
Tool expected: get_entity
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ .NET 8 service identified (not Java — real platform diversity finding)
✅ 5 init containers catalogued with purpose
✅ wait-for-client-service init container = hard dependency on client-service
✅ Migration-aware deployment strategy (RollingUpdate vs Recreate)
✅ Full secret chain across 3 K8s secrets, 11+2+2 keys
✅ 4 repos covered (newAd_Artifacts, Eastwood-terraform, harness-pipelines, SRE-Management-Tools)

### C9. Connector tracing
Q: "Which services use the ACR connector in their pipelines?"
Tool expected: query_memory + query_graph
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ Found 3 distinct connector names with different purposes
✅ Template inheritance chain correctly traced
✅ Found ALL services effectively use ACR via template inheritance
✅ .NET services identified separately (CoreNonProd_Docker_Connector)
✅ Utility pipelines for ACR management found

### C10. Change impact
Q: "What would break if the newAd Helm chart values changed?"
Tool expected: impact_analysis + query_memory
Score: [ ] 0 [ ] 1 [ ] 2 [x] 3
Notes:✅ 144 entities, 84 files — largest blast radius in the benchmark
✅ Correctly categorised: 35 service charts + 15 infra charts + 8 CD pipelines + 10 CI/CD pipelines
✅ Breakage scenarios table with severity ratings
✅ Found atomic Helm rollback mechanism (--atomic flag)
✅ Cross-repo dependency to Global-SRE-Management-Tools found

CATEGORY C SCORE: __ / 30

---

## FINAL SCORES

| Category | Score | Max | Accuracy | Target |
|---|---|---|---|---|
| A: HTI Structural | __ | 30 | __%  | 88-95% |
| B: Broad Search | __ | 30 | __% | 65-75% |
| C: Cross-repo | __ | 30 | __% | 70-80% |
| **TOTAL** | __ | 90 | __% | ~75% |

## Failure Analysis
Questions that scored 0 or 1 — what went wrong:
- [ ] Wrong tool used (routing failure)
- [ ] Right tool, wrong result (KB gap)
- [ ] Right result, no citation (format failure)
- [ ] HTI not triggered (routing not working)
- [ ] KB not indexed for this data

## Notes for automation