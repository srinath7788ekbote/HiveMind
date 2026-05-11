"""
Extract Relationships

Parses files to extract edges for the knowledge graph.
Edges represent relationships between entities:
    CALLS_TEMPLATE, USES_SERVICE, TARGETS_INFRA,
    MOUNTS_SECRET, CREATES_KV_SECRET, CREATES_K8S_SECRET,
    READS_KV_SECRET, DEPENDS_ON, OUTPUTS_TO, etc.
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Optional


# Edge types
CALLS_TEMPLATE = "CALLS_TEMPLATE"
USES_SERVICE = "USES_SERVICE"
TARGETS_INFRA = "TARGETS_INFRA"
MOUNTS_SECRET = "MOUNTS_SECRET"
CREATES_KV_SECRET = "CREATES_KV_SECRET"
CREATES_K8S_SECRET = "CREATES_K8S_SECRET"
READS_KV_SECRET = "READS_KV_SECRET"
DEPENDS_ON = "DEPENDS_ON"
OUTPUTS_TO = "OUTPUTS_TO"
REFERENCES = "REFERENCES"
DEFINES_CONFIG = "DEFINES_CONFIG"
OVERRIDES_FOR_ENV = "OVERRIDES_FOR_ENV"
CONNECTS_TO = "CONNECTS_TO"


# Known Spring profile names for settings overlay detection
_SPRING_PROFILES = frozenset({
    "prod", "proddr", "dev", "qa", "perf", "demo", "preprod", "predemo",
})

# Endpoint patterns — compiled once
_ENDPOINT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r'[\w.-]+\.servicebus\.windows\.net'), "service_bus"),
    (re.compile(r'[\w.-]+\.database\.azure\.com'), "database"),
    (re.compile(r'[\w.-]+\.redis\.cache\.windows\.net'), "redis"),
    (re.compile(r'[\w.-]+\.blob\.core\.windows\.net'), "storage"),
    (re.compile(r'https?://[\w.-]*salesforce\.com[\w/.-]*'), "salesforce"),
    (re.compile(r'https?://login[\w.-]*\.dfinsolutions\.com[\w/.-]*'), "auth0"),
    (re.compile(r'[\w.-]+\.auth0app\.com[\w/.-]*'), "auth0"),
    (re.compile(r'[\w.-]+\.azurewebsites\.net'), "app_service"),
    (re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(:\d+)?'), "internal_endpoint"),
]

# YAML key fragments that indicate interesting config properties
_CONFIG_KEY_INDICATORS = {
    "endpoint", "url", "host", "namespace", "connection-string",
    "domain", "base-url", "access-token-uri",
}


def _extract_from_pipeline(file_path: Path, repo_root: Path) -> list[dict]:
    """Extract relationships from a pipeline YAML file."""
    edges = []
    try:
        content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return edges

    rel_path = str(file_path.relative_to(repo_root))
    source_id = rel_path

    # templateRef → CALLS_TEMPLATE
    for match in re.finditer(r'templateRef:\s*["\']?(\S+)["\']?', content):
        edges.append({
            "source": source_id,
            "target": match.group(1),
            "edge_type": CALLS_TEMPLATE,
            "file": rel_path,
            "repo": repo_root.name,
        })

    # serviceRef → USES_SERVICE
    for match in re.finditer(r'serviceRef:\s*["\']?(\S+)["\']?', content):
        edges.append({
            "source": source_id,
            "target": match.group(1),
            "edge_type": USES_SERVICE,
            "file": rel_path,
            "repo": repo_root.name,
        })

    # infraRef → TARGETS_INFRA
    for match in re.finditer(r'infraRef:\s*["\']?(\S+)["\']?', content):
        edges.append({
            "source": source_id,
            "target": match.group(1),
            "edge_type": TARGETS_INFRA,
            "file": rel_path,
            "repo": repo_root.name,
        })

    return edges


def _extract_from_terraform(file_path: Path, repo_root: Path) -> list[dict]:
    """Extract relationships from a Terraform file."""
    edges = []
    try:
        content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return edges

    rel_path = str(file_path.relative_to(repo_root))

    # azurerm_key_vault_secret → CREATES_KV_SECRET
    for match in re.finditer(
        r'resource\s+"azurerm_key_vault_secret"\s+"(\w+)"\s*\{(.*?)\n\}',
        content,
        re.DOTALL,
    ):
        resource_name = match.group(1)
        block = match.group(2)
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        secret_name = name_match.group(1) if name_match else resource_name

        edges.append({
            "source": rel_path,
            "target": f"kv_secret:{secret_name}",
            "edge_type": CREATES_KV_SECRET,
            "file": rel_path,
            "repo": repo_root.name,
            "resource": f"azurerm_key_vault_secret.{resource_name}",
        })

    # kubernetes_secret → CREATES_K8S_SECRET
    for match in re.finditer(
        r'resource\s+"kubernetes_secret"\s+"(\w+)"\s*\{(.*?)\n\}',
        content,
        re.DOTALL,
    ):
        resource_name = match.group(1)
        block = match.group(2)
        meta_match = re.search(
            r'metadata\s*\{[^}]*name\s*=\s*"([^"]+)"',
            block,
            re.DOTALL,
        )
        secret_name = meta_match.group(1) if meta_match else resource_name

        edges.append({
            "source": rel_path,
            "target": f"k8s_secret:{secret_name}",
            "edge_type": CREATES_K8S_SECRET,
            "file": rel_path,
            "repo": repo_root.name,
            "resource": f"kubernetes_secret.{resource_name}",
        })

        # Check if this K8s secret reads from a KV secret
        kv_refs = re.findall(
            r'data\.azurerm_key_vault_secret\.(\w+)\.value',
            block,
        )
        for kv_ref in kv_refs:
            edges.append({
                "source": f"k8s_secret:{secret_name}",
                "target": f"kv_data:{kv_ref}",
                "edge_type": READS_KV_SECRET,
                "file": rel_path,
                "repo": repo_root.name,
            })

    # Data sources for KV secrets
    for match in re.finditer(
        r'data\s+"azurerm_key_vault_secret"\s+"(\w+)"\s*\{(.*?)\n\}',
        content,
        re.DOTALL,
    ):
        data_name = match.group(1)
        block = match.group(2)
        name_match = re.search(r'name\s*=\s*"([^"]+)"', block)
        secret_name = name_match.group(1) if name_match else data_name

        edges.append({
            "source": f"kv_data:{data_name}",
            "target": f"kv_secret:{secret_name}",
            "edge_type": READS_KV_SECRET,
            "file": rel_path,
            "repo": repo_root.name,
        })

    # depends_on references
    for match in re.finditer(r'depends_on\s*=\s*\[(.*?)\]', content, re.DOTALL):
        deps_block = match.group(1)
        for dep_match in re.finditer(r'(\w+\.\w+)', deps_block):
            edges.append({
                "source": rel_path,
                "target": dep_match.group(1),
                "edge_type": DEPENDS_ON,
                "file": rel_path,
                "repo": repo_root.name,
            })

    return edges


def _extract_from_helm_template(file_path: Path, repo_root: Path) -> list[dict]:
    """Extract relationships from Helm template files."""
    edges = []
    try:
        content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return edges

    rel_path = str(file_path.relative_to(repo_root))

    # secretKeyRef → MOUNTS_SECRET
    pattern = re.compile(
        r'secretKeyRef:\s*\n\s+name:\s*["\']?([^"\'\n]+)["\']?',
        re.MULTILINE,
    )
    for match in pattern.finditer(content):
        secret_name = match.group(1).strip()
        edges.append({
            "source": rel_path,
            "target": f"k8s_secret:{secret_name}",
            "edge_type": MOUNTS_SECRET,
            "file": rel_path,
            "repo": repo_root.name,
        })

    return edges


def _flatten_yaml(data, prefix=""):
    """Recursively flatten a YAML dict into (dotted_key, value) pairs."""
    items = []
    if isinstance(data, dict):
        for k, v in data.items():
            new_key = f"{prefix}.{k}" if prefix else str(k)
            items.extend(_flatten_yaml(v, new_key))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            new_key = f"{prefix}[{i}]"
            items.extend(_flatten_yaml(v, new_key))
    else:
        items.append((prefix, data))
    return items


def _detect_endpoint(value: str) -> Optional[tuple[str, str]]:
    """Check if a string value matches a known endpoint pattern.

    Returns (endpoint_value, endpoint_type) or None.
    """
    for pattern, ep_type in _ENDPOINT_PATTERNS:
        m = pattern.search(value)
        if m:
            return (m.group(0), ep_type)
    return None


def _parse_settings_filename(file_path: Path) -> tuple[Optional[str], Optional[str]]:
    """Parse a settings filename into (service_name, profile).

    Examples:
        client-service-prod.yaml → ("client-service", "prod")
        client-service.yaml → ("client-service", None)
        application-prod.yaml → ("application", "prod")
        application.yaml → ("application", None)
    """
    stem = file_path.stem
    parent_name = file_path.parent.name

    # If it's an application[-profile].yaml at any level
    if stem.startswith("application"):
        rest = stem[len("application"):]
        if rest == "":
            return ("application", None)
        if rest.startswith("-"):
            profile = rest[1:]
            if profile in _SPRING_PROFILES:
                return ("application", profile)
        return ("application", None)

    # Service-named files: {parent_name}[-profile].yaml
    if parent_name and stem.startswith(parent_name):
        rest = stem[len(parent_name):]
        if rest == "":
            return (parent_name, None)
        if rest.startswith("-"):
            profile = rest[1:]
            if profile in _SPRING_PROFILES:
                return (parent_name, profile)
        return (parent_name, None)

    return (None, None)


def _extract_from_settings(file_path: Path, repo_root: Path) -> list[dict]:
    """Extract relationships from a Spring Cloud Config settings file.

    Parses YAML property files to find:
    - External endpoints (service bus, database, redis, etc.)
    - Environment overlay relationships (prod → proddr)
    - Config property definitions for critical paths

    Args:
        file_path: Absolute path to the settings YAML file.
        repo_root: Absolute path to the settings repo root.

    Returns:
        List of edge dicts.
    """
    edges = []
    try:
        content = file_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return edges

    if not content.strip():
        return edges

    # Parse YAML — handle Spring placeholders like ${VAR} gracefully
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.allow_duplicate_keys = True
        data = yaml.load(content)
    except Exception:
        return edges

    if not isinstance(data, dict):
        return edges

    rel_path = str(file_path.relative_to(repo_root))
    repo_name = repo_root.name
    source_id = f"config:{rel_path}"

    service_name, profile = _parse_settings_filename(file_path)

    # Create DEFINES_CONFIG edge from file to service
    if service_name and service_name != "application":
        edges.append({
            "source": source_id,
            "target": service_name,
            "edge_type": DEFINES_CONFIG,
            "file": rel_path,
            "repo": repo_name,
            "service": service_name,
            "profile": profile or "default",
        })

    # Detect overlay → base relationships
    if profile:
        # This overlay file overrides the base file
        if service_name == "application":
            base_file = file_path.parent / "application.yaml"
        else:
            base_file = file_path.parent / f"{service_name}.yaml"

        if base_file.exists():
            base_rel = str(base_file.relative_to(repo_root))
            edges.append({
                "source": source_id,
                "target": f"config:{base_rel}",
                "edge_type": OVERRIDES_FOR_ENV,
                "file": rel_path,
                "repo": repo_name,
                "profile": profile,
            })

    # Flatten YAML and scan for endpoints + config properties
    flat = _flatten_yaml(data)
    for key_path, value in flat:
        if not isinstance(value, str):
            # Also check numeric values formatted as IP:port
            if value is not None:
                value = str(value)
            else:
                continue

        # Check for endpoint patterns
        ep = _detect_endpoint(value)
        if ep:
            ep_value, ep_type = ep
            edges.append({
                "source": source_id,
                "target": f"endpoint:{ep_value}",
                "edge_type": CONNECTS_TO,
                "file": rel_path,
                "repo": repo_name,
                "yaml_key_path": key_path,
                "endpoint_type": ep_type,
            })

        # Check if key path indicates a config property worth indexing
        key_lower = key_path.lower()
        if any(indicator in key_lower for indicator in _CONFIG_KEY_INDICATORS):
            edges.append({
                "source": source_id,
                "target": f"config_prop:{key_path}",
                "edge_type": DEFINES_CONFIG,
                "file": rel_path,
                "repo": repo_name,
                "yaml_key_path": key_path,
                "value": value,
            })

    return edges


def extract_relationships(
    repo_path: str,
    file_classifications: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Extract all relationships from a repository.

    Args:
        repo_path: Absolute path to repository root.
        file_classifications: Optional pre-computed classification list.
                             If None, will scan the repo.

    Returns:
        List of edge dicts with keys:
            source: str — source entity ID
            target: str — target entity ID
            edge_type: str — relationship type
            file: str — source file relative path
            repo: str — repository name
    """
    repo = Path(repo_path)
    if not repo.exists():
        return []

    edges = []

    # When file_classifications is provided, only process those specific files
    # instead of scanning the entire repo tree
    if file_classifications:
        for clf in file_classifications:
            f = Path(clf["file"])
            if not f.exists():
                continue
            cls = clf.get("classification", "")
            if cls == "pipeline" or f.name in ("pipeline.yaml", "pipeline.yml"):
                edges.extend(_extract_from_pipeline(f, repo))
            elif cls == "terraform" or f.suffix == ".tf":
                edges.extend(_extract_from_terraform(f, repo))
            elif cls in ("helm_chart", "helm_values", "template") or "templates" in f.parts:
                if f.suffix in (".yaml", ".yml"):
                    edges.extend(_extract_from_helm_template(f, repo))
            elif cls == "config":
                edges.extend(_extract_from_settings(f, repo))
        return edges

    # Full repo scan (no file list provided)

    # Process pipeline files
    for f in repo.rglob("pipeline.yaml"):
        edges.extend(_extract_from_pipeline(f, repo))
    for f in repo.rglob("pipeline.yml"):
        edges.extend(_extract_from_pipeline(f, repo))

    # Process Terraform files
    for f in repo.rglob("*.tf"):
        edges.extend(_extract_from_terraform(f, repo))

    # Process Helm templates
    templates_dirs = list(repo.rglob("templates"))
    for td in templates_dirs:
        if td.is_dir():
            for f in td.rglob("*.yaml"):
                edges.extend(_extract_from_helm_template(f, repo))
            for f in td.rglob("*.yml"):
                edges.extend(_extract_from_helm_template(f, repo))

    # Process Spring Cloud Config settings files
    # Scan for YAML files that match settings naming conventions
    for f in repo.rglob("*.yaml"):
        if "templates" in f.parts or f.name in ("Chart.yaml", "values.yaml"):
            continue
        svc_name, _ = _parse_settings_filename(f)
        if svc_name is not None:
            edges.extend(_extract_from_settings(f, repo))
    for f in repo.rglob("*.yml"):
        if "templates" in f.parts or f.name in ("Chart.yml", "values.yml"):
            continue
        svc_name, _ = _parse_settings_filename(f)
        if svc_name is not None:
            edges.extend(_extract_from_settings(f, repo))

    return edges


def save_to_graph_db(edges: list[dict], db_path: str) -> None:
    """
    Save extracted edges to a SQLite graph database.

    Creates tables:
        nodes — unique entities
        edges — relationships between entities
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT,
            file TEXT,
            repo TEXT,
            branch TEXT DEFAULT 'default'
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            target TEXT,
            edge_type TEXT,
            file TEXT,
            repo TEXT,
            branch TEXT DEFAULT 'default',
            metadata TEXT,
            FOREIGN KEY (source) REFERENCES nodes(id),
            FOREIGN KEY (target) REFERENCES nodes(id)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_edges_branch ON edges(branch)")

    # Insert nodes (dedup from edges)
    node_set = set()
    for edge in edges:
        node_set.add((edge["source"], edge.get("file", ""), edge.get("repo", "")))
        node_set.add((edge["target"], "", edge.get("repo", "")))

    for node_id, file_path, repo in node_set:
        # Determine node type from ID
        if node_id.startswith("kv_secret:"):
            node_type = "kv_secret"
        elif node_id.startswith("k8s_secret:"):
            node_type = "k8s_secret"
        elif node_id.startswith("kv_data:"):
            node_type = "kv_data_source"
        elif node_id.startswith("config:"):
            node_type = "config_file"
        elif node_id.startswith("endpoint:"):
            node_type = "external_endpoint"
        elif node_id.startswith("config_prop:"):
            node_type = "config_property"
        elif node_id.endswith(".tf"):
            node_type = "terraform_file"
        elif node_id.endswith(".yaml") or node_id.endswith(".yml"):
            node_type = "yaml_file"
        else:
            node_type = "entity"

        cursor.execute(
            "INSERT OR REPLACE INTO nodes (id, node_type, file, repo) VALUES (?, ?, ?, ?)",
            (node_id, node_type, file_path, repo),
        )

    # Insert edges
    for edge in edges:
        metadata = json.dumps({
            k: v for k, v in edge.items()
            if k not in ("source", "target", "edge_type", "file", "repo")
        })
        cursor.execute(
            "INSERT INTO edges (source, target, edge_type, file, repo, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                edge["source"],
                edge["target"],
                edge["edge_type"],
                edge.get("file", ""),
                edge.get("repo", ""),
                metadata,
            ),
        )

    conn.commit()
    conn.close()
