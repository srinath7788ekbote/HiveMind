"""
Discover Infrastructure Layers

Finds Terraform layer directories and orders them by dependency.
Detects layer numbering patterns (layer_1, layer_2, etc.)
and parses inter-layer dependencies.
"""

import re
from pathlib import Path
from typing import Optional


def _extract_layer_number(name: str) -> float:
    """
    Extract numeric layer order from directory name.
    Supports: layer_2, layer_3.5, layer_10, etc.
    """
    match = re.search(r'(\d+(?:\.\d+)?)', name)
    if match:
        return float(match.group(1))
    return 999.0  # Unknown layers sort last


def _parse_layer(layer_dir: Path, repo_path: Path) -> dict:
    """Parse a single Terraform layer directory."""
    tf_files = list(layer_dir.glob("*.tf"))

    resources = []
    data_sources = []
    modules = []
    outputs = []

    for tf_file in tf_files:
        try:
            content = tf_file.read_text(encoding='utf-8')

            # Resources
            for match in re.finditer(r'resource\s+"(\w+)"\s+"(\w+)"', content):
                resources.append({
                    "type": match.group(1),
                    "name": match.group(2),
                    "file": str(tf_file.relative_to(repo_path)),
                })

            # Data sources
            for match in re.finditer(r'data\s+"(\w+)"\s+"(\w+)"', content):
                data_sources.append({
                    "type": match.group(1),
                    "name": match.group(2),
                    "file": str(tf_file.relative_to(repo_path)),
                })

            # Modules
            for match in re.finditer(r'module\s+"(\w+)"', content):
                modules.append({
                    "name": match.group(1),
                    "file": str(tf_file.relative_to(repo_path)),
                })

            # Outputs
            for match in re.finditer(r'output\s+"(\w+)"', content):
                outputs.append({
                    "name": match.group(1),
                    "file": str(tf_file.relative_to(repo_path)),
                })
        except (OSError, UnicodeDecodeError):
            continue

    return {
        "name": layer_dir.name,
        "order": _extract_layer_number(layer_dir.name),
        "path": str(layer_dir.relative_to(repo_path)),
        "tf_files": [str(f.relative_to(repo_path)) for f in tf_files],
        "resources": resources,
        "data_sources": data_sources,
        "modules": modules,
        "outputs": outputs,
        "resource_count": len(resources),
        "repo": repo_path.name,
    }


def discover_infra_layers(repo_paths: list[str]) -> list[dict]:
    """
    Discover Terraform infrastructure layers across repositories.
    Returns layers sorted by their numeric order.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        Sorted list of layer dicts with keys:
            name: str — directory name (e.g., "layer_2")
            order: float — numeric order for sorting
            path: str — relative path
            tf_files: list[str] — .tf file paths
            resources: list[dict] — resource definitions
            data_sources: list[dict] — data source definitions
            modules: list[dict] — module definitions
            resource_count: int
            repo: str
    """
    layers = []

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        # Look for layer_* directories
        for item in repo_path.iterdir():
            if item.is_dir() and item.name.startswith("layer_"):
                tf_files = list(item.glob("*.tf"))
                if tf_files:
                    layer = _parse_layer(item, repo_path)
                    layers.append(layer)

        # Also check for nested layer directories
        for item in repo_path.rglob("layer_*"):
            if item.is_dir() and item.parent == repo_path:
                continue  # Already handled above
            if item.is_dir():
                tf_files = list(item.glob("*.tf"))
                if tf_files:
                    layer = _parse_layer(item, repo_path)
                    if not any(l["name"] == layer["name"] for l in layers):
                        layers.append(layer)

    return sorted(layers, key=lambda l: l["order"])
