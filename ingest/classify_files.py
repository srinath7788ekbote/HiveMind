"""
Classify Files

Classifies individual files by their type based on path patterns and content.
Used during ingestion to determine how to parse and index each file.

Supported classifications:
    pipeline, helm_chart, helm_values, terraform, harness_svc,
    harness_env, harness_override, template, k8s_manifest,
    dockerfile, readme, skip, unknown
"""

import os
import re
from pathlib import Path
from typing import Optional


# File extensions to skip entirely
SKIP_EXTENSIONS = {
    '.jar', '.class', '.war', '.ear',
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
    '.zip', '.tar', '.gz', '.bz2', '.7z', '.rar',
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.pyc', '.pyo', '.o', '.obj',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp3', '.mp4', '.avi', '.mov', '.wav',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx',
    '.lock', '.sum',
}

# Known skip file names
SKIP_FILENAMES = {
    '.DS_Store', 'Thumbs.db', '.gitkeep',
    'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
}


def classify_file(file_path: str, repo_root: str = "") -> str:
    """
    Classify a file based on its path and name.

    Args:
        file_path: Absolute or relative path to the file.
        repo_root: Root of the repository (for relative path calculation).

    Returns:
        Classification string: pipeline, helm_chart, helm_values,
        terraform, harness_svc, harness_env, harness_override,
        template, k8s_manifest, dockerfile, readme, skip, unknown
    """
    p = Path(file_path)
    name = p.name
    suffix = p.suffix.lower()
    parts = p.parts

    # Normalize parts to lowercase for matching
    parts_lower = [part.lower() for part in parts]

    # Skip binary and irrelevant files
    if suffix in SKIP_EXTENSIONS:
        return "skip"
    if name in SKIP_FILENAMES:
        return "skip"

    # Pipeline YAML (pipeline.yaml in CI/CD directories)
    if name.lower() in ('pipeline.yaml', 'pipeline.yml'):
        return "pipeline"

    # Helm Chart.yaml
    if name.lower() in ('chart.yaml', 'chart.yml'):
        if 'charts' in parts_lower:
            return "helm_chart"
        return "helm_chart"

    # Helm values.yaml
    if name.lower() in ('values.yaml', 'values.yml'):
        if 'charts' in parts_lower:
            return "helm_values"
        # Could also be Helm values even without charts/ parent
        return "helm_values"

    # Terraform files
    if suffix == '.tf':
        return "terraform"
    if suffix == '.tfvars':
        return "terraform"

    # Harness service definitions
    if 'services' in parts_lower and suffix in ('.yaml', '.yml'):
        if '.harness' in parts_lower:
            return "harness_svc"
        return "harness_svc"

    # Harness environment definitions
    if 'environments' in parts_lower and suffix in ('.yaml', '.yml'):
        if '.harness' in parts_lower:
            return "harness_env"
        return "harness_env"

    # Harness overrides
    if 'overrides' in parts_lower and suffix in ('.yaml', '.yml'):
        return "harness_override"

    # Templates directory (Helm or other)
    if 'templates' in parts_lower and suffix in ('.yaml', '.yml'):
        return "template"

    # Kubernetes manifests (YAML files with kind: in content)
    if suffix in ('.yaml', '.yml') and 'templates' not in parts_lower:
        # We classify these as unknown YAML — content-based classification
        # would need file reading which we avoid here for performance
        return "unknown"

    # Dockerfile
    if name.lower() in ('dockerfile', 'dockerfile.prod', 'dockerfile.dev'):
        return "dockerfile"
    if name.lower().startswith('dockerfile'):
        return "dockerfile"

    # README
    if name.lower().startswith('readme'):
        return "readme"

    return "unknown"


def classify_directory(dir_path: str, repo_root: str = "") -> list[dict]:
    """
    Classify all files in a directory tree.

    Args:
        dir_path: Absolute path to directory.
        repo_root: Root of the repository.

    Returns:
        List of dicts with keys: file, classification, relative_path
    """
    results = []
    root = Path(dir_path)
    repo = Path(repo_root) if repo_root else root

    if not root.exists():
        return results

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        classification = classify_file(str(file_path), str(repo))
        try:
            rel = str(file_path.relative_to(repo))
        except ValueError:
            rel = str(file_path)

        results.append({
            "file": str(file_path),
            "relative_path": rel,
            "classification": classification,
        })

    return results


def classify_file_list(file_paths: list[str], repo_root: str = "") -> list[dict]:
    """
    Classify an explicit list of files (fast path for incremental sync).

    Args:
        file_paths: List of absolute file paths to classify.
        repo_root: Root of the repository.

    Returns:
        List of dicts with keys: file, classification, relative_path
    """
    results = []
    repo = Path(repo_root) if repo_root else None

    for fp in file_paths:
        file_path = Path(fp)
        if not file_path.is_file():
            continue

        classification = classify_file(str(file_path), repo_root)
        try:
            rel = str(file_path.relative_to(repo)) if repo else str(file_path)
        except ValueError:
            rel = str(file_path)

        results.append({
            "file": str(file_path),
            "relative_path": rel,
            "classification": classification,
        })

    return results
