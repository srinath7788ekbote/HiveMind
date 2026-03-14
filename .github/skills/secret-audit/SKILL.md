---
name: secret-audit
description: >
  Deep secret, identity, and config investigation for Azure KeyVault + AKS.
  Traces the full secret lifecycle from Terraform provisioning through
  KeyVault storage, managed/workload identity authentication, CSI driver
  mounting, Kubernetes Secret sync, pod env var injection, to Spring Boot
  consumption. Covers 7 failure modes with playbooks for each.
triggers:
  - secret
  - keyvault
  - key vault
  - SecretProviderClass
  - CSI
  - mount failed
  - workload identity
  - pod identity
  - managed identity
  - federated credential
  - service account
  - access denied
  - unauthorized
  - "403"
  - forbidden
  - missing env var
  - configuration not found
  - "@Value"
  - application.yaml
  - Spring Cloud Config
  - ConfigMap
  - Harness secret
  - connector secret
  - azurerm_key_vault_secret
  - access policy
  - role assignment
  - MountVolume.SetUp failed
  - SecretNotFound
  - KeyVaultReferenceNotFound
  - credential
  - identity
  - token
  - AADSTS
slash_command: /secrets
---

# Secret Audit — Azure KeyVault + AKS Operations Playbook

> This skill is the DEEP investigation layer for secret, identity, and
> configuration failures. It traces the complete secret lifecycle from
> Terraform provisioning to Spring Boot consumption. Activated after
> `incident-triage` or `k8s-debug` identifies a secret/config/identity
> problem, or directly when the user asks about secrets.
> Follow the secret chain. Check every link. Skip nothing.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| S-1 | **NEVER run commands.** User is on AVD via jump host. Recommend every `az`, `kubectl` command. Wait for paste-back. |
| S-2 | **NEVER skip `hivemind_get_secret_flow`.** It is ALWAYS the first call for any secret investigation. |
| S-3 | **NEVER skip blast radius check.** Secret failures cascade — one broken identity can take down multiple services. Always call `hivemind_impact_analysis`. |
| S-4 | **NEVER block on Sherlock.** If unavailable, fall back to `kubectl logs` and `az` commands immediately. |
| S-5 | **ALWAYS trace the full chain:** Terraform → KeyVault → Identity → CSI → K8s Secret → Pod → App. |
| S-6 | **ALWAYS search ALL indexed repos** for the active client — secrets span Helm, Terraform, and Harness repos. |
| S-7 | **ALWAYS provide exact file path + repo + branch + what to change.** User makes all changes — Copilot does NOT stage files. |
| S-8 | **ALWAYS check deployment timing.** Did a Harness deployment coincide with when secret failures started? |
| S-9 | **Commands MUST be copy-paste ready** with `<placeholder>` markers. |
| S-10 | **NEVER answer from training data** when HiveMind KB or Sherlock has results. |

---

## 🔄 SHERLOCK FALLBACK RULE

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use it — correlate auth errors, 401/403 logs, deployment timing |
| **Path B** | Sherlock unavailable or no data | Fall back to `kubectl logs` / `az` commands, continue seamlessly |

**Path A tools:**
- `mcp_sherlock_search_logs(service_name="<service>", keyword="secret|vault|auth|denied|403|unauthorized")` — auth failure logs
- `mcp_sherlock_get_service_incidents(service_name="<service>")` — active alerts
- `mcp_sherlock_get_deployments(app_name="<service>")` — deployment timing correlation
- `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — error rate spike

**Path B fallback commands:**
```bash
# Auth/secret errors in previous container logs
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "secret\|vault\|auth\|denied\|403\|forbidden\|credential\|token\|identity"

# Startup errors
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "failed\|error\|exception" | head -50

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Secret Failure Taxonomy — 7 Failure Modes

| ID | Failure Mode | One-Line Signal |
|----|-------------|-----------------|
| **FM-1** | SECRET MISSING | Secret doesn't exist in KeyVault at all |
| **FM-2** | SECRET WRONG VERSION | Secret exists but disabled version or wrong version active |
| **FM-3** | ACCESS DENIED | Identity doesn't have GET/LIST permission on KeyVault |
| **FM-4** | CSI MOUNT FAILED | SecretProviderClass misconfigured or CSI driver unhealthy |
| **FM-5** | IDENTITY BROKEN | Workload Identity binding broken — SA annotation, federated credential, or pod label missing |
| **FM-6** | SECRET NAME MISMATCH | Terraform provisions `my-secret` but app references `mySecret` or `MY_SECRET` |
| **FM-7** | CONFIG MISSING | ConfigMap, Spring Cloud Config, or application.yaml key missing |

---

## The Secret Chain — Centerpiece

Every secret investigation traces this chain link by link. A break at ANY link causes failure. For each link: what to check, what breaks, which tool reveals it.

```
┌──────────────────────────────────────────────────────────────────┐
│                    THE SECRET CHAIN                               │
│                                                                   │
│  ① TERRAFORM ──→ ② KEYVAULT ──→ ③ IDENTITY ──→ ④ CSI DRIVER    │
│                                                                   │
│  ④ CSI DRIVER ──→ ⑤ K8S SECRET ──→ ⑥ POD MOUNT ──→ ⑦ APP READ │
└──────────────────────────────────────────────────────────────────┘
```

### Link ① — Terraform Provisioning

**What this link does:** Creates the secret in Azure KeyVault via `azurerm_key_vault_secret` resource. Also creates access policies via `azurerm_key_vault_access_policy`.

**What breaks:**
- Terraform resource exists but was never applied to this environment
- Terraform resource references wrong KeyVault name for this env
- Secret name in Terraform doesn't match what downstream expects
- Access policy missing or grants wrong permissions (e.g., `list` but not `get`)

**How to check:**

KB tools (always first):
```
hivemind_get_secret_flow(client=<client>, secret="<secret-name>")
hivemind_query_memory(client=<client>, query="<service> azurerm_key_vault_secret keyvault terraform")
hivemind_search_files(client=<client>, query="key_vault_secret.tf")
```

What to look for in KB results:
- `azurerm_key_vault_secret` resource with matching `name` attribute
- `azurerm_key_vault_access_policy` granting `secret_permissions = ["get", "list"]`
- Which Terraform layer the secret is in (layer ordering matters for dependencies)
- Whether the KeyVault name is parameterized per environment (e.g., `kv-${env}-${service}`)

**Failure signal:** KB shows Terraform resource but `az keyvault secret show` returns `SecretNotFound` → Terraform not applied to this environment.

---

### Link ② — Azure KeyVault Storage

**What this link does:** Stores the secret value, manages versions, enforces access policies.

**What breaks:**
- Secret doesn't exist (never created or soft-deleted)
- Secret exists but current version is disabled
- Secret was soft-deleted — blocks re-creation with same name
- KeyVault itself is disabled or in recovery mode
- KeyVault firewall blocks access from AKS subnet

**Commands to recommend:**
```bash
# 1. List all secrets in vault (verify existence)
az keyvault secret list --vault-name <vault-name> --query "[].{name:name, enabled:attributes.enabled}" -o table

# 2. Show specific secret metadata (NOT the value)
az keyvault secret show --vault-name <vault-name> --name <secret-name> --query "{name:name, enabled:attributes.enabled, created:attributes.created, updated:attributes.updated, version:id}"

# 3. List all versions of the secret
az keyvault secret list-versions --vault-name <vault-name> --name <secret-name> --query "[].{version:id, enabled:attributes.enabled, created:attributes.created}" -o table

# 4. Check for soft-deleted secrets (if secret can't be recreated)
az keyvault secret list-deleted --vault-name <vault-name> --query "[].{name:name, deletedDate:deletedDate, scheduledPurgeDate:scheduledPurgeDate}" -o table

# 5. Check KeyVault network rules
az keyvault show --name <vault-name> --query "{networkAcls:properties.networkAcls, publicAccess:properties.publicNetworkAccess}"
```

**Output interpretation:**

| If You See | It Means | Next Step |
|------------|----------|-----------|
| Secret not in list | FM-1: SECRET MISSING | Check TF (Link ①) — was it ever provisioned? |
| `enabled: false` | FM-2: WRONG VERSION | Check version history — who disabled it and when? |
| Empty version list | FM-1: SECRET MISSING | Secret name may be wrong — check for case/format differences |
| Secret in deleted list | FM-1: MISSING (soft-delete) | Purge first: `az keyvault secret purge --vault-name <vault> --name <name>`, then re-create |
| `publicNetworkAccess: Disabled` | KeyVault behind firewall | AKS subnet must be in allowed network list or use private endpoint |

---

### Link ③ — Identity Authentication

**What this link does:** The pod's identity (managed identity or workload identity) authenticates to KeyVault to read the secret.

**What breaks:**
- Managed identity not assigned to AKS node VMSS
- Workload Identity: ServiceAccount missing `azure.workload.identity/client-id` annotation
- Workload Identity: Federated credential issuer/subject/audience mismatch
- Workload Identity: Pod missing `azure.workload.identity/use: "true"` label
- AAD Pod Identity (legacy): AzureIdentityBinding in wrong namespace
- AAD Pod Identity (legacy): NMI daemon pod down
- Identity has no role assignment or access policy on KeyVault

**Commands to recommend — Workload Identity (current):**
```bash
# 1. Check ServiceAccount annotation
kubectl get serviceaccount <sa-name> -n <namespace> -o yaml
# Must have: azure.workload.identity/client-id: <managed-identity-client-id>

# 2. Check pod label
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.labels.azure\.workload\.identity/use}'
# Must return: "true"

# 3. Check the managed identity exists
az identity show --name <identity-name> --resource-group <rg> --query "{clientId:clientId, principalId:principalId, tenantId:tenantId}"

# 4. Check federated credential
az identity federated-credential list --identity-name <identity-name> --resource-group <rg> -o table
# Verify: issuer matches AKS OIDC issuer, subject matches "system:serviceaccount:<namespace>:<sa-name>"

# 5. Get AKS OIDC issuer URL (to compare with federated credential issuer)
az aks show --resource-group <rg> --name <cluster> --query "oidcIssuerProfile.issuerUrl" -o tsv

# 6. Check role assignment on KeyVault (RBAC mode)
az role assignment list --assignee <managed-identity-client-id> --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.KeyVault/vaults/<vault-name> -o table

# 7. Check access policy (access policy mode)
az keyvault show --name <vault-name> --query "properties.accessPolicies[?objectId=='<managed-identity-principal-id>'].{permissions:permissions.secrets}" -o table
```

**Commands to recommend — AAD Pod Identity (legacy):**
```bash
# 1. Check AzureIdentity and AzureIdentityBinding in the SAME namespace as the pod
kubectl get azureidentity,azureidentitybinding -n <namespace> -o yaml

# 2. Check NMI daemon health
kubectl get pods -n kube-system -l app=nmi -o wide
```

**Commands to recommend — Node-level Managed Identity:**
```bash
# 1. Check kubelet identity
az aks show --resource-group <rg> --name <cluster> --query "identityProfile.kubeletidentity.{clientId:clientId, objectId:objectId}"

# 2. Check VMSS identity assignments
az vmss identity show --resource-group <MC_rg> --name <vmss-name>
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| SA has no `azure.workload.identity/client-id` annotation | Workload Identity not configured on SA | FM-5: IDENTITY BROKEN |
| Pod has no `azure.workload.identity/use` label | Pod not opted into Workload Identity | FM-5: IDENTITY BROKEN |
| Federated credential `issuer` ≠ AKS OIDC URL | Wrong cluster or old OIDC URL | FM-5: IDENTITY BROKEN |
| Federated credential `subject` ≠ `system:serviceaccount:<ns>:<sa>` | Wrong namespace or SA name | FM-5: IDENTITY BROKEN |
| `AADSTS70021` in logs | Federated credential mismatch | FM-5: IDENTITY BROKEN |
| `AADSTS700016` in logs | Application/client ID not found | FM-5: IDENTITY BROKEN |
| No role assignment/access policy on KV | Identity can't read secrets | FM-3: ACCESS DENIED |
| Access policy has `list` but not `get` | Can list but not read secret value | FM-3: ACCESS DENIED |
| NMI pod CrashLoopBackOff | ALL pod identity bindings broken cluster-wide | FM-5: IDENTITY BROKEN |
| AzureIdentityBinding in wrong namespace | Binding not matched to pod | FM-5: IDENTITY BROKEN |

---

### Link ④ — CSI Driver Mount

**What this link does:** The Secrets Store CSI driver reads the SecretProviderClass, authenticates to KeyVault, and mounts secrets as volumes on the pod (and optionally syncs to K8s Secrets).

**What breaks:**
- SecretProviderClass `keyvaultName` wrong for this environment
- SecretProviderClass `tenantId` wrong
- SecretProviderClass `objects` array: secret name doesn't match KeyVault
- SecretProviderClass `useVMManagedIdentity` when workload identity is expected (or vice versa)
- CSI driver pod not running on the node where pod is scheduled
- SecretProviderClass `secretObjects` sync config wrong (K8s secret not created)

**Commands to recommend:**
```bash
# 1. List SecretProviderClass objects
kubectl get secretproviderclass -n <namespace>

# 2. Full SecretProviderClass config
kubectl get secretproviderclass <spc-name> -n <namespace> -o yaml

# 3. Check SecretProviderClassPodStatus (shows sync result per pod)
kubectl get secretproviderclasspodstatus -n <namespace>

# 4. Check pod events for mount errors
kubectl describe pod <pod-name> -n <namespace> | grep -A5 -i "failedmount\|mount\|volume\|secret\|warning"

# 5. Check mount-related events in namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i "secret\|mount\|csi\|provider"

# 6. Check CSI driver pods on the specific node
kubectl get pods -n kube-system -l app=secrets-store-csi-driver -o wide | grep <node-name>

# 7. CSI driver logs on the node (if needed)
kubectl logs -n kube-system <csi-secrets-store-pod-on-node> --tail=100
```

**KB tools:**
```
hivemind_query_memory(client=<client>, query="<service> SecretProviderClass keyvaultName objects")
hivemind_query_memory(client=<client>, query="<service> csi volume secret mount")
```

**Output interpretation — SecretProviderClass YAML:**

| Field | What to Check | Common Misconfiguration |
|-------|--------------|------------------------|
| `spec.parameters.keyvaultName` | Must match actual KV name for THIS environment | Hardcoded KV name instead of environment-parameterized |
| `spec.parameters.tenantId` | Must match Azure AD tenant ID | Copy-paste error from different tenant |
| `spec.parameters.useVMManagedIdentity` | `"true"` for node MI, `"false"` for workload identity | Wrong auth mode selected |
| `spec.parameters.clientID` | Must match managed identity client ID | Stale identity after re-creation |
| `spec.parameters.objects` | Array of `objectName` entries | Secret name case mismatch with actual KV secret |
| `spec.secretObjects` | Defines K8s Secret sync | Missing → secrets mounted as files only, not K8s Secrets |
| `spec.secretObjects[].data[].objectName` | Must match an entry in `objects` array | Typo: objectName in secretObjects ≠ objectName in objects |
| `spec.secretObjects[].data[].key` | The key name in the synced K8s Secret | Must match what pod spec references |

**Event error interpretation:**

| Event Message Pattern | Root Cause | Fix |
|----------------------|-----------|-----|
| `failed to get objectType:secret, objectName:<name>, objectVersion:: keyvault.BaseClient#GetSecret: Failure responding to request: StatusCode=403` | FM-3: ACCESS DENIED | Fix identity permissions on KeyVault |
| `failed to get objectType:secret, objectName:<name>: SecretNotFound` | FM-1: SECRET MISSING or FM-6: NAME MISMATCH | Verify secret name in KV vs SPC |
| `failed to create provider: provider not registered` | CSI driver not installed on cluster | Install `secrets-store-csi-driver` Helm chart |
| `failed to mount secrets store objects ... context deadline exceeded` | Network issue: can't reach KeyVault | Check private endpoints, NSG, KV firewall |
| `MSI not available` | Managed identity not on VMSS | Assign identity to node pool VMSS |
| `rpc error: code = Unknown desc = failed to mount` | Generic CSI failure | Check CSI driver logs for detailed error |

---

### Link ⑤ — Kubernetes Secret Sync

**What this link does:** When `spec.secretObjects` is configured in the SecretProviderClass, the CSI driver creates a K8s Secret in the namespace, syncing values from KeyVault. This K8s Secret can then be referenced in pod env vars.

**What breaks:**
- `secretObjects` not configured in SecretProviderClass → no K8s Secret created
- `secretObjects.data[].key` doesn't match what pod env var references
- K8s Secret exists but the data keys inside it don't match pod spec references
- K8s Secret created by CSI sync vs manually-created K8s Secret conflict
- Secret type mismatch (`Opaque` vs `kubernetes.io/tls`)

**Commands to recommend:**
```bash
# 1. List secrets in namespace
kubectl get secret -n <namespace> | grep -i <service>

# 2. Describe secret (shows keys, NOT values)
kubectl describe secret <secret-name> -n <namespace>

# 3. Check secret data keys
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data}' | python -m json.tool
# (Shows base64 keys — names only, not values)

# 4. Check how pod references the secret (env vars)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].env}' | python -m json.tool

# 5. Check envFrom (bulk import from secret)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].envFrom}' | python -m json.tool

# 6. Check volume mounts (file-based secret access)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[0].volumeMounts}' | python -m json.tool
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.volumes}' | python -m json.tool
```

**Output interpretation:**

| If You See | It Means | Next Step |
|------------|----------|-----------|
| Secret not in namespace | CSI sync didn't create it, or `secretObjects` not configured | Check SPC `secretObjects` config (Link ④) |
| Secret exists but missing expected key | `secretObjects.data[].key` doesn't match | Compare SPC `secretObjects` keys with pod env refs |
| Pod env `valueFrom.secretKeyRef.key` doesn't match secret data key | FM-6: NAME MISMATCH | Align Helm values with actual K8s Secret key names |
| Pod env `valueFrom.secretKeyRef.name` points to nonexistent secret | Secret name mismatch between Helm and actual | Check Helm values for secret reference name |
| Secret has data but pod still fails | App reads secret but can't parse the value | Check secret value format (URL-encoded? JSON? plain text?) |

---

### Link ⑥ — Pod Mount / Env Injection

**What this link does:** The pod spec mounts the K8s Secret or CSI volume and exposes values as environment variables or files.

**What breaks:**
- Volume mount path wrong — app looks in different directory
- Env var name in pod spec doesn't match what app code expects
- `optional: true` on secret reference masks the missing secret (pod starts but crashes later)
- Multiple containers in pod — secret only mounted on wrong container
- Init container needs secret but only main container has it mounted

**Commands to recommend:**
```bash
# 1. Full pod spec volumes and mounts
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A30 "volumes:"
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A20 "volumeMounts:"

# 2. All env vars on the running pod (if pod is Running)
kubectl exec <pod-name> -n <namespace> -- env | sort

# 3. Check specific env var
kubectl exec <pod-name> -n <namespace> -- printenv <ENV_VAR_NAME>

# 4. If pod is CrashLooping (can't exec), check spec
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].env}' | python -m json.tool
```

**Output interpretation:**

| If You See | It Means | Next Step |
|------------|----------|-----------|
| Env var is empty / not set | Secret not synced or wrong key reference | Check Link ⑤ (K8s Secret sync) |
| Env var has value but app still fails | Value format wrong (e.g., connection string URL-encoded) | Check actual value format vs what app parser expects |
| Volume mounted but empty directory | CSI sync failed silently | Check `secretproviderclasspodstatus` (Link ④) |
| Volume mounted at `/mnt/secrets` but app reads from `/etc/secrets` | Mount path mismatch | Check Helm values `volumeMounts.mountPath` |

---

### Link ⑦ — Application Read

**What this link does:** Spring Boot reads the secret value from an environment variable (`@Value("${DB_PASSWORD}")`) or from a mounted file, or from Spring Cloud Config.

**What breaks:**
- `@Value("${ENV_NAME}")` but env var has different name (case-sensitive)
- `application.yaml` references `${SECRET_NAME}` but env var is `secret-name`
- Spring Cloud Config server unreachable at startup
- ConfigMap key name doesn't match Spring property path
- Property set in wrong Spring profile (`application-dev.yaml` not loaded)

**KB tools:**
```
hivemind_query_memory(client=<client>, query="<service> application.yaml @Value environment secret")
hivemind_query_memory(client=<client>, query="<service> spring.profiles SPRING_PROFILES_ACTIVE")
hivemind_query_memory(client=<client>, query="<service> configmap spring config")
```

**Commands to recommend (only if pod is running):**
```bash
# 1. Check Spring profiles active
kubectl exec <pod-name> -n <namespace> -- printenv SPRING_PROFILES_ACTIVE

# 2. Check specific secret env var the app expects
kubectl exec <pod-name> -n <namespace> -- printenv <ENV_VAR_NAME>

# 3. Check actuator env endpoint (if exposed)
kubectl exec <pod-name> -n <namespace> -- curl -s http://localhost:<port>/actuator/env/<property-name> 2>/dev/null | python -m json.tool

# 4. Check if configmap is mounted
kubectl get configmap <service>-config -n <namespace> -o yaml
```

**Common patterns on this platform:**

| App Reference | Env Var Name | KeyVault Secret Name | Mismatch? |
|--------------|-------------|---------------------|-----------|
| `@Value("${DB_PASSWORD}")` | `DB_PASSWORD` | `db-password` | ✅ Name format differs (env var uses `_`, KV uses `-`) |
| `spring.datasource.password` | `SPRING_DATASOURCE_PASSWORD` | `spring-datasource-password` | ✅ Spring relaxed binding may help but KV name format differs |
| `${my.custom.secret}` | `MY_CUSTOM_SECRET` | `my-custom-secret` | ⚠️ Works via Spring relaxed binding BUT only if env var is set |

**Key rule:** KeyVault secret names are **case-insensitive** and use **hyphens**. Env var names are **case-sensitive** and use **UPPER_SNAKE_CASE**. The mapping between them happens in the Helm values (`env[].name` + `secretKeyRef`). A break in this mapping = FM-6.

---

## Investigation Layers — Execute in Order

### LAYER 1 — SECRET EXISTENCE CHECK

**Always start here.** Verify the secret exists where it's expected.

**Step 1 — KB lookup (always first):**
```
hivemind_get_active_client()
hivemind_get_secret_flow(client=<client>, secret="<secret-name-or-service>")
hivemind_query_memory(client=<client>, query="<service> keyvault secret terraform azurerm_key_vault_secret")
```

What to extract from KB:
- Which KeyVault the secret should be in (per environment)
- What exact name the secret has in KeyVault
- Which Terraform layer provisions it
- Whether access policies are defined in same layer
- Chain status: is the chain complete or has gaps?

**Step 2 — Verify existence in KeyVault:**
```bash
# List secrets (verify name exists)
az keyvault secret list --vault-name <vault-name> --query "[?contains(name, '<partial-name>')].{name:name, enabled:attributes.enabled}" -o table

# Show specific secret metadata
az keyvault secret show --vault-name <vault-name> --name <secret-name> --query "{name:name, enabled:attributes.enabled, created:attributes.created, updated:attributes.updated, contentType:contentType}"

# Check versions
az keyvault secret list-versions --vault-name <vault-name> --name <secret-name> --query "[].{version:id, enabled:attributes.enabled, created:attributes.created}" -o table

# Check soft-deleted (if secret seems to have vanished)
az keyvault secret list-deleted --vault-name <vault-name> --query "[?contains(name, '<name>')].{name:name, deletedDate:deletedDate}" -o table
```

**Decision:**
- Secret exists and enabled → proceed to Layer 2
- Secret missing → FM-1. Check Terraform (Link ①). Was it applied to this env?
- Secret disabled → FM-2. Check who disabled it and when
- Secret soft-deleted → FM-1. Must purge before re-creating with same name

---

### LAYER 2 — ACCESS AND IDENTITY CHECK

**Verify the pod's identity can read the secret.**

**Step 1 — Determine auth mode:**
```bash
# Check if cluster uses workload identity
az aks show --resource-group <rg> --name <cluster> --query "oidcIssuerProfile.issuerUrl"
# Non-null = workload identity enabled

# Check if KeyVault uses RBAC or access policy mode
az keyvault show --name <vault-name> --query "properties.enableRbacAuthorization"
# true = RBAC mode, false/null = access policy mode
```

**Step 2 — Workload Identity verification:**
```bash
# Check SA has identity annotation
kubectl get serviceaccount <sa-name> -n <namespace> -o jsonpath='{.metadata.annotations.azure\.workload\.identity/client-id}'

# Check pod has workload identity label
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.labels.azure\.workload\.identity/use}'

# Check federated credential
az identity federated-credential list --identity-name <identity-name> --resource-group <rg> --query "[].{name:name, issuer:issuer, subject:subject, audience:audiences[0]}" -o table

# Get AKS OIDC issuer (must match federated credential issuer)
az aks show --resource-group <rg> --name <cluster> --query "oidcIssuerProfile.issuerUrl" -o tsv
```

**Step 3 — Permission verification (depends on KV mode):**

RBAC mode:
```bash
az role assignment list --assignee <managed-identity-client-id> --scope /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.KeyVault/vaults/<vault-name> --query "[].{role:roleDefinitionName, scope:scope}" -o table
# Need: "Key Vault Secrets User" or "Key Vault Secrets Officer"
```

Access policy mode:
```bash
az keyvault show --name <vault-name> --query "properties.accessPolicies[?objectId=='<principal-id>'].permissions.secrets" -o table
# Need: ["get", "list"] at minimum
```

**Step 4 — KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> managed identity workload identity service account")
hivemind_query_memory(client=<client>, query="<vault-name> access policy terraform role assignment")
```

**Decision:**
- SA annotation present + federated credential matches + permissions OK → proceed to Layer 3
- SA annotation missing → FM-5. Fix: add annotation to SA in Helm values
- Federated credential issuer mismatch → FM-5. Fix: update federated credential in Terraform
- No role assignment / access policy → FM-3. Fix: add in Terraform

---

### LAYER 3 — CSI DRIVER AND MOUNT CHECK

**Verify the CSI driver fetches secrets and mounts them.**

```bash
# SecretProviderClass config
kubectl get secretproviderclass -n <namespace> -o yaml

# Pod status from CSI perspective
kubectl get secretproviderclasspodstatus -n <namespace>

# Pod events (mount errors are here)
kubectl describe pod <pod-name> -n <namespace> | grep -B2 -A5 -i "mount\|volume\|secret\|warning\|error"

# Secret-related events in namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i "secret\|mount\|csi\|provider\|keyvault"

# CSI driver health
kubectl get pods -n kube-system -l app=secrets-store-csi-driver -o wide
```

**KB tools:**
```
hivemind_query_memory(client=<client>, query="<service> SecretProviderClass keyvaultName objects secretObjects")
```

**Decision:**
- SPC config correct + CSI healthy + no mount errors → proceed to Layer 4
- SPC `keyvaultName` wrong → FM-4. Fix: update Helm values for correct env
- SPC `objects` name mismatch → FM-6. Fix: align SPC with actual KV secret names
- CSI driver pod down → FM-4. Restart: `kubectl rollout restart daemonset/csi-secrets-store -n kube-system`
- 403 in mount events → FM-3. Go back to Layer 2

---

### LAYER 4 — KUBERNETES SECRET SYNC CHECK

**Verify CSI-synced K8s Secrets exist and have correct keys.**

```bash
# List K8s secrets
kubectl get secret -n <namespace> | grep -i <service>

# Check secret data keys (NOT values)
kubectl describe secret <secret-name> -n <namespace>

# How pod references secrets
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].env}' | python -m json.tool
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].envFrom}' | python -m json.tool
```

**Decision:**
- K8s Secret exists with correct keys + pod references match → proceed to Layer 5
- K8s Secret missing → FM-4. Check SPC `secretObjects` config (Layer 3)
- K8s Secret exists but key name doesn't match pod env ref → FM-6. Fix Helm values
- Pod references wrong secret name → FM-6. Fix Helm values

---

### LAYER 5 — HARNESS PIPELINE SECRET CHECK

**Verify secrets referenced in deploy pipelines.**

**KB tools (primary source — no direct Harness commands):**
```
hivemind_get_pipeline(client=<client>, name="<service>-deploy")
hivemind_query_memory(client=<client>, query="<service> harness secret variable connector")
hivemind_query_memory(client=<client>, query="<service> pipeline secret override")
```

**What to look for:**
- Pipeline variables with type `Secret` — do they reference the right Harness secret?
- Connector secrets — do they use valid credentials?
- Variable overrides — does a pipeline override replace a Helm value that references a secret?
- Secret scope — account-level vs org-level vs project-level (scope mismatch = not found)
- Harness secret identifier vs actual KeyVault/K8s secret name

**Decision:**
- Pipeline doesn't override secret-related values → proceed to Layer 6
- Pipeline overrides with wrong identifier → Fix pipeline variable in Harness
- Connector secret expired → Rotate connector credentials

---

### LAYER 6 — SPRING BOOT CONFIG CHECK

**Verify the app reads the right secret from the right source.**

**KB tools:**
```
hivemind_query_memory(client=<client>, query="<service> application.yaml spring datasource password secret")
hivemind_query_memory(client=<client>, query="<service> @Value environment variable secret")
hivemind_query_memory(client=<client>, query="<service> configmap spring cloud config")
```

**Commands (if pod is Running):**
```bash
# Check Spring profile
kubectl exec <pod-name> -n <namespace> -- printenv SPRING_PROFILES_ACTIVE

# Check if the env var the app expects is actually set
kubectl exec <pod-name> -n <namespace> -- printenv <EXPECTED_ENV_VAR>

# If pod is CrashLooping, check deployment spec instead
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="<EXPECTED_ENV_VAR>")]}'

# Check ConfigMap for Spring config
kubectl get configmap -n <namespace> | grep -i <service>
kubectl describe configmap <service>-config -n <namespace>
```

**Decision:**
- Env var set with correct value → issue is in app code, not infra
- Env var missing → FM-6 or FM-7. Trace backwards: is K8s Secret synced? Is SPC correct?
- ConfigMap missing key → FM-7. Fix Helm chart configmap template
- Wrong Spring profile → FM-7. Fix `SPRING_PROFILES_ACTIVE` in Helm values

---

## Failure Mode Playbooks

### FM-1: SECRET MISSING

**Distinguishing signal:** `az keyvault secret show` returns `SecretNotFound` or secret not in `secret list`.

**Investigation sequence:** Layer 1 → Link ① (Terraform)

**Most likely root cause:** Terraform resource exists in code but was never applied to this environment. Common during new environment provisioning or when Terraform layers run out of order.

**Check:**
```
hivemind_query_memory(client=<client>, query="<secret-name> azurerm_key_vault_secret terraform")
```

**File to fix:** The Terraform layer that provisions secrets. Typical path pattern:
`layer_5/secrets_<service>.tf` or `modules/secrets/<service>.tf` [repo: Terraform repo, branch: environment branch]

**Common gotcha:** KeyVault has soft-delete enabled by default. If someone deleted the secret, it's in soft-delete. Must `purge` before re-creating with same name:
```bash
az keyvault secret purge --vault-name <vault> --name <secret-name>
```

---

### FM-2: SECRET WRONG VERSION

**Distinguishing signal:** `az keyvault secret show` returns a secret but `enabled: false`, or app logs show unexpected value format.

**Investigation sequence:** Layer 1 (version list) → check when disabled

**Most likely root cause:** Secret rotation created a new version but left old version as active, or someone disabled the current version during maintenance.

**Commands:**
```bash
az keyvault secret list-versions --vault-name <vault> --name <secret-name> --query "[].{version:id, enabled:attributes.enabled, created:attributes.created}" -o table
```

**File to fix:** Usually operational — no file change needed. Re-enable the secret version or trigger Terraform re-apply:
```bash
az keyvault secret set-attributes --vault-name <vault> --name <secret-name> --version <version-id> --enabled true
```

**Common gotcha:** CSI driver caches secrets. After re-enabling, pods may need restart to pick up the change:
```bash
kubectl rollout restart deployment/<service> -n <namespace>
```

---

### FM-3: ACCESS DENIED

**Distinguishing signal:** Pod events contain `StatusCode=403` or `Forbidden`. Logs contain `AADSTS`, `unauthorized`, or `access denied`.

**Investigation sequence:** Layer 2 → Link ③ (Identity)

**Most likely root cause (ranked):**
1. Managed identity not assigned the right role on KeyVault (RBAC mode)
2. Access policy missing `get` permission for the identity (access policy mode)
3. KeyVault firewall blocking AKS subnet
4. Identity was deleted and re-created — new identity has different principal ID

**Check (RBAC mode):**
```
hivemind_query_memory(client=<client>, query="<vault-name> role assignment terraform keyvault")
```

**File to fix — RBAC mode:**
Terraform: `azurerm_role_assignment` resource granting `Key Vault Secrets User` role.
Typical path: `layer_5/identity_<service>.tf` or `modules/identity/<service>.tf`

**File to fix — access policy mode:**
Terraform: `azurerm_key_vault_access_policy` resource granting `["get", "list"]` on secrets.
Typical path: `layer_5/keyvault_policies.tf`

**Common gotcha:** If the managed identity was deleted and re-created, the access policy still references the OLD principal ID. Terraform `plan` may show no changes because it tracks by resource name, not principal ID. Force recreation:
```bash
terraform taint azurerm_key_vault_access_policy.<resource-name>
```

---

### FM-4: CSI MOUNT FAILED

**Distinguishing signal:** Pod stuck in `ContainerCreating`. Events show `FailedMount` with CSI-related errors.

**Investigation sequence:** Layer 3 → Link ④ (CSI Driver)

**Most likely root cause (ranked):**
1. SecretProviderClass `keyvaultName` wrong for this environment
2. CSI driver pod not running on the node where the pod is scheduled
3. SecretProviderClass `objects` array references a secret that doesn't exist or uses wrong name
4. `tenantId` wrong in SecretProviderClass
5. Network: can't reach KeyVault (private endpoint / firewall)

**Check:**
```
hivemind_query_memory(client=<client>, query="<service> SecretProviderClass helm keyvaultName")
```

**File to fix:** Helm values or Helm template for SecretProviderClass.
Typical paths:
- `charts/<service>/templates/secret-provider-class.yaml`
- `charts/<service>/values-<env>.yaml` (environment override with KV name)

**Common gotcha:** `keyvaultName` is often parameterized via Helm values per environment. If a new environment was added but the values file wasn't created, the SPC gets the default (wrong) vault name.

---

### FM-5: IDENTITY BROKEN

**Distinguishing signal:** Pod events show identity-related errors. Logs contain `AADSTS70021`, `AADSTS700016`, or `MSI not available`.

**Investigation sequence:** Layer 2 → Link ③ (Identity)

**Most likely root cause (ranked):**
1. ServiceAccount missing `azure.workload.identity/client-id` annotation
2. Pod missing `azure.workload.identity/use: "true"` label
3. Federated credential `issuer` doesn't match AKS OIDC URL (cluster changed or rebuilt)
4. Federated credential `subject` wrong namespace or SA name
5. (Legacy) AzureIdentityBinding in wrong namespace

**Check:**
```
hivemind_query_memory(client=<client>, query="<service> serviceaccount workload identity annotation")
hivemind_query_memory(client=<client>, query="<service> managed identity federated credential terraform")
```

**Files to fix:**
- SA annotation → Helm values: `serviceAccount.annotations` section
- Pod label → Helm template: `spec.template.metadata.labels` section
- Federated credential → Terraform: `azurerm_federated_identity_credential` resource

**Common gotcha:** When an AKS cluster is rebuilt, its OIDC issuer URL changes. ALL federated credentials referencing the old issuer must be updated. This is a blast radius issue — run `hivemind_impact_analysis` to find all affected services.

---

### FM-6: SECRET NAME MISMATCH

**Distinguishing signal:** Secret exists in KeyVault. Identity has access. CSI driver is healthy. But the app doesn't receive the secret value. This is a mapping/naming problem.

**Investigation sequence:** Layer 4 → Layer 6 → compare names across all links

**The mismatch chain — check each junction:**

| Junction | Left Side | Right Side | Common Mismatch |
|----------|----------|-----------|-----------------|
| KV → SPC | KV secret name: `db-password` | SPC `objectName`: `dbPassword` | Case/format difference |
| SPC → K8s Secret | SPC `objects.objectName`: `db-password` | SPC `secretObjects.data.objectName`: `db_password` | Underscore vs hyphen |
| K8s Secret → Pod env | K8s Secret key: `db-password` | Pod `secretKeyRef.key`: `DB_PASSWORD` | UPPER_SNAKE vs lower-kebab |
| Pod env → App code | Env var: `DB_PASS` | `@Value("${DB_PASSWORD}")` | Truncated name |

**How to trace the full name chain:**
```bash
# 1. KeyVault secret name
az keyvault secret list --vault-name <vault> --query "[?contains(name, '<partial>')].name" -o tsv

# 2. SPC objects array
kubectl get secretproviderclass <spc> -n <ns> -o jsonpath='{.spec.parameters.objects}'

# 3. SPC secretObjects (K8s Secret sync)
kubectl get secretproviderclass <spc> -n <ns> -o jsonpath='{.spec.secretObjects}'

# 4. K8s Secret keys
kubectl get secret <secret> -n <ns> -o jsonpath='{.data}' | python -m json.tool

# 5. Pod env var name
kubectl get deployment <svc> -n <ns> -o jsonpath='{.spec.template.spec.containers[0].env[?(@.valueFrom.secretKeyRef)]}' | python -m json.tool

# 6. App reference (from KB)
hivemind_query_memory(client=<client>, query="<service> @Value DB_PASSWORD environment")
```

**File to fix:** Usually the Helm values where env vars are mapped to K8s Secret keys. Align the name at every junction.

**Common gotcha:** KeyVault secret names are case-insensitive (`db-password` == `DB-Password`), but EVERYTHING downstream is case-sensitive. The mismatch usually happens at the SPC → K8s Secret or K8s Secret → pod env junction.

---

### FM-7: CONFIG MISSING

**Distinguishing signal:** No secret/KeyVault errors — the missing value is a non-secret configuration (ConfigMap, Spring property, profile).

**Investigation sequence:** Layer 6 → Link ⑦ (App Read)

**Most likely root cause (ranked):**
1. `SPRING_PROFILES_ACTIVE` not set or set to wrong profile
2. ConfigMap missing or missing the expected key
3. Spring Cloud Config server unreachable at startup
4. ConfigMap key name doesn't match Spring property path
5. `spring.config.import` set to unavailable source

**Check:**
```
hivemind_query_memory(client=<client>, query="<service> configmap application.yaml spring profiles")
hivemind_query_memory(client=<client>, query="<service> spring cloud config import")
```

**Commands:**
```bash
# Check ConfigMap
kubectl get configmap -n <namespace> | grep -i <service>
kubectl describe configmap <service>-config -n <namespace>

# Check Spring profile
kubectl get deployment <service> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SPRING_PROFILES_ACTIVE")].value}'

# Check if config server is running
kubectl get pods -n <namespace> -l app=<config-server>
```

**Files to fix:**
- Missing ConfigMap → Helm template: `templates/configmap.yaml`
- Wrong profile → Helm values: `env` section for `SPRING_PROFILES_ACTIVE`
- Missing config key → ConfigMap data in Helm chart or external config repo

**Common gotcha:** `spring.config.import=configserver:http://config-server:8888` with `spring.cloud.config.fail-fast: true` — if config server is unreachable, the app crashes immediately. Set `fail-fast: false` for resilience, or ensure config server is deployed before dependent services.

---

## Blast Radius Check — NEVER SKIP

After identifying the failure mode, ALWAYS check how many services are affected:

```
# 1. How many services use this secret?
hivemind_query_memory(client=<client>, query="<secret-name> secret service deployment")

# 2. How many services use this identity?
hivemind_query_memory(client=<client>, query="<identity-name> managed identity service workload")

# 3. Full dependency impact
hivemind_impact_analysis(client=<client>, entity="<service-or-identity>")
```

**Why this matters:**
- One managed identity is often shared across multiple services
- One KeyVault is often shared by all services in an environment
- One broken federated credential (e.g., wrong OIDC issuer after cluster rebuild) breaks ALL services using workload identity
- One expired access policy blocks ALL services using that identity

**Report format:**
```
### Blast Radius
| Affected Service | Same Identity? | Same KeyVault? | Same Secret? | Current State |
|-----------------|---------------|---------------|-------------|---------------|
| <service-1> | Yes | Yes | Yes | CrashLoopBackOff |
| <service-2> | Yes | Yes | No | Running (different secrets) |
| <service-3> | No | Yes | No | Running (different identity) |

Total services at risk: <N>
Shared identity: <identity-name> [<N> services]
Shared KeyVault: <vault-name> [<N> services]
```

---

## KB Cross-Reference — Summary Map

Search ALL indexed repos for the active client. Cross-reference across Helm, Terraform, Harness, and application repos together.

| What You Need | HiveMind Tool | Query Pattern |
|---------------|---------------|---------------|
| Full secret chain (**ALWAYS FIRST**) | `hivemind_get_secret_flow(secret="<name>")` | End-to-end chain |
| Service metadata | `hivemind_get_entity(name="<service>")` | All repos/branches |
| Blast radius (**ALWAYS**) | `hivemind_impact_analysis(entity="<service>")` | Dependencies |
| TF secret provisioning | `hivemind_query_memory(query="<secret> azurerm_key_vault_secret terraform")` | TF definition |
| TF access policy / role | `hivemind_query_memory(query="<vault> access_policy role_assignment terraform")` | TF permissions |
| TF identity / federated cred | `hivemind_query_memory(query="<service> managed_identity federated_identity_credential")` | TF identity |
| Helm SecretProviderClass | `hivemind_query_memory(query="<service> SecretProviderClass keyvaultName objects")` | SPC config |
| Helm secret env vars | `hivemind_query_memory(query="<service> env secretKeyRef valueFrom")` | Pod env mapping |
| Helm serviceaccount | `hivemind_query_memory(query="<service> serviceAccount annotations workload identity")` | SA config |
| Harness pipeline secrets | `hivemind_get_pipeline(name="<pipeline>")` | Pipeline variables |
| Harness connectors | `hivemind_query_memory(query="<service> harness connector secret")` | Connector auth |
| Spring Boot config | `hivemind_query_memory(query="<service> application.yaml @Value secret")` | App config |
| ConfigMap | `hivemind_query_memory(query="<service> configmap spring profiles")` | Config data |
| All services sharing secret | `hivemind_query_memory(query="<secret-name> service")` | Blast radius |
| All services sharing identity | `hivemind_query_memory(query="<identity-name> managed identity")` | Blast radius |

---

## Output Format — SECRET AUDIT REPORT

Every secret-audit response MUST use this structure:

```
## 🔐 SECRET AUDIT REPORT

### Failure Mode Classification
| Field | Value |
|-------|-------|
| Failure Mode | <FM-1 through FM-7: label> |
| Service | <service name> |
| Namespace | <namespace> |
| Secret | <secret name in KeyVault> |
| KeyVault | <vault name> |
| Identity | <managed identity name> |
| Investigation Path | <Path A (Sherlock) or Path B (command-based)> |

### Secret Chain Trace
```
① Terraform:    <✅ found / ❌ missing / ⚠️ issue>
   📁 Source: `<tf-file>` [repo: <repo>, branch: <branch>]
② KeyVault:     <✅ exists & enabled / ❌ missing / ⚠️ disabled>
③ Identity:     <✅ configured / ❌ broken — <what's wrong>>
④ CSI Driver:   <✅ mounted / ❌ failed — <error>>
⑤ K8s Secret:   <✅ synced / ❌ missing / ⚠️ wrong keys>
⑥ Pod Mount:    <✅ env var set / ❌ missing / ⚠️ wrong name>
⑦ App Read:     <✅ value consumed / ❌ mismatch / ⚠️ format error>

CHAIN BREAK AT: Link <N> — <description>
```

### Blast Radius
| Affected Service | Same Identity | Same Vault | Same Secret | Risk |
|-----------------|--------------|-----------|------------|------|
| <service> | Yes/No | Yes/No | Yes/No | 🔴/🟡/🟢 |

Total at risk: <N> services

### KB Findings
📋 Finding: <what KB revealed>
📁 Sources:
  - `<file_path>` [repo: <repo>, branch: <branch>]
  - `<file_path>` [repo: <repo>, branch: <branch>]

### Observability Correlation
**Path A (Sherlock):**
| Signal | Value |
|--------|-------|
| Auth errors in logs | <count / pattern> |
| Error rate since incident | <value> |
| Last deployment | <timestamp> |

**OR Path B (Sherlock unavailable):**
⚠️ Sherlock unavailable — proceeding with command-based investigation
Recommended log check:
```bash
kubectl logs <pod> -n <ns> --previous --tail=300 | grep -i "secret|vault|auth|denied|403"
```

### Recommended Commands
Run these on your jump host and paste the output back:

**1. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

### Root Cause
📋 **Failure Mode:** FM-<N>: <label>
📋 **Root Cause:** <specific statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - KB: `<file>` [repo: <repo>, branch: <branch>] — <what it shows>
  - Command output: <what user-pasted output confirmed>

### Fix
**🔥 Immediate Mitigation:**
<az or kubectl command to restore access now>

**🔧 Permanent Fix:**
File: `<file_path>` [repo: <repo>, branch: <branch>]
- Change: `<field>` from `<old>` to `<new>`
- Reason: <why this fixes the root cause>
(User makes this change — Copilot does NOT stage files)

**🔄 Rollback Path:**
<rollback command or pipeline step if fix makes things worse>

**♻️ Pod Restart (after fix applied):**
```bash
kubectl rollout restart deployment/<service> -n <namespace>
```

---
## All Sources
| Source | Tool | File / Query | Repo | Branch |
|--------|------|-------------|------|--------|
| KB | hivemind_get_secret_flow | <file_path> | <repo> | <branch> |
| KB | hivemind_query_memory | <file_path> | <repo> | <branch> |
| KB | hivemind_impact_analysis | <entity> | — | — |
| Live | <sherlock tool> | <tool(params)> | — | — |
| Cmd | User | <az/kubectl command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```
