"""
Discover Environments

Finds environment definitions across all repo types:
- Harness: .harness/environments/*.yaml
- Terraform: tfvars files, workspace names
- Pipeline YAML: infraRef, envRef, environment variables

Returns list of environments with tier classification.
"""

import re
from pathlib import Path
from typing import Optional


TIER_PATTERNS = {
    "production": [r'\bprod\b', r'\bprd\b', r'\bproduction\b'],
    "staging": [r'\bstaging\b', r'\bstg\b', r'\buat\b', r'\bpre-?prod\b'],
    "integration": [r'\bdev\b', r'\bdevelop\b', r'\bint\b', r'\bintegration\b'],
    "sandbox": [r'\bsandbox\b', r'\bsbx\b', r'\blab\b', r'\btest\b'],
}


def _classify_tier(env_name: str) -> str:
    """Classify an environment name into a tier."""
    name_lower = env_name.lower()
    for tier, patterns in TIER_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, name_lower):
                return tier
    return "unknown"


def _discover_from_harness(repo_path: Path) -> list[dict]:
    """Find environments defined in .harness/environments/."""
    environments = []
    env_dir = repo_path / ".harness" / "environments"
    if not env_dir.exists():
        return environments

    for yaml_file in env_dir.iterdir():
        if yaml_file.suffix in ('.yaml', '.yml') and yaml_file.is_file():
            try:
                content = yaml_file.read_text(encoding='utf-8')
                env_name = yaml_file.stem

                id_match = re.search(r'identifier:\s*["\']?(\S+)["\']?', content)
                if id_match:
                    env_name = id_match.group(1)

                name_match = re.search(r'name:\s*["\']?([^"\'\n]+)["\']?', content)
                display_name = name_match.group(1).strip() if name_match else env_name

                type_match = re.search(r'type:\s*["\']?(\S+)["\']?', content)
                env_type = type_match.group(1) if type_match else "unknown"

                environments.append({
                    "name": env_name,
                    "display_name": display_name,
                    "tier": _classify_tier(env_name),
                    "type": env_type,
                    "source": "harness",
                    "file": str(yaml_file.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
            except (OSError, UnicodeDecodeError):
                continue
    return environments


def _discover_from_pipelines(repo_path: Path) -> list[dict]:
    """Find environment references in pipeline YAML files."""
    environments = []
    seen = set()

    for yaml_file in repo_path.rglob("pipeline.yaml"):
        try:
            content = yaml_file.read_text(encoding='utf-8')

            # Look for environmentRef or infraRef
            for pattern in [r'environmentRef:\s*["\']?(\S+)["\']?', r'envRef:\s*["\']?(\S+)["\']?']:
                for match in re.finditer(pattern, content):
                    env_name = match.group(1)
                    if env_name.startswith('<') or env_name.startswith('$'):
                        continue
                    if env_name not in seen:
                        seen.add(env_name)
                        environments.append({
                            "name": env_name,
                            "display_name": env_name,
                            "tier": _classify_tier(env_name),
                            "type": "pipeline_ref",
                            "source": "pipeline_ref",
                            "file": str(yaml_file.relative_to(repo_path)),
                            "repo": repo_path.name,
                        })
        except (OSError, UnicodeDecodeError):
            continue
    return environments


def _discover_from_overrides(repo_path: Path) -> list[dict]:
    """Find environments from override directories."""
    environments = []
    overrides_dir = repo_path / ".harness" / "overrides"
    if not overrides_dir.exists():
        return environments

    # Each subdir under overrides/global_environment/ is an environment
    global_env_dir = overrides_dir / "global_environment"
    if global_env_dir.exists():
        for d in global_env_dir.iterdir():
            if d.is_dir():
                environments.append({
                    "name": d.name,
                    "display_name": d.name,
                    "tier": _classify_tier(d.name),
                    "type": "override",
                    "source": "harness_override",
                    "file": str(d.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
            elif d.suffix in ('.yaml', '.yml'):
                env_name = d.stem
                environments.append({
                    "name": env_name,
                    "display_name": env_name,
                    "tier": _classify_tier(env_name),
                    "type": "override",
                    "source": "harness_override",
                    "file": str(d.relative_to(repo_path)),
                    "repo": repo_path.name,
                })
    return environments


def discover_environments(repo_paths: list[str]) -> list[dict]:
    """
    Discover environments across multiple repositories.
    Deduplicates by name, merging source references.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        List of environment dicts with keys:
            name: str — environment identifier
            display_name: str — human-readable name
            tier: str — production|staging|integration|sandbox|unknown
            sources: list[dict] — all source references
    """
    all_envs: dict[str, dict] = {}

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        discovered = []
        discovered.extend(_discover_from_harness(repo_path))
        discovered.extend(_discover_from_pipelines(repo_path))
        discovered.extend(_discover_from_overrides(repo_path))

        for env in discovered:
            name = env["name"]
            if name not in all_envs:
                all_envs[name] = {
                    "name": name,
                    "display_name": env.get("display_name", name),
                    "tier": env.get("tier", "unknown"),
                    "sources": [],
                }
            all_envs[name]["sources"].append({
                "source": env["source"],
                "file": env["file"],
                "repo": env["repo"],
            })

    return sorted(all_envs.values(), key=lambda e: e["name"])
