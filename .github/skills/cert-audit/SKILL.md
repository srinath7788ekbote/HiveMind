---
name: cert-audit
description: >
  Deep TLS/certificate investigation for any platform. Auto-detects cert
  infrastructure from the HiveMind KB (Istio mTLS, cert-manager, Azure KeyVault
  certificates, JVM truststore/keystore, Ingress/Gateway TLS) and investigates
  certificate failures across all detected platforms. Covers 6 failure modes
  with playbooks for each.
triggers:
  - certificate
  - cert
  - TLS
  - SSL
  - x509
  - expired
  - expiring
  - PKIX
  - handshake failed
  - certificate verify failed
  - mTLS
  - truststore
  - keystore
  - CERTIFICATE_VERIFY_FAILED
  - cert-manager
  - CertificateRequest
  - Certificate
  - Issuer
  - ClusterIssuer
  - tls secret
  - certificate rotation
  - cert expiry
  - PeerAuthentication
  - istio cert
  - Citadel
  - istiod cert
  - javax.net.ssl
  - SSLHandshakeException
  - sun.security.validator
slash_command: /cert-audit
---

# Cert Audit — TLS/Certificate Investigation Playbook

> This skill is the DEEP investigation layer for TLS certificate and PKI
> failures on any platform. It auto-detects the client's cert infrastructure
> from the HiveMind KB before investigating. Activated after `incident-triage`
> or `k8s-debug` identifies a certificate/TLS/mTLS problem, or directly when
> the user asks about certificates.
> Auto-detect first. Investigate what exists. Skip nothing.

---

## ⛔ CONSTRAINTS — ABSOLUTE, NO EXCEPTIONS

| # | Rule |
|---|------|
| CA-1 | **NEVER run commands.** User is on AVD via jump host. Recommend every `kubectl`, `openssl`, `keytool`, `az`, `istioctl` command. Wait for paste-back. |
| CA-2 | **NEVER assume platform.** Always auto-detect cert infrastructure from KB first. Never assume Azure/Istio/cert-manager — the KB tells you what exists. |
| CA-3 | **NEVER skip blast radius check.** Certificate failures cascade silently — a service works until the cert expires, then everything depending on it breaks. Always call `hivemind_impact_analysis`. |
| CA-4 | **NEVER block on Sherlock.** If unavailable, fall back to `kubectl logs` grep commands immediately. |
| CA-5 | **ALWAYS build an expiry timeline** for any cert failure. When did it expire? When was last rotation? Is auto-rotation enabled? |
| CA-6 | **ALWAYS check ALL detected cert platforms**, not just the obvious one. A service may have Istio mTLS AND an Ingress TLS cert AND a JVM truststore — all must be checked. |
| CA-7 | **ALWAYS cite file path + repo + branch** for every KB finding. |
| CA-8 | **ALWAYS provide exact file path + repo + branch + what to change.** User makes all changes — Copilot does NOT stage files. |
| CA-9 | **Commands MUST be copy-paste ready** with `<placeholder>` markers. `openssl` and `keytool` commands are user-run from jump host. |
| CA-10 | **NEVER answer from training data** when HiveMind KB or Sherlock has results. |

---

## 🔄 SHERLOCK FALLBACK RULE

| Path | Condition | Behavior |
|------|-----------|----------|
| **Path A** | Sherlock returns data | Use it — correlate SSL/TLS errors, cert expiry timing, deployment correlation |
| **Path B** | Sherlock unavailable or no data | Fall back to `kubectl logs` / `openssl` commands, continue seamlessly |

**Path A tools:**
- `mcp_sherlock_search_logs(service_name="<service>", keyword="ssl|cert|tls|pkix|handshake|x509|expired")` — cert failure logs
- `mcp_sherlock_get_service_incidents(service_name="<service>")` — active alerts (NR cert expiry alerts exist)
- `mcp_sherlock_get_deployments(app_name="<service>")` — deployment timing correlation
- `mcp_sherlock_get_service_golden_signals(service_name="<service>")` — error rate spike at cert expiry

**Path B fallback commands:**
```bash
# Cert/TLS errors in pod logs
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "ssl\|cert\|tls\|pkix\|handshake\|x509\|expired\|trust"

# Current container cert errors
kubectl logs <pod-name> -n <namespace> --tail=100 | grep -i "ssl\|cert\|tls"

# Deployment timing proxy
kubectl rollout history deployment/<service> -n <namespace>
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Certificate Failure Taxonomy — 6 Failure Modes

| ID | Failure Mode | One-Line Signal |
|----|-------------|-----------------|
| **CM-1** | CERT EXPIRED | Certificate past expiry date — connections fail with expired cert error |
| **CM-2** | CERT EXPIRING SOON | Certificate within warning threshold (30/14/7 days) — proactive action needed |
| **CM-3** | CERT NOT TRUSTED | Certificate exists but not in truststore — PKIX path building failed |
| **CM-4** | CERT WRONG DOMAIN | CN/SAN mismatch for the target hostname — hostname verification fails |
| **CM-5** | CERT ROTATION FAILED | Auto-rotation broke, stale cert still in use — cert-manager or KeyVault rotation stuck |
| **CM-6** | MTLS HANDSHAKE FAILED | Certificate exists but mTLS negotiation fails — peer auth mismatch or missing sidecar |

---

## Auto-Detection Phase — ALWAYS RUN FIRST

Before investigating ANY cert issue, determine what cert infrastructure this client actually has. **Never assume.**

### Step 1 — Query KB for Cert Infrastructure

```
STEP 1: Call hivemind_get_active_client()
        → Determines which client KB to search

STEP 2: Query KB for cert-related config:
  hivemind_query_memory(client=<client>, query="certificate tls")
  hivemind_query_memory(client=<client>, query="cert-manager Certificate Issuer")
  hivemind_query_memory(client=<client>, query="KeyVault certificate")
  hivemind_query_memory(client=<client>, query="istio certificate PeerAuthentication")
  hivemind_query_memory(client=<client>, query="keystore truststore javax.net.ssl")

STEP 3: Read discovered_profile.yaml:
  memory/clients/<client>/discovered_profile.yaml
  → Understand client cert infrastructure, services, environments
```

### Step 2 — Classify Detected Cert Infrastructure

| Platform | Detection Signal | What It Means |
|----------|-----------------|---------------|
| **PLATFORM A — Istio mTLS** | Found `PeerAuthentication`, `DestinationRule`, `istio-proxy` in KB | Service mesh with mutual TLS between services |
| **PLATFORM B — cert-manager** | Found `Certificate`, `Issuer`, `ClusterIssuer` CRDs in KB | Automated cert issuance and renewal via K8s |
| **PLATFORM C — KeyVault Certificates** | Found `azurerm_key_vault_certificate` in Terraform | Azure-managed certificate storage and rotation |
| **PLATFORM D — JVM Truststore/Keystore** | Found `keystore`, `truststore`, `javax.net.ssl` in Helm values or app config | Java app-level certificate management |
| **PLATFORM E — Ingress/Gateway TLS** | Found `tls` section in Ingress spec or Istio `Gateway` with `credentialName` | TLS termination at edge |

**Multiple platforms can coexist — investigate ALL that are detected.**

### Step 3 — State Detection Results

Before proceeding to investigation layers, ALWAYS output detection results:

```
Detected cert infrastructure for <client>:
  ✓ Istio mTLS (found PeerAuthentication in KB)
  ✓ cert-manager (found Certificate CRDs in KB)
  ✓ Azure KeyVault certificates (found in Terraform)
  ✗ JVM keystore (not found in KB)
  ✓ Ingress/Gateway TLS (found Gateway TLS config in KB)
Investigating relevant layers...
```

If a platform is NOT detected in KB but the user's error message suggests it exists (e.g., `SSLHandshakeException` implies JVM), note:
```
⚠️ JVM keystore not found in KB — but SSLHandshakeException suggests JVM TLS is involved.
   Investigating based on error signal. KB may be incomplete.
```

---

## Investigation Layers — Run Only Layers Relevant to Detected Platforms

### LAYER 1 — CERT-MANAGER INVESTIGATION
*(Run if cert-manager detected in KB — Platform B)*

**Step 1 — KB lookup:**
```
hivemind_query_memory(client=<client>, query="<service> Certificate cert-manager")
hivemind_query_memory(client=<client>, query="Issuer ClusterIssuer cert-manager")
```

**Step 2 — Commands to recommend:**
```bash
# 1. Check certificate status
kubectl get certificate -n <namespace>

# 2. Check certificate details
kubectl get certificate -n <namespace> -o wide

# 3. Describe the certificate (shows conditions, renewal status)
kubectl describe certificate <name> -n <namespace>

# 4. Check CertificateRequest status
kubectl get certificaterequest -n <namespace>

# 5. Describe CertificateRequest (shows approval, issuer response)
kubectl describe certificaterequest <name> -n <namespace>

# 6. Check issuer health
kubectl get issuer -n <namespace>
kubectl get clusterissuer

# 7. Describe issuer (shows status, conditions, last registration)
kubectl describe issuer <name> -n <namespace>

# 8. Check cert-manager controller logs
kubectl logs -n cert-manager -l app=cert-manager --tail=50
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| `Ready: False` | Cert not issued yet or renewal failed | CM-5: ROTATION FAILED |
| `Reason: Expired` | Past expiry, renewal should have triggered | CM-1: CERT EXPIRED |
| `Reason: Failed` | Issuer, ACME challenge, or KeyVault connector error | CM-5: ROTATION FAILED |
| `NotReady` issuer | All certs from that issuer are broken | CM-5: ROTATION FAILED (blast radius) |
| `renewBefore` too short | Renewal window smaller than issuance time | CM-2: EXPIRING SOON (risk) |
| CertificateRequest `Denied` | Approval policy rejected the request | CM-5: ROTATION FAILED |

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> Certificate cert-manager renewBefore")
hivemind_query_memory(client=<client>, query="Issuer ClusterIssuer <client>")
```

---

### LAYER 2 — AZURE KEYVAULT CERTIFICATE INVESTIGATION
*(Run if KeyVault certificates detected in KB — Platform C)*

**Step 1 — KB lookup:**
```
hivemind_query_memory(client=<client>, query="azurerm_key_vault_certificate")
hivemind_query_memory(client=<client>, query="<service> certificate keyvault")
hivemind_get_secret_flow(client=<client>, secret="<cert-name>")
```

**Step 2 — Commands to recommend:**
```bash
# 1. List certificates in vault
az keyvault certificate list --vault-name <vault> -o table

# 2. Show specific certificate (metadata, expiry, thumbprint)
az keyvault certificate show --vault-name <vault> --name <cert-name>

# 3. Check certificate policy (auto-rotation config)
az keyvault certificate show --vault-name <vault> --name <cert-name> --query policy.x509CertificateProperties

# 4. Check certificate auto-rotation policy
az keyvault certificate show --vault-name <vault> --name <cert-name> --query policy.lifetimeActions

# 5. Check if cert is syncing to K8s via CSI driver
kubectl get secretproviderclass -n <namespace> -o yaml | grep -A5 cert

# 6. Describe the TLS secret created from KV cert
kubectl describe secret <tls-secret-name> -n <namespace>
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| `enabled: false` | Cert disabled, won't sync | CM-5: ROTATION FAILED |
| Expiry date in the past | Certificate expired | CM-1: CERT EXPIRED |
| Expiry date < 30 days | Certificate expiring soon | CM-2: CERT EXPIRING SOON |
| No `lifetimeActions` configured | Auto-rotation not enabled | CM-5: ROTATION FAILED (risk) |
| CSI `SecretProviderClass` missing cert `objectType` | Cert not syncing to K8s | CM-5: ROTATION FAILED |

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="azurerm_key_vault_certificate terraform")
hivemind_query_memory(client=<client>, query="<service> certificate keyvault CSI")
hivemind_get_secret_flow(client=<client>, secret="<cert-name>")
```

---

### LAYER 3 — ISTIO MTLS CERTIFICATE INVESTIGATION
*(Run if Istio detected in KB — Platform A)*

**Step 1 — KB lookup:**
```
hivemind_query_memory(client=<client>, query="<service> PeerAuthentication DestinationRule")
hivemind_query_memory(client=<client>, query="istio tls certificate mTLS")
```

**Step 2 — Commands to recommend:**
```bash
# 1. Check Istio proxy cert sync status per pod
istioctl proxy-status

# 2. Check proxy cert details for specific pod
istioctl proxy-config secret <pod-name> -n <namespace>

# 3. Check cert expiry in Istio proxy
istioctl proxy-config secret <pod-name> -n <namespace> -o json | grep -A5 "EXPIRE"

# 4. Check Istio control plane cert
kubectl get secret -n istio-system | grep -i cert
kubectl describe secret istio-ca-secret -n istio-system

# 5. Check PeerAuthentication (mTLS mode)
kubectl get peerauthentication -A
kubectl get peerauthentication -n <namespace> -o yaml

# 6. Check DestinationRule TLS settings
kubectl get destinationrule -n <namespace> -o yaml
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| `CERT_CHAIN` missing in proxy secret | Pod sidecar not getting cert from istiod | CM-6: MTLS HANDSHAKE FAILED |
| Cert expiry < 24h in proxy | Istio rotation failing, istiod issue | CM-1: CERT EXPIRED |
| PeerAuthentication `STRICT` + no sidecar on peer | Sidecar-less service can't connect | CM-6: MTLS HANDSHAKE FAILED |
| DestinationRule `clientTLSMode` mismatch | One side expects TLS, other doesn't | CM-6: MTLS HANDSHAKE FAILED |
| `RBAC: access denied` with mTLS context | AuthorizationPolicy blocking with cert identity | CM-6: MTLS HANDSHAKE FAILED |
| istiod logs show cert signing errors | Control plane cert issuance broken | CM-5: ROTATION FAILED |

**Istio cert rotation (ONLY with explicit user approval — restarts control plane):**
```bash
kubectl rollout restart deployment/istiod -n istio-system
```

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> PeerAuthentication DestinationRule mTLS")
hivemind_query_memory(client=<client>, query="istio tls certificate istiod")
```

---

### LAYER 4 — INGRESS / GATEWAY TLS INVESTIGATION
*(Run if Ingress TLS or Istio Gateway detected — Platform E)*

**Step 1 — KB lookup:**
```
hivemind_query_memory(client=<client>, query="<service> tls ingress gateway")
hivemind_query_memory(client=<client>, query="Gateway tls credentialName")
```

**Step 2 — Commands to recommend:**
```bash
# 1. Check TLS secret referenced in Ingress
kubectl get ingress -n <namespace> -o yaml | grep -A5 tls

# 2. Check TLS config in Istio Gateway
kubectl get gateway -n <namespace> -o yaml | grep -A10 tls

# 3. Check the TLS secret exists
kubectl get secret <tls-secret-name> -n <namespace>

# 4. Check cert expiry from the K8s secret directly
kubectl get secret <tls-secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -dates

# 5. Check cert SAN/CN from the K8s secret
kubectl get secret <tls-secret-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -subject -ext subjectAltName

# 6. Check external TLS cert (run from jump host with external access)
openssl s_client -connect <hostname>:443 -servername <hostname> </dev/null 2>/dev/null | openssl x509 -noout -dates -subject -ext subjectAltName
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| TLS secret not found | Secret deleted or never created | CM-5: ROTATION FAILED |
| `notAfter` date in the past | Ingress/Gateway cert expired | CM-1: CERT EXPIRED |
| CN/SAN doesn't match hostname | Wrong cert for this domain | CM-4: CERT WRONG DOMAIN |
| Gateway `credentialName` doesn't match secret name | Gateway referencing wrong secret | CM-4: CERT WRONG DOMAIN |
| External `openssl` shows different cert than K8s secret | CDN/LB terminating with different cert | CM-4: CERT WRONG DOMAIN |

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> tls ingress gateway credentialName")
hivemind_query_memory(client=<client>, query="Gateway tls credentialName <hostname>")
```

---

### LAYER 5 — JVM TRUSTSTORE/KEYSTORE INVESTIGATION
*(Run if Java keystore/truststore detected in KB — Platform D)*

**Symptoms in app logs:**
```
javax.net.ssl.SSLHandshakeException
sun.security.validator.ValidatorException: PKIX path building failed
PKIX path building failed: unable to find valid certification path to requested target
```

**Step 1 — KB lookup:**
```
hivemind_query_memory(client=<client>, query="<service> truststore keystore javax.net.ssl")
hivemind_query_memory(client=<client>, query="<service> ssl JAVA_OPTS JAVA_TOOL_OPTIONS")
hivemind_query_memory(client=<client>, query="<service> application.yaml ssl server.ssl")
```

**Step 2 — Commands to recommend:**
```bash
# 1. Check if custom truststore is mounted
kubectl get pod <pod> -n <namespace> -o yaml | grep -A10 volumeMounts

# 2. Check for cert-related volumes
kubectl get pod <pod> -n <namespace> -o yaml | grep -A10 volumes | grep -i cert

# 3. List certs in JVM default truststore (if pod is Running)
kubectl exec -it <pod> -n <namespace> -- keytool -list -cacerts -storepass changeit | grep <cert-alias>

# 4. Check if custom truststore is set via JAVA_OPTS
kubectl exec <pod> -n <namespace> -- printenv | grep -i "trust\|keystore\|ssl\|javax"

# 5. Check Spring Boot SSL config in ConfigMap
kubectl get configmap -n <namespace> -l app=<service> -o yaml | grep -i "ssl\|trust\|keystore"

# 6. Check if CA cert bundle is mounted as ConfigMap/Secret
kubectl describe configmap <name> -n <namespace> | grep -i cert
```

**Output interpretation:**

| If You See | It Means | Failure Mode |
|------------|----------|-------------|
| No custom truststore mounted | App uses default JVM cacerts | CM-3: CERT NOT TRUSTED (if custom CA needed) |
| `PKIX path building failed` in logs | Target cert's CA not in truststore | CM-3: CERT NOT TRUSTED |
| Custom truststore mounted but missing CA | CA cert not added to custom bundle | CM-3: CERT NOT TRUSTED |
| `javax.net.ssl.trustStore` env var missing | Truststore path not configured | CM-3: CERT NOT TRUSTED |
| `server.ssl.key-store` misconfigured | Keystore for server-side TLS broken | CM-5: ROTATION FAILED |

**KB cross-reference:**
```
hivemind_query_memory(client=<client>, query="<service> javax.net.ssl truststore JAVA_OPTS")
hivemind_query_memory(client=<client>, query="<service> JAVA_TOOL_OPTIONS ssl")
```

---

## Sherlock Correlation

### Path A — Sherlock Available

```
mcp_sherlock_search_logs(service_name="<service>", keyword="ssl|cert|tls|pkix|handshake|x509|expired")
mcp_sherlock_get_service_incidents(service_name="<service>")
mcp_sherlock_get_service_golden_signals(service_name="<service>")
mcp_sherlock_get_deployments(app_name="<service>")
```

Look for:
- `SSLHandshakeException`, `PKIX`, `certificate` errors in logs
- Error rate spike correlating with cert expiry or rotation time
- Whether NR alert fired for cert expiry (alerts exist for this)
- Deployment timing — did a deploy coincide with cert failure?

### Path B — Sherlock Unavailable

```bash
# Cert/TLS errors in previous container logs
kubectl logs <pod-name> -n <namespace> --previous --tail=300 | grep -i "ssl\|cert\|tls\|pkix\|handshake\|x509\|expired\|trust"

# Current container cert errors
kubectl logs <pod-name> -n <namespace> --tail=100 | grep -i "ssl\|cert\|tls"

# Istio proxy logs (if Istio detected)
kubectl logs <pod-name> -n <namespace> -c istio-proxy --tail=100 | grep -i "ssl\|tls\|cert\|handshake"
```

State: `"⚠️ Sherlock unavailable — proceeding with command-based investigation"`

---

## Blast Radius Check — NEVER SKIP

Certificate failures cascade silently — service works until cert expires, then everything depending on it fails simultaneously.

**After identifying ANY cert issue:**

```
# 1. Impact analysis on affected service
hivemind_impact_analysis(client=<client>, entity="<service>")

# 2. Find all services referencing the same cert or issuer
hivemind_query_memory(client=<client>, query="<cert-name> certificate service")
hivemind_query_memory(client=<client>, query="<issuer-name> Issuer ClusterIssuer service")

# 3. Find all services with mTLS to this service
hivemind_query_memory(client=<client>, query="<service> PeerAuthentication DestinationRule upstream downstream")
```

**Report format:**
```
### Blast Radius
| Affected Service | Same Cert? | Same Issuer? | mTLS Dependency? | Current State |
|-----------------|-----------|-------------|-----------------|---------------|
| <service-1> | Yes | Yes | Yes | 503 errors |
| <service-2> | No | Yes | Yes | Healthy (different cert) |
| <service-3> | No | No | No | Not affected |

Total services at risk: <N>
Shared issuer: <issuer-name> [<N> certificates]
Shared cert: <cert-name> [<N> services]
mTLS peers affected: <N>
```

---

## Expiry Timeline — ALWAYS BUILD FOR CERT FAILURES

When cert expiry is involved, ALWAYS construct a timeline:

```
### Expiry Timeline
| Field | Value |
|-------|-------|
| Certificate | <cert-name> |
| Not Before | <start date> |
| Not After (Expiry) | <expiry date> |
| Last Successful Rotation | <date or "unknown"> |
| Auto-Rotation Enabled? | Yes (cert-manager renewBefore: <value>) / Yes (KeyVault lifetimeActions) / No |
| Renewal Window | <N days before expiry> |
| Time Until Impact | EXPIRED <N days ago> / Expires in <N days/hours> |
| How Long Until Service Impact? | <assessment based on cert type> |
```

**Urgency levels:**

| Level | Criteria | Action |
|-------|----------|--------|
| **CRITICAL** | Expired or expiring < 24 hours | Immediate remediation required |
| **HIGH** | Expiring in 1–7 days | Urgent fix within business day |
| **MEDIUM** | Expiring in 7–30 days | Plan rotation in next sprint |
| **LOW** | Expiring > 30 days | Proactive — add to backlog |

---

## Failure Mode Playbooks

### CM-1: CERT EXPIRED

**How to confirm:** Certificate `notAfter` date is in the past. `openssl x509 -noout -dates` shows expired date. cert-manager shows `Reason: Expired`. Connection errors reference `expired certificate`.

**Investigation layers to run:** Layer 1 (cert-manager status), Layer 2 (KeyVault cert expiry), Layer 4 (Ingress/Gateway TLS)

**Most likely root cause:** Auto-rotation failed silently — cert-manager or KeyVault rotation policy not configured, or renewal process hit an error that went unnoticed.

**File to fix:** cert-manager `Certificate` resource — check `renewBefore` and `duration` fields.
Typical path: `charts/<service>/templates/certificate.yaml` or `certificates/<service>.yaml` [repo: artifacts repo, branch: environment branch]

**Remediation:**
- **Immediate:** Manually trigger cert renewal: `kubectl delete certificate <name> -n <ns>` (cert-manager will re-create)
- **Permanent:** Configure `renewBefore` to be at least 30 days: update Helm values or Certificate resource
- **Verify:** `kubectl get certificate -n <ns>` shows `Ready: True`

**Common gotcha:** cert-manager may show `Ready: True` even after renewal if the old TLS secret wasn't rotated in consuming pods. Pods may cache the old cert in memory — restart required:
```bash
kubectl rollout restart deployment/<service> -n <namespace>
```

---

### CM-2: CERT EXPIRING SOON

**How to confirm:** Certificate `notAfter` is within 30/14/7 days. New Relic alert may have fired for cert expiry warning.

**Investigation layers to run:** Layer 1 (cert-manager renewal status), Layer 2 (KeyVault rotation policy)

**Most likely root cause:** Auto-rotation is configured but renewal window (`renewBefore`) is too short, or the rotation process is slower than expected.

**File to fix:** cert-manager `Certificate` resource `renewBefore` field, or KeyVault `lifetimeActions` policy.

**Remediation:**
- **Immediate:** Trigger early renewal if within danger zone
- **Permanent:** Increase `renewBefore` to 30+ days in Certificate resource

**Common gotcha:** `renewBefore` in cert-manager must be SHORTER than `duration`. If `duration: 90d` and `renewBefore: 91d`, cert-manager silently ignores renewal. Check both fields together:
```bash
kubectl get certificate <name> -n <ns> -o jsonpath='{.spec.duration} {.spec.renewBefore}'
```

---

### CM-3: CERT NOT TRUSTED

**How to confirm:** Logs show `PKIX path building failed`, `certificate verify failed`, `unable to find valid certification path`. The cert exists and is valid, but the client doesn't trust the CA.

**Investigation layers to run:** Layer 5 (JVM truststore), Layer 3 (Istio CA), Layer 4 (Ingress cert chain)

**Most likely root cause:** The target service's certificate is signed by a CA that isn't in the calling service's truststore. Common with internal CAs, Azure-managed CAs, or Istio's self-signed CA.

**File to fix:** JVM truststore configuration in Helm values (`JAVA_OPTS` with `-Djavax.net.ssl.trustStore`), or custom CA bundle ConfigMap.
Typical path: `charts/<service>/values.yaml` → `env.JAVA_TOOL_OPTIONS` or `volumes` section [repo: artifacts repo]

**Remediation:**
- **Immediate:** Add CA cert to JVM truststore or custom CA bundle
- **Permanent:** Include CA cert in base Docker image or mount via ConfigMap at build time

**Common gotcha:** Java `cacerts` doesn't include Azure internal CA by default — a custom CA bundle is needed in the base Docker image. Mounting a custom truststore via volume overrides the default cacerts entirely — all standard CAs (DigiCert, Let's Encrypt, etc.) must be included in the custom bundle.

---

### CM-4: CERT WRONG DOMAIN

**How to confirm:** TLS handshake fails with hostname verification error. `openssl s_client` shows certificate CN/SAN doesn't include the requested hostname.

**Investigation layers to run:** Layer 4 (Ingress/Gateway config), Layer 1 (cert-manager dnsNames)

**Most likely root cause:** Certificate was issued for a different domain or subdomain. Istio Gateway `credentialName` references a secret containing a cert with wrong SAN.

**File to fix:** cert-manager `Certificate` resource `dnsNames` field, or Ingress TLS host configuration.
Typical path: `charts/<service>/templates/certificate.yaml` → `spec.dnsNames` [repo: artifacts repo]

**Remediation:**
- **Immediate:** Update cert `dnsNames` to include the correct hostname, delete old Certificate for re-issuance
- **Permanent:** Ensure cert dnsNames match all hostnames used by the service (including internal DNS)

**Common gotcha:** Istio Gateway `credentialName` must match the exact K8s secret name containing the right SAN. If two Gateways reference different secrets but serve the same domain, the first-loaded Gateway wins — may serve wrong cert.

---

### CM-5: CERT ROTATION FAILED

**How to confirm:** cert-manager Certificate shows `Ready: False` with `Reason: Failed` or `Issuing`. KeyVault cert shows old `updated` date despite rotation policy existing. The cert in use is stale while a newer version exists somewhere.

**Investigation layers to run:** Layer 1 (cert-manager CertificateRequest), Layer 2 (KeyVault rotation policy), Layer 4 (TLS secret age)

**Most likely root cause:** cert-manager issuer lost connectivity to CA, KeyVault rotation event fired but CSI driver cached old cert, or cert-manager controller crashed during renewal.

**File to fix:** cert-manager `Issuer` resource (CA connectivity), `Certificate` resource (renewal config), or CSI `SecretProviderClass` (sync config).

**Remediation:**
- **Immediate:** Check cert-manager controller logs, restart if needed: `kubectl rollout restart deployment/cert-manager -n cert-manager` (with user approval)
- **Permanent:** Fix issuer connectivity, add monitoring for cert-manager health

**Common gotcha:** KeyVault rotation event triggers successfully, but the CSI driver may cache the old cert. Pods need restart to pick up the new cert synced via CSI:
```bash
kubectl rollout restart deployment/<service> -n <namespace>
```

---

### CM-6: MTLS HANDSHAKE FAILED

**How to confirm:** Service-to-service calls fail with connection reset or 503. Istio proxy logs show TLS handshake errors. One service has `PeerAuthentication: STRICT` but the calling service has no sidecar.

**Investigation layers to run:** Layer 3 (Istio mTLS), Layer 1 (cert-manager if Istio uses custom certs)

**Most likely root cause:** One service upgraded to Istio `STRICT` mTLS while a calling service either has no sidecar injected or has a `DestinationRule` with wrong TLS mode.

**File to fix:** `PeerAuthentication` resource (`STRICT` vs `PERMISSIVE`), or `DestinationRule` TLS settings.
Typical path: `charts/<service>/templates/peer-authentication.yaml` or K8s manifests [repo: artifacts repo]

**Remediation:**
- **Immediate:** Temporarily set `PeerAuthentication` to `PERMISSIVE` for the affected namespace (with user approval — reduces security)
- **Permanent:** Ensure all services in the mesh have sidecars injected, then enforce `STRICT`

**Common gotcha:** One service upgraded to Istio `STRICT` while a calling service has no sidecar — results in 503 with NO cert error in the calling service's logs. The error only appears in the Istio proxy logs of the target service. Check the TARGET service's `istio-proxy` container logs, not the caller's app logs:
```bash
kubectl logs <target-pod> -n <namespace> -c istio-proxy --tail=100 | grep -i "tls\|handshake\|ssl"
```

---

## Output Format — CERT AUDIT REPORT

Every cert-audit response MUST use this structure:

```
## 🔐 CERT AUDIT REPORT

### Detected Cert Infrastructure
| Platform | Detected? | Evidence |
|----------|----------|---------|
| Istio mTLS | ✓/✗ | <what was found in KB> |
| cert-manager | ✓/✗ | <what was found in KB> |
| KeyVault Certificates | ✓/✗ | <what was found in KB> |
| JVM Truststore/Keystore | ✓/✗ | <what was found in KB> |
| Ingress/Gateway TLS | ✓/✗ | <what was found in KB> |

### Failure Mode Classification
| Field | Value |
|-------|-------|
| Failure Mode | <CM-1 through CM-6: label> |
| Service | <service name> |
| Namespace | <namespace> |
| Certificate | <cert name or identifier> |
| Platform | <which cert platform(s) affected> |
| Investigation Path | <Path A (Sherlock) or Path B (command-based)> |

### Expiry Timeline
| Field | Value |
|-------|-------|
| Expiry Date | <date> |
| Last Rotation | <date or unknown> |
| Auto-Rotation | <enabled/disabled> |
| Urgency | <CRITICAL/HIGH/MEDIUM/LOW> |
| Time Until Impact | <assessment> |

### Layer Findings
<findings from each investigated layer with KB citations>
📁 Sources:
  - `<file_path>` [repo: <repo>, branch: <branch>]

### Blast Radius
| Affected Service | Same Cert? | Same Issuer? | mTLS Dependency? | Risk |
|-----------------|-----------|-------------|-----------------|------|
| <service> | Yes/No | Yes/No | Yes/No | 🔴/🟡/🟢 |

Total at risk: <N> services

### Observability Correlation
**Path A (Sherlock):**
| Signal | Value |
|--------|-------|
| Cert errors in logs | <count / pattern> |
| Error rate since incident | <value> |
| Last deployment | <timestamp> |

**OR Path B (Sherlock unavailable):**
⚠️ Sherlock unavailable — proceeding with command-based investigation
Recommended log check:
```bash
kubectl logs <pod> -n <ns> --previous --tail=300 | grep -i "ssl|cert|tls|pkix|handshake"
```

### Recommended Commands
Run these on your jump host and paste the output back:

**1. <purpose>**
```bash
<copy-paste ready command>
```
> What to look for: <specific patterns>

### Root Cause
📋 **Failure Mode:** CM-<N>: <label>
📋 **Root Cause:** <specific statement — never generic>
🎯 **Confidence:** HIGH / MEDIUM / LOW
📁 **Evidence:**
  - KB: `<file>` [repo: <repo>, branch: <branch>] — <what it shows>
  - Command output: <what user-pasted output confirmed>

### Fix
**🔥 Immediate Mitigation:**
<command or action to restore TLS connectivity now>

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
| KB | hivemind_query_memory | <file_path> | <repo> | <branch> |
| KB | hivemind_impact_analysis | <entity> | — | — |
| Live | <sherlock tool> | <tool(params)> | — | — |
| Cmd | User | <kubectl command> | — | — |

🎯 Confidence: {HIGH|MEDIUM|LOW}
```
