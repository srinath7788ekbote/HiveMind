"""
Get Pipeline — Deep-parse a pipeline file and return structured details

Extracts stages, steps, templates, services, environments, variables,
and infrastructure references from a Harness pipeline YAML.

Usage:
    python tools/get_pipeline.py --client dfin --name "deploy-audit-service"
    python tools/get_pipeline.py --client dfin --file "pipelines/deploy_audit.yaml" --repo dfin-harness-pipelines
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_pipeline(client: str, name: str = None, file: str = None, repo: str = None, branch: str = None) -> dict:
    """
    Retrieve and deeply parse a pipeline by name or file path.

    Args:
        client: Client name.
        name: Pipeline name (will search across repos).
        file: Specific file path within a repo.
        repo: Repository name.
        branch: Branch to read from (currently reads working tree).

    Returns:
        dict with pipeline details.
    """
    if file and repo:
        return _parse_pipeline_by_file(client, repo, file)
    elif name:
        return _find_and_parse_pipeline(client, name, repo)
    else:
        return {"error": "Provide --name or --file and --repo"}


def _find_and_parse_pipeline(client: str, name: str, repo_filter: str = None) -> dict:
    """Find a pipeline by name across repos."""
    config = _load_config(client)
    if not config:
        return {"error": "Client config not found"}

    for repo_cfg in config.get("repos", []):
        repo_name = repo_cfg.get("name", "")
        if repo_filter and repo_name != repo_filter:
            continue

        repo_path = Path(repo_cfg.get("path", ""))
        if not repo_path.exists():
            continue

        # Search for pipeline files
        for yaml_file in repo_path.rglob("*.yaml"):
            rel = str(yaml_file.relative_to(repo_path)).replace("\\", "/")
            if name.lower() in rel.lower():
                content = yaml_file.read_text(encoding="utf-8", errors="replace")
                if "pipeline:" in content or "stage:" in content:
                    return _parse_pipeline_content(content, rel, repo_name)

        for yml_file in repo_path.rglob("*.yml"):
            rel = str(yml_file.relative_to(repo_path)).replace("\\", "/")
            if name.lower() in rel.lower():
                content = yml_file.read_text(encoding="utf-8", errors="replace")
                if "pipeline:" in content or "stage:" in content:
                    return _parse_pipeline_content(content, rel, repo_name)

    return {"error": f"Pipeline '{name}' not found"}


def _parse_pipeline_by_file(client: str, repo_name: str, file_path: str) -> dict:
    """Parse a specific pipeline file."""
    config = _load_config(client)
    if not config:
        return {"error": "Client config not found"}

    for repo_cfg in config.get("repos", []):
        if repo_cfg.get("name", "") != repo_name:
            continue

        full_path = Path(repo_cfg.get("path", "")) / file_path
        if not full_path.exists():
            return {"error": f"File not found: {file_path} in {repo_name}"}

        content = full_path.read_text(encoding="utf-8", errors="replace")
        return _parse_pipeline_content(content, file_path, repo_name)

    return {"error": f"Repo '{repo_name}' not found in config"}


def _parse_pipeline_content(content: str, file_path: str, repo: str) -> dict:
    """Deep-parse pipeline YAML content."""
    result = {
        "file": file_path,
        "repo": repo,
        "name": "",
        "identifier": "",
        "stages": [],
        "templates_used": [],
        "services_referenced": [],
        "environments_referenced": [],
        "infrastructure_refs": [],
        "variables": [],
        "connectors": [],
        "triggers": [],
        "approval_stages": [],
        "notification_rules": [],
    }

    # Extract pipeline name and identifier
    name_match = re.search(r'name:\s*(.+)', content)
    if name_match:
        result["name"] = name_match.group(1).strip().strip('"')

    id_match = re.search(r'identifier:\s*(\S+)', content)
    if id_match:
        result["identifier"] = id_match.group(1).strip()

    # Extract stages
    stage_blocks = re.finditer(
        r'-\s*stage:\s*\n((?:\s{2,}.+\n)*)',
        content,
    )
    for block in stage_blocks:
        stage_content = block.group(1)
        stage = {"name": "", "type": "", "spec": {}}

        stage_name = re.search(r'name:\s*(.+)', stage_content)
        if stage_name:
            stage["name"] = stage_name.group(1).strip().strip('"')

        stage_type = re.search(r'type:\s*(\S+)', stage_content)
        if stage_type:
            stage["type"] = stage_type.group(1).strip()

        # Check for approval
        if stage["type"].lower() in ("approval", "harnessapproval", "jiraapproval"):
            result["approval_stages"].append(stage["name"])

        result["stages"].append(stage)

    # Extract template references
    for match in re.finditer(r'templateRef:\s*(\S+)', content):
        ref = match.group(1).strip()
        if ref not in result["templates_used"]:
            result["templates_used"].append(ref)

    # Extract service references
    for match in re.finditer(r'serviceRef:\s*(\S+)', content):
        ref = match.group(1).strip()
        if ref and ref != "<+input>" and ref not in result["services_referenced"]:
            result["services_referenced"].append(ref)

    # Extract environment references
    for match in re.finditer(r'environmentRef:\s*(\S+)', content):
        ref = match.group(1).strip()
        if ref and ref != "<+input>" and ref not in result["environments_referenced"]:
            result["environments_referenced"].append(ref)

    # Extract infrastructure references
    for match in re.finditer(r'infrastructureRef:\s*(\S+)', content):
        ref = match.group(1).strip()
        if ref not in result["infrastructure_refs"]:
            result["infrastructure_refs"].append(ref)

    for match in re.finditer(r'infrastructureDefinition:\s*\n(?:\s+\w+:.+\n)*', content):
        block = match.group(0)
        infra_type = re.search(r'type:\s*(\S+)', block)
        if infra_type:
            ref = f"infra_type:{infra_type.group(1)}"
            if ref not in result["infrastructure_refs"]:
                result["infrastructure_refs"].append(ref)

    # Extract variables
    for match in re.finditer(r'-\s*name:\s*(\S+)\s*\n\s*(?:type:\s*(\S+))?\s*\n?\s*(?:value:\s*(.+))?', content):
        var = {
            "name": match.group(1).strip(),
            "type": match.group(2).strip() if match.group(2) else "String",
            "value": match.group(3).strip() if match.group(3) else "",
        }
        result["variables"].append(var)

    # Extract connectors
    for match in re.finditer(r'connectorRef:\s*(\S+)', content):
        ref = match.group(1).strip()
        if ref and ref not in result["connectors"]:
            result["connectors"].append(ref)

    # Extract triggers
    trigger_match = re.search(r'trigger:', content)
    if trigger_match:
        trigger_type = re.search(r'type:\s*(\S+)', content[trigger_match.start():])
        if trigger_type:
            result["triggers"].append(trigger_type.group(1))

    return result


def _load_config(client: str) -> dict:
    """Load client repos config."""
    config_path = PROJECT_ROOT / "clients" / client / "repos.yaml"
    if not config_path.exists():
        return {}

    content = config_path.read_text(encoding="utf-8")

    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass

    config = {"repos": []}
    current_repo = None

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith("- name:"):
            current_repo = {"name": stripped.split(":", 1)[1].strip().strip('"\"')}
            config["repos"].append(current_repo)
        elif current_repo and ":" in stripped:
            key, val = stripped.split(":", 1)
            key = key.strip()
            val = val.strip().strip('"\"')
            if key == "path":
                current_repo["path"] = val
            elif key == "type":
                current_repo["type"] = val

    return config


def main():
    parser = argparse.ArgumentParser(description="HiveMind Get Pipeline — deep parse a pipeline")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--name", default=None, help="Pipeline name to search for")
    parser.add_argument("--file", default=None, help="Specific file path within repo")
    parser.add_argument("--repo", default=None, help="Repository name")
    parser.add_argument("--branch", default=None, help="Branch")
    args = parser.parse_args()

    result = get_pipeline(
        client=args.client,
        name=args.name,
        file=args.file,
        repo=args.repo,
        branch=args.branch,
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        return

    print(f"Pipeline: {result['name']} ({result['identifier']})")
    print(f"File:     {result['repo']}/{result['file']}")

    if result["stages"]:
        print(f"\nStages ({len(result['stages'])}):")
        for s in result["stages"]:
            print(f"  [{s['type']}] {s['name']}")

    if result["templates_used"]:
        print(f"\nTemplates: {', '.join(result['templates_used'])}")

    if result["services_referenced"]:
        print(f"Services:  {', '.join(result['services_referenced'])}")

    if result["environments_referenced"]:
        print(f"Environments: {', '.join(result['environments_referenced'])}")

    if result["infrastructure_refs"]:
        print(f"Infra refs: {', '.join(result['infrastructure_refs'])}")

    if result["variables"]:
        print(f"\nVariables ({len(result['variables'])}):")
        for v in result["variables"]:
            val_str = f" = {v['value']}" if v["value"] else ""
            print(f"  {v['name']} ({v['type']}){val_str}")

    if result["connectors"]:
        print(f"\nConnectors: {', '.join(result['connectors'])}")

    if result["approval_stages"]:
        print(f"\nApproval gates: {', '.join(result['approval_stages'])}")


if __name__ == "__main__":
    main()

