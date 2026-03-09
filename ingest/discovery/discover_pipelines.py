"""
Discover Pipelines

Finds CI/CD pipeline definitions:
- Harness pipeline YAML files
- Template references
- Stage and step structures
- Service and environment bindings
"""

import re
from pathlib import Path
from typing import Optional


def _parse_pipeline_yaml(file_path: Path, repo_path: Path) -> Optional[dict]:
    """
    Parse a pipeline YAML file and extract key information.
    Uses regex parsing to avoid YAML library dependency for basic extraction.
    """
    try:
        content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None

    rel_path = str(file_path.relative_to(repo_path))

    pipeline = {
        "file": rel_path,
        "repo": repo_path.name,
        "name": file_path.parent.name,
        "stages": [],
        "template_refs": [],
        "service_refs": [],
        "infra_refs": [],
        "variables": [],
    }

    # Extract pipeline name/identifier
    id_match = re.search(r'identifier:\s*["\']?(\S+)["\']?', content)
    if id_match:
        pipeline["name"] = id_match.group(1)

    name_match = re.search(r'^name:\s*["\']?([^"\'\n]+)["\']?', content, re.MULTILINE)
    if name_match:
        pipeline["display_name"] = name_match.group(1).strip()

    # Extract stages
    stage_pattern = re.compile(r'-\s*stage:\s*\n\s+(?:name|identifier):\s*["\']?([^"\'\n]+)', re.MULTILINE)
    for match in stage_pattern.finditer(content):
        pipeline["stages"].append(match.group(1).strip())

    # Also look for simpler stage references
    simple_stage = re.compile(r'stage:\s*\n\s+name:\s*["\']?([^"\'\n]+)', re.MULTILINE)
    for match in simple_stage.finditer(content):
        name = match.group(1).strip()
        if name not in pipeline["stages"]:
            pipeline["stages"].append(name)

    # Extract template references
    for match in re.finditer(r'templateRef:\s*["\']?(\S+)["\']?', content):
        ref = match.group(1)
        if ref not in pipeline["template_refs"]:
            pipeline["template_refs"].append(ref)

    # Extract service references
    for match in re.finditer(r'serviceRef:\s*["\']?(\S+)["\']?', content):
        ref = match.group(1)
        if ref not in pipeline["service_refs"]:
            pipeline["service_refs"].append(ref)

    # Extract infrastructure references
    for match in re.finditer(r'infraRef:\s*["\']?(\S+)["\']?', content):
        ref = match.group(1)
        if ref not in pipeline["infra_refs"]:
            pipeline["infra_refs"].append(ref)
    for match in re.finditer(r'infrastructureRef:\s*["\']?(\S+)["\']?', content):
        ref = match.group(1)
        if ref not in pipeline["infra_refs"]:
            pipeline["infra_refs"].append(ref)

    # Extract variables
    var_pattern = re.compile(r'-\s*name:\s*["\']?(\w+)["\']?\s*\n\s+type:\s*["\']?(\w+)', re.MULTILINE)
    for match in var_pattern.finditer(content):
        pipeline["variables"].append({
            "name": match.group(1),
            "type": match.group(2),
        })

    return pipeline


def discover_pipelines(repo_paths: list[str]) -> list[dict]:
    """
    Discover pipelines across multiple repositories.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        List of pipeline dicts with keys:
            name: str — pipeline identifier
            file: str — relative path to pipeline file
            repo: str — repo name
            stages: list[str] — stage names
            template_refs: list[str] — template references
            service_refs: list[str] — service references
            infra_refs: list[str] — infra references
            variables: list[dict] — input variables
    """
    pipelines = []

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        for yaml_file in repo_path.rglob("pipeline.yaml"):
            parsed = _parse_pipeline_yaml(yaml_file, repo_path)
            if parsed:
                pipelines.append(parsed)

        for yaml_file in repo_path.rglob("pipeline.yml"):
            parsed = _parse_pipeline_yaml(yaml_file, repo_path)
            if parsed:
                pipelines.append(parsed)

    return sorted(pipelines, key=lambda p: p.get("name", ""))
