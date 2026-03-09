"""
Discover Repository Type

Classifies a repository based on its file structure and contents.
Returns a dict with type, platform, and confidence.

Supported types:
  - cicd/harness
  - infrastructure/terraform
  - helm
  - application
  - documentation
  - unknown
"""

import os
from pathlib import Path
from typing import Optional


def discover_repo_type(repo_path: str) -> dict:
    """
    Classify a repository by examining its directory structure and file patterns.

    Args:
        repo_path: Absolute path to the repository root.

    Returns:
        dict with keys:
            type: str — high-level type (cicd, infrastructure, helm, application, etc.)
            platform: str — specific platform (harness, terraform, helm, etc.)
            confidence: float — 0.0 to 1.0
            indicators: list[str] — what was found that led to the classification
    """
    repo = Path(repo_path)
    if not repo.exists():
        return {
            "type": "unknown",
            "platform": "unknown",
            "confidence": 0.0,
            "indicators": [f"Path does not exist: {repo_path}"],
        }

    indicators = []
    scores = {
        "cicd/harness": 0.0,
        "infrastructure/terraform": 0.0,
        "helm": 0.0,
        "application": 0.0,
    }

    # Check for Harness CI/CD indicators
    harness_dir = repo / ".harness"
    if harness_dir.exists() and harness_dir.is_dir():
        scores["cicd/harness"] += 0.4
        indicators.append(".harness/ directory found")

    # Look for pipeline YAML files in common Harness patterns
    for pattern_dir in ["newad", "pipelines", "ci", "cd"]:
        check = repo / pattern_dir
        if check.exists():
            yaml_files = list(check.rglob("pipeline.yaml")) + list(check.rglob("pipeline.yml"))
            if yaml_files:
                scores["cicd/harness"] += 0.3
                indicators.append(f"Pipeline YAML files found in {pattern_dir}/")
                break

    # Check for pipeline files directly
    pipeline_files = list(repo.rglob("pipeline.yaml")) + list(repo.rglob("pipeline.yml"))
    if pipeline_files:
        scores["cicd/harness"] += 0.2
        indicators.append(f"{len(pipeline_files)} pipeline.yaml files found")

    # Check Harness services/environments directories
    for sub in ["services", "environments", "overrides"]:
        check = harness_dir / sub if harness_dir.exists() else repo / sub
        if check.exists():
            scores["cicd/harness"] += 0.1
            indicators.append(f"{sub}/ directory found")

    # Check for Terraform indicators
    tf_files = list(repo.rglob("*.tf"))
    if tf_files:
        count = len(tf_files)
        scores["infrastructure/terraform"] += min(0.5, count * 0.05)
        indicators.append(f"{count} .tf files found")

    # Check for layer directories (layer_1, layer_2, etc.)
    layer_dirs = [d for d in repo.iterdir() if d.is_dir() and d.name.startswith("layer_")]
    if layer_dirs:
        scores["infrastructure/terraform"] += 0.3
        indicators.append(f"{len(layer_dirs)} layer_* directories found")

    # Check for terraform.tfvars or backend configs
    for tf_indicator in ["terraform.tfvars", "backend.tf", "providers.tf", "versions.tf"]:
        matches = list(repo.rglob(tf_indicator))
        if matches:
            scores["infrastructure/terraform"] += 0.1
            indicators.append(f"{tf_indicator} found")

    # Check for Helm indicators
    charts_dir = repo / "charts"
    if charts_dir.exists() and charts_dir.is_dir():
        chart_files = list(charts_dir.rglob("Chart.yaml")) + list(charts_dir.rglob("Chart.yml"))
        if chart_files:
            scores["helm"] += 0.5
            indicators.append(f"{len(chart_files)} Chart.yaml files found in charts/")

    # Check for Chart.yaml at root or in subdirectories
    chart_files = list(repo.rglob("Chart.yaml")) + list(repo.rglob("Chart.yml"))
    if chart_files:
        scores["helm"] += 0.3
        indicators.append(f"{len(chart_files)} Chart.yaml files total")

    # Check for values.yaml (Helm indicator)
    values_files = list(repo.rglob("values.yaml")) + list(repo.rglob("values.yml"))
    if values_files and chart_files:
        scores["helm"] += 0.1
        indicators.append(f"{len(values_files)} values.yaml files found")

    # Check for templates/ with deployment manifests
    template_dirs = list(repo.rglob("templates"))
    for td in template_dirs:
        if td.is_dir():
            deployment_files = list(td.glob("*.yaml")) + list(td.glob("*.yml"))
            if deployment_files:
                scores["helm"] += 0.1
                indicators.append(f"templates/ directory with {len(deployment_files)} manifests")
                break

    # Application indicators (fallback)
    app_indicators = [
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
        "package.json", "requirements.txt", "setup.py", "pom.xml",
        "build.gradle", "Makefile", "go.mod", "Cargo.toml",
    ]
    for ai in app_indicators:
        if (repo / ai).exists():
            scores["application"] += 0.15
            indicators.append(f"{ai} found (application indicator)")

    # Determine the winner
    if not indicators:
        return {
            "type": "unknown",
            "platform": "unknown",
            "confidence": 0.0,
            "indicators": ["No recognizable patterns found"],
        }

    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    if best_score < 0.2:
        return {
            "type": "unknown",
            "platform": "unknown",
            "confidence": best_score,
            "indicators": indicators,
        }

    # Map type to platform
    platform_map = {
        "cicd/harness": "harness",
        "infrastructure/terraform": "terraform",
        "helm": "helm",
        "application": "generic",
    }

    # Split type for the result
    if "/" in best_type:
        repo_type, platform = best_type.split("/", 1)
    else:
        repo_type = best_type
        platform = platform_map.get(best_type, best_type)

    return {
        "type": repo_type,
        "platform": platform,
        "confidence": min(1.0, best_score),
        "indicators": indicators,
    }
