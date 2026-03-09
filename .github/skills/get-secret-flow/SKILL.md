---
name: get-secret-flow
description: >
  Traces the complete secret lifecycle for a service: Key Vault creation ->
  data source read -> Kubernetes secret -> Helm mount -> Pod env var.
---

## When to use this skill

- "Secret flow for X"
- "How does X get its credentials"
- "Trace secret for service Y"
- "KV to pod chain for Z"
- Understanding how secrets move from Terraform to running pods
- Diagnosing secret-related access failures

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/get_secret_flow.py "{service_name}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --env | Filter by environment | --env production |

## Output

Returns the complete secret chain:
- **kv_secrets**: Key Vault secrets created in Terraform
  - Secret name, Key Vault name, source .tf file
- **data_reads**: Terraform data sources that read KV secrets
  - Data source name, referenced KV, source .tf file
- **k8s_secrets**: Kubernetes secrets created from KV values
  - Secret name, namespace, source .tf file
- **helm_mounts**: Helm chart values that mount K8s secrets
  - Mount path, secret reference, source values.yaml
- **chain_status**: Whether the chain is complete or has gaps

## Citation rule

Every secret claim MUST cite all 3 files in the chain:
1. Key Vault terraform file (where the secret is created)
2. K8s secret terraform file (where the secret is read and mounted)
3. Helm deployments.yaml (where the secret is consumed by the pod)

If any link in the chain is missing, explicitly state which link is missing.
