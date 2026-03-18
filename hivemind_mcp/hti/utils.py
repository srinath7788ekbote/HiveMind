"""HTI Utilities — Shared helpers for HiveMind Tree Intelligence."""

import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def detect_file_type(file_path: str, content: str = None) -> str:
    """Detect infrastructure file type from path and optional content.

    Returns: "harness" | "terraform" | "helm" | "generic"
    """
    fp = file_path.lower().replace("\\", "/")

    # Terraform: extension-based
    if fp.endswith((".tf", ".hcl")):
        return "terraform"

    # Harness: path or content signals
    if "pipeline" in fp or "harness" in fp or ".harness" in fp:
        return "harness"
    if content:
        cl = content.lstrip()
        if cl.startswith("pipeline:") or "\npipeline:" in content:
            return "harness"

    # Helm: path or content signals
    if any(kw in fp for kw in ("charts/", "chart/", "values", "helm")):
        return "helm"
    if content:
        if "replicaCount:" in content or "image:" in content:
            return "helm"

    return "generic"


def get_hti_db_path(client: str, project_root: Path = None) -> Path:
    """Return path to hti.sqlite for a client."""
    root = project_root or PROJECT_ROOT
    return root / "memory" / client / "hti.sqlite"


def get_hti_connection(client: str, project_root: Path = None) -> sqlite3.Connection:
    """Get SQLite connection with WAL mode, creating DB + schema if needed."""
    db_path = get_hti_db_path(client, project_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Apply schema if tables don't exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='hti_skeletons'"
    )
    if cursor.fetchone() is None:
        schema_path = Path(__file__).parent / "schema.sql"
        schema_sql = schema_path.read_text(encoding="utf-8")
        conn.executescript(schema_sql)

    return conn


def format_skeleton_for_display(skeleton: dict, max_depth: int = 4, indent: int = 0) -> str:
    """Human-readable text representation of skeleton for debugging."""
    lines = []
    prefix = "  " * indent
    stype = skeleton.get("_type", "unknown")
    path = skeleton.get("_path", "?")

    if stype == "object":
        keys = skeleton.get("_keys", [])
        lines.append(f"{prefix}{path} (object, {len(keys)} keys)")
        if indent < max_depth:
            for key, child in skeleton.get("_children", {}).items():
                lines.append(format_skeleton_for_display(child, max_depth, indent + 1))
    elif stype == "array":
        length = skeleton.get("_length", 0)
        lines.append(f"{prefix}{path} (array, {length} items)")
        if indent < max_depth:
            for key, child in skeleton.get("_children", {}).items():
                lines.append(format_skeleton_for_display(child, max_depth, indent + 1))
    elif stype == "truncated":
        lines.append(f"{prefix}{path} (truncated at depth {skeleton.get('_depth', '?')})")
    else:
        preview = skeleton.get("_preview", "")
        lines.append(f"{prefix}{path} ({stype}: {preview})")

    return "\n".join(lines)


def estimate_skeleton_size(skeleton: dict) -> int:
    """Rough token estimate for skeleton JSON (~4 chars per token)."""
    json_str = json.dumps(skeleton, separators=(",", ":"))
    return len(json_str) // 4
