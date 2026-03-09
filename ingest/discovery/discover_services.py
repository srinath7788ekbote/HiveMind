"""
Discover Services

Finds service definitions across all repo types:
- Harness: .harness/services/*.yaml
- Helm: charts/*/Chart.yaml
- Kubernetes: manifests with kind: Deployment/Service
- Pipeline refs: serviceRef in pipeline YAML

Returns deduplicated list of services with source info.
"""

import os
import re
from pathlib import Path
from typing import Optional


def _normalize_service_name(name: str) -> str:
    """
    Normalize service name for deduplication.
    audit-service, audit_service, auditservice → audit-service
    """
    normalized = name.lower().strip()
    normalized = re.sub(r'[_\s]+', '-', normalized)
    # Remove version suffixes like _v4, -v2
    normalized = re.sub(r'-v\d+$', '', normalized)
    return normalized


def _discover_from_harness(repo_path: Path) -> list[dict]:
    """Find services defined in .harness/services/."""
    services = []
    harness_svc_dir = repo_path / ".harness" / "services"
    if not harness_svc_dir.exists():
        return services

    for yaml_file in harness_svc_dir.iterdir():
        if yaml_file.suffix in ('.yaml', '.yml') and yaml_file.is_file():
            try:
                content = yaml_file.read_text(encoding='utf-8')
                # Extract service name from filename or content
                svc_name = yaml_file.stem
                # Try to find identifier in content
                id_match = re.search(r'identifier:\s*["\']?(\S+)["\']?', content)
                if id_match:
                    svc_name = id_match.group(1)
                name_match = re.search(r'name:\s*["\']?([^"\'\n]+)["\']?', content)
                display_name = name_match.group(1).strip() if name_match else svc_name

                services.append({
                    "name": _normalize_service_name(svc_name),
                    "display_name": display_name,
                    "source": "harness",
                    "file": str(yaml_file.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
            except (OSError, UnicodeDecodeError):
                continue
    return services


def _discover_from_helm(repo_path: Path) -> list[dict]:
    """Find services from Helm chart definitions."""
    services = []
    charts_dir = repo_path / "charts"
    if not charts_dir.exists():
        return services

    for chart_dir in charts_dir.iterdir():
        if not chart_dir.is_dir():
            continue
        chart_file = chart_dir / "Chart.yaml"
        if not chart_file.exists():
            chart_file = chart_dir / "Chart.yml"
        if not chart_file.exists():
            continue

        try:
            content = chart_file.read_text(encoding='utf-8')
            name_match = re.search(r'^name:\s*["\']?([^"\'\n]+)["\']?', content, re.MULTILINE)
            svc_name = name_match.group(1).strip() if name_match else chart_dir.name

            version_match = re.search(r'^version:\s*["\']?([^"\'\n]+)["\']?', content, re.MULTILINE)
            version = version_match.group(1).strip() if version_match else "unknown"

            services.append({
                "name": _normalize_service_name(svc_name),
                "display_name": svc_name,
                "source": "helm",
                "file": str(chart_file.relative_to(repo_path)),
                "repo": repo_path.name,
                "version": version,
            })
        except (OSError, UnicodeDecodeError):
            continue
    return services


def _discover_from_pipelines(repo_path: Path) -> list[dict]:
    """Find serviceRef references in pipeline YAML files."""
    services = []
    seen = set()

    for yaml_file in repo_path.rglob("pipeline.yaml"):
        try:
            content = yaml_file.read_text(encoding='utf-8')
            for match in re.finditer(r'serviceRef:\s*["\']?(\S+)["\']?', content):
                svc_name = match.group(1)
                normalized = _normalize_service_name(svc_name)
                if normalized not in seen:
                    seen.add(normalized)
                    services.append({
                        "name": normalized,
                        "display_name": svc_name,
                        "source": "pipeline_ref",
                        "file": str(yaml_file.relative_to(repo_path)),
                        "repo": repo_path.name,
                    })
        except (OSError, UnicodeDecodeError):
            continue
    return services


def discover_services(repo_paths: list[str]) -> list[dict]:
    """
    Discover services across multiple repositories.
    Deduplicates by normalized name, keeping all source references.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        List of service dicts with keys:
            name: str — normalized service name
            display_name: str — human-readable name
            sources: list[dict] — all source references (source, file, repo)
    """
    all_services: dict[str, dict] = {}

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        discovered = []
        discovered.extend(_discover_from_harness(repo_path))
        discovered.extend(_discover_from_helm(repo_path))
        discovered.extend(_discover_from_pipelines(repo_path))

        for svc in discovered:
            name = svc["name"]
            if name not in all_services:
                all_services[name] = {
                    "name": name,
                    "display_name": svc.get("display_name", name),
                    "sources": [],
                }
            all_services[name]["sources"].append({
                "source": svc["source"],
                "file": svc["file"],
                "repo": svc["repo"],
            })

    return sorted(all_services.values(), key=lambda s: s["name"])
