"""
Build Profile

Aggregates all discovery results into a single discovered_profile.yaml file.
This is the client's architecture fingerprint used by agents.
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from ingest.discovery.discover_repo_type import discover_repo_type
from ingest.discovery.discover_services import discover_services
from ingest.discovery.discover_environments import discover_environments
from ingest.discovery.discover_pipelines import discover_pipelines
from ingest.discovery.discover_infra_layers import discover_infra_layers
from ingest.discovery.discover_secrets import discover_secrets
from ingest.discovery.discover_naming import discover_naming


def build_profile(
    client_name: str,
    repo_configs: list[dict],
    output_dir: str,
) -> dict:
    """
    Run all discovery modules and build the discovered_profile.yaml.

    Args:
        client_name: Client identifier (e.g., "dfin")
        repo_configs: List of repo config dicts from repos.yaml,
                      each with at least "name" and "path" keys.
        output_dir: Directory to write discovered_profile.yaml

    Returns:
        The complete profile dict.
    """
    repo_paths = []
    repo_info = []

    for rc in repo_configs:
        rp = rc.get("path", "")
        if not rp or not Path(rp).exists():
            continue
        repo_paths.append(rp)
        repo_type_result = discover_repo_type(rp)
        repo_info.append({
            "name": rc.get("name", Path(rp).name),
            "path": rp,
            "type": repo_type_result.get("type", "unknown"),
            "platform": repo_type_result.get("platform", "unknown"),
            "confidence": repo_type_result.get("confidence", 0.0),
            "branches": rc.get("branches", []),
        })

    services = discover_services(repo_paths)
    environments = discover_environments(repo_paths)
    pipelines = discover_pipelines(repo_paths)
    infra_layers = discover_infra_layers(repo_paths)
    secrets_result = discover_secrets(repo_paths)
    naming_result = discover_naming(repo_paths)

    profile = {
        "client": client_name,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "repos": repo_info,
        "services": services,
        "environments": environments,
        "pipelines": pipelines,
        "infra_layers": infra_layers,
        "secrets": {
            "kv_secrets": secrets_result.get("kv_secrets", []),
            "k8s_secrets": secrets_result.get("k8s_secrets", []),
            "helm_mounts": secrets_result.get("helm_mounts", []),
        },
        "secret_patterns": secrets_result.get("naming_patterns", []),
        "naming_conventions": naming_result.get("conventions", []),
        "summary": {
            "repo_count": len(repo_info),
            "service_count": len(services),
            "environment_count": len(environments),
            "pipeline_count": len(pipelines),
            "infra_layer_count": len(infra_layers),
            "kv_secret_count": len(secrets_result.get("kv_secrets", [])),
            "k8s_secret_count": len(secrets_result.get("k8s_secrets", [])),
            "naming_convention_count": len(naming_result.get("conventions", [])),
        },
    }

    # Write the profile
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    profile_file = output_path / "discovered_profile.yaml"

    # Write as YAML-like format without requiring PyYAML
    # Using a simple serializer
    try:
        import yaml
        with open(profile_file, 'w', encoding='utf-8') as f:
            yaml.dump(profile, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
    except ImportError:
        # Fallback: write as JSON (still valid, just not as pretty)
        with open(profile_file, 'w', encoding='utf-8') as f:
            json.dump(profile, f, indent=2, ensure_ascii=False)

    # Also write as JSON for easy programmatic access
    json_file = output_path / "discovered_profile.json"
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(profile, f, indent=2, ensure_ascii=False)

    return profile
