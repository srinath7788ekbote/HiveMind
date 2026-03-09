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

    return edges


def save_to_graph_db(edges: list[dict], db_path: str) -> None:
    """
    Save extracted edges to a SQLite graph database.

    Creates tables:
        nodes — unique entities
        edges — relationships between entities
    """
    conn = sqlite3.connect(db_path)
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
