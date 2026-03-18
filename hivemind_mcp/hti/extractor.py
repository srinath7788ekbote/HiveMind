"""HTI Extractor — Build skeleton + node list from YAML/HCL files.

Parses infrastructure files into a compact skeleton tree (keys, paths,
metadata) and a flat list of addressable nodes with full content.
"""

import json
import sys
import warnings
from pathlib import Path


def _build_skeleton(node, path: str, depth: int, max_depth: int, nodes_out: list) -> dict:
    """Recursively build a skeleton tree from a parsed data structure.

    For dicts: object with _keys, _children
    For lists: array with _length, _sample, _children
    For scalars: leaf with _type, _preview
    For None: null node
    Beyond max_depth: truncated node

    Also populates nodes_out with addressable nodes.
    """
    if depth > max_depth:
        return {"_type": "truncated", "_path": path, "_depth": depth}

    # Register this node (store full content)
    nodes_out.append({
        "node_path": path,
        "depth": depth,
        "content_json": json.dumps(node, default=str),
    })

    if node is None:
        return {"_type": "null", "_path": path}

    if isinstance(node, dict):
        keys = list(node.keys())
        children = {}
        for key in keys:
            child_path = f"{path}.{key}"
            children[key] = _build_skeleton(
                node[key], child_path, depth + 1, max_depth, nodes_out
            )
        return {
            "_type": "object",
            "_path": path,
            "_keys": keys,
            "_children": children,
        }

    if isinstance(node, list):
        length = len(node)
        if length > 10:
            sample_indices = [0, 1, 2, length - 1]
        else:
            sample_indices = list(range(length))

        children = {}
        for i in sample_indices:
            child_path = f"{path}[{i}]"
            children[str(i)] = _build_skeleton(
                node[i], child_path, depth + 1, max_depth, nodes_out
            )

        # Also register non-sampled items as nodes (but don't recurse skeleton)
        for i in range(length):
            if i not in sample_indices:
                child_path = f"{path}[{i}]"
                nodes_out.append({
                    "node_path": child_path,
                    "depth": depth + 1,
                    "content_json": json.dumps(node[i], default=str),
                })

        return {
            "_type": "array",
            "_path": path,
            "_length": length,
            "_sample": sample_indices,
            "_children": children,
        }

    # Scalar leaf
    type_name = type(node).__name__
    preview = str(node)[:80]
    return {
        "_type": type_name,
        "_path": path,
        "_preview": preview,
    }


def extract_yaml_tree(file_path: str, max_depth: int = 8) -> tuple:
    """Parse a YAML file and build skeleton + node list.

    Args:
        file_path: Path to the YAML file.
        max_depth: Maximum recursion depth for skeleton building.

    Returns:
        (skeleton_dict, nodes_list) where nodes_list items have:
            node_path, depth, content_json
    """
    p = Path(file_path)
    if not p.exists():
        return ({"_error": f"File not found: {file_path}"}, [])

    try:
        content = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return ({"_error": f"Read error: {e}"}, [])

    if not content.strip():
        return ({"_type": "null", "_path": "root"}, [])

    # Try ruamel.yaml first, fall back to pyyaml
    parsed = None
    try:
        from ruamel.yaml import YAML
        yaml = YAML()
        yaml.preserve_quotes = True
        parsed = yaml.load(content)
        # Convert ruamel types to plain Python for JSON serialization
        parsed = _to_plain(parsed)
    except ImportError:
        warnings.warn(
            "ruamel.yaml not installed; falling back to pyyaml (comments not preserved)",
            stacklevel=2,
        )
        try:
            import yaml
            parsed = yaml.safe_load(content)
        except ImportError:
            return ({"_error": "Neither ruamel.yaml nor pyyaml installed"}, [])
        except Exception as e:
            return ({"_error": f"YAML parse error: {e}"}, [])
    except Exception as e:
        # ruamel parse error — try pyyaml
        try:
            import yaml
            parsed = yaml.safe_load(content)
        except Exception as e2:
            return ({"_error": f"YAML parse error: {e2}"}, [])

    if parsed is None:
        return ({"_type": "null", "_path": "root"}, [])

    nodes = []
    skeleton = _build_skeleton(parsed, "root", 0, max_depth, nodes)
    return (skeleton, nodes)


def extract_hcl_tree(file_path: str, max_depth: int = 8) -> tuple:
    """Parse an HCL/Terraform file and build skeleton + node list.

    Requires python-hcl2. Raises ImportError if not available.

    Args:
        file_path: Path to the .tf/.hcl file.
        max_depth: Maximum recursion depth.

    Returns:
        (skeleton_dict, nodes_list)
    """
    try:
        import hcl2
    except ImportError:
        raise ImportError(
            "python-hcl2 is required for HCL parsing. "
            "Install with: pip install python-hcl2"
        )

    p = Path(file_path)
    if not p.exists():
        return ({"_error": f"File not found: {file_path}"}, [])

    try:
        with open(p, "r", encoding="utf-8") as f:
            parsed = hcl2.load(f)
    except Exception as e:
        return ({"_error": f"HCL parse error: {e}"}, [])

    if not parsed:
        return ({"_type": "null", "_path": "root"}, [])

    nodes = []
    skeleton = _build_skeleton(parsed, "root", 0, max_depth, nodes)
    return (skeleton, nodes)


def _to_plain(obj):
    """Convert ruamel.yaml types to plain Python types for JSON serialization."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_plain(item) for item in obj]
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, float):
        return float(obj)
    if isinstance(obj, str):
        return str(obj)
    # Fallback — try to coerce
    return str(obj)
