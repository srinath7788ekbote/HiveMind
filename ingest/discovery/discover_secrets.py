"""
Discover Secrets

Finds secret definitions and detects naming patterns:
- Azure Key Vault secrets in Terraform
- Kubernetes secrets in Terraform
- Secret references in Helm charts
- Secret naming patterns (e.g., automation-{env}-db{service})
"""

import re
from pathlib import Path
from typing import Optional


def _discover_kv_secrets(repo_path: Path) -> list[dict]:
    """Find Azure Key Vault secret resources in Terraform files."""
    secrets = []
    for tf_file in repo_path.rglob("*.tf"):
        try:
            content = tf_file.read_text(encoding='utf-8')
            # Match azurerm_key_vault_secret resources
            pattern = re.compile(
                r'resource\s+"azurerm_key_vault_secret"\s+"(\w+)"\s*\{(.*?)\}',
                re.DOTALL,
            )
            for match in pattern.finditer(content):
                resource_name = match.group(1)
                block = match.group(2)
                name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
                secret_name = name_match.group(1) if name_match else resource_name

                secrets.append({
                    "resource_name": resource_name,
                    "secret_name": secret_name,
                    "type": "kv_secret",
                    "file": str(tf_file.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
        except (OSError, UnicodeDecodeError):
            continue
    return secrets


def _discover_k8s_secrets(repo_path: Path) -> list[dict]:
    """Find Kubernetes secret resources in Terraform files."""
    secrets = []
    for tf_file in repo_path.rglob("*.tf"):
        try:
            content = tf_file.read_text(encoding='utf-8')
            pattern = re.compile(
                r'resource\s+"kubernetes_secret"\s+"(\w+)"\s*\{(.*?)\n\}',
                re.DOTALL,
            )
            for match in pattern.finditer(content):
                resource_name = match.group(1)
                block = match.group(2)

                # Find the metadata name
                meta_match = re.search(
                    r'metadata\s*\{[^}]*name\s*=\s*"([^"]+)"',
                    block,
                    re.DOTALL,
                )
                secret_name = meta_match.group(1) if meta_match else resource_name

                # Find KV secret references in data block
                kv_refs = re.findall(
                    r'data\.azurerm_key_vault_secret\.(\w+)\.value',
                    block,
                )

                secrets.append({
                    "resource_name": resource_name,
                    "secret_name": secret_name,
                    "type": "k8s_secret",
                    "kv_refs": kv_refs,
                    "file": str(tf_file.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
        except (OSError, UnicodeDecodeError):
            continue
    return secrets


def _discover_helm_secret_refs(repo_path: Path) -> list[dict]:
    """Find secretKeyRef references in Helm templates."""
    secrets = []
    for yaml_file in repo_path.rglob("*.yaml"):
        if "templates" not in str(yaml_file):
            continue
        try:
            content = yaml_file.read_text(encoding='utf-8')
            # Look for secretKeyRef patterns
            pattern = re.compile(
                r'secretKeyRef:\s*\n\s+name:\s*["\']?([^"\'\n]+)["\']?'
                r'\s*\n\s+key:\s*["\']?([^"\'\n]+)["\']?',
                re.MULTILINE,
            )
            for match in pattern.finditer(content):
                secrets.append({
                    "secret_name": match.group(1).strip(),
                    "key": match.group(2).strip(),
                    "type": "helm_mount",
                    "file": str(yaml_file.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
        except (OSError, UnicodeDecodeError):
            continue
    return secrets


def _detect_naming_pattern(secret_names: list[str]) -> list[dict]:
    """
    Detect naming patterns from a list of secret names.
    E.g., automation-dev-dbauditservice → automation-{env}-db{service}
    """
    patterns = []

    # Common environment tokens to look for
    env_tokens = ['dev', 'stg', 'staging', 'prod', 'prd', 'uat', 'np', 'sandbox']

    for name in secret_names:
        name_lower = name.lower()
        detected_env = None
        for env in env_tokens:
            if env in name_lower:
                detected_env = env
                break

        if detected_env:
            # Replace the env token with {env} placeholder
            pattern = name_lower.replace(detected_env, '{env}')

            # Try to detect service name component
            # Look for common service-related prefixes after 'db'
            db_match = re.search(r'db(\w+)', name_lower)
            if db_match:
                service_part = db_match.group(1)
                pattern = pattern.replace(f'db{service_part}', 'db{{service}}')

            patterns.append({
                "example": name,
                "pattern": pattern,
                "confidence": 0.8 if detected_env and db_match else 0.5,
            })

    # Deduplicate patterns
    seen_patterns = set()
    unique = []
    for p in patterns:
        if p["pattern"] not in seen_patterns:
            seen_patterns.add(p["pattern"])
            unique.append(p)

    return unique


def discover_secrets(repo_paths: list[str]) -> dict:
    """
    Discover secrets across multiple repositories.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        dict with keys:
            kv_secrets: list[dict] — KV secret resources
            k8s_secrets: list[dict] — K8s secret resources
            helm_mounts: list[dict] — Helm secretKeyRef references
            naming_patterns: list[dict] — detected naming patterns
    """
    all_kv = []
    all_k8s = []
    all_helm = []

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        all_kv.extend(_discover_kv_secrets(repo_path))
        all_k8s.extend(_discover_k8s_secrets(repo_path))
        all_helm.extend(_discover_helm_secret_refs(repo_path))

    # Detect naming patterns from all secret names
    all_names = [s["secret_name"] for s in all_kv] + [s["secret_name"] for s in all_k8s]
    naming_patterns = _detect_naming_pattern(all_names)

    return {
        "kv_secrets": all_kv,
        "k8s_secrets": all_k8s,
        "helm_mounts": all_helm,
        "naming_patterns": naming_patterns,
    }
