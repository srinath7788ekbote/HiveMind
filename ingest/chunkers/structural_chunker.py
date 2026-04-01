"""
Structure-aware chunking for YAML, HCL, and Helm values files.

Infrastructure files have natural semantic boundaries (pipeline stages,
Terraform resource blocks, Helm service sections). Chunking at those
boundaries gives the retrieval system complete, coherent units instead
of arbitrary character slices that split mid-stage or mid-resource.

Falls back gracefully: if any parse fails, returns None so the caller
uses the existing fixed-size chunker. Never raises exceptions.
"""

import re
from pathlib import Path
from typing import Optional


def _char_offset_to_line(content: str, offset: int) -> int:
    """Convert a character offset to a 1-based line number."""
    return content[:offset].count('\n') + 1


def _find_line_for_pattern(content: str, pattern: str) -> int | None:
    """Find the 1-based line number of the first occurrence of pattern in content.

    Returns None if pattern is not found.
    """
    idx = content.find(pattern)
    if idx < 0:
        return None
    return _char_offset_to_line(content, idx)


def _try_import_ruamel():
    """Import ruamel.yaml, return (YAML class, True) or (None, False)."""
    try:
        from ruamel.yaml import YAML
        return YAML, True
    except ImportError:
        return None, False


def _try_import_hcl2():
    """Import hcl2, return (hcl2 module, True) or (None, False)."""
    try:
        import hcl2
        return hcl2, True
    except ImportError:
        return None, False


def _yaml_dump_to_str(yaml_cls, data) -> str:
    """Serialize a ruamel.yaml object back to a YAML string."""
    import io
    stream = io.StringIO()
    y = yaml_cls()
    y.default_flow_style = False
    y.dump(data, stream)
    return stream.getvalue()


# ─────────────────────────────────────────────────────────────
# 3a. HARNESS PIPELINE YAML CHUNKER
# ─────────────────────────────────────────────────────────────

def chunk_harness_pipeline(
    content: str,
    file_path: str,
    max_chunk_chars: int = 3000,
) -> list[dict]:
    """
    Chunk a Harness pipeline YAML by stage boundaries.

    Each stage becomes one chunk. If a stage exceeds max_chunk_chars,
    it is further split at step boundaries within that stage.
    """
    try:
        chunks = _chunk_harness_yaml_parsed(content, file_path, max_chunk_chars)
        if chunks:
            return chunks
    except Exception:
        pass

    # Regex fallback
    try:
        chunks = _chunk_harness_yaml_regex(content, file_path, max_chunk_chars)
        if chunks:
            return chunks
    except Exception:
        pass

    return []


def _chunk_harness_yaml_parsed(
    content: str,
    file_path: str,
    max_chunk_chars: int,
) -> list[dict]:
    """Parse with ruamel.yaml and chunk by stage."""
    YAML, ok = _try_import_ruamel()
    if not ok:
        return []

    y = YAML()
    y.preserve_quotes = True
    doc = y.load(content)
    if not isinstance(doc, dict):
        return []

    pipeline = doc.get("pipeline", doc)
    if not isinstance(pipeline, dict):
        return []

    stages = pipeline.get("stages")
    if not stages or not isinstance(stages, list):
        return []

    chunks = []
    for idx, stage_entry in enumerate(stages):
        if not isinstance(stage_entry, dict):
            continue

        # Extract the stage object — could be under "stage" key or directly
        stage_obj = stage_entry.get("stage", stage_entry)
        stage_name = ""
        if isinstance(stage_obj, dict):
            stage_name = stage_obj.get("name", stage_obj.get("identifier", f"stage_{idx}"))
        if not stage_name:
            stage_name = f"stage_{idx}"

        stage_yaml = _yaml_dump_to_str(YAML, stage_entry)
        header = f"# File: {file_path}\n# Stage: {stage_name}\n\n"

        # Compute line_start by searching for the stage name in original content
        line_start = _find_line_for_pattern(content, str(stage_name))

        if len(stage_yaml) <= max_chunk_chars:
            chunks.append({
                "text": header + stage_yaml,
                "metadata": {
                    "chunk_type": "harness_stage",
                    "stage_name": str(stage_name),
                    "stage_index": idx,
                    "source_file": file_path,
                    "chunking_strategy": "structural_harness",
                    "line_start": line_start,
                },
            })
        else:
            # Split large stages at step boundaries
            sub_chunks = _split_large_stage(
                stage_entry, stage_name, idx, file_path, max_chunk_chars, YAML
            )
            if sub_chunks:
                chunks.extend(sub_chunks)
            else:
                # Can't split further — keep as one chunk
                chunks.append({
                    "text": header + stage_yaml,
                    "metadata": {
                        "chunk_type": "harness_stage",
                        "stage_name": str(stage_name),
                        "stage_index": idx,
                        "source_file": file_path,
                        "chunking_strategy": "structural_harness",
                        "line_start": line_start,
                    },
                })

    return chunks


def _split_large_stage(
    stage_entry: dict,
    stage_name: str,
    stage_index: int,
    file_path: str,
    max_chunk_chars: int,
    yaml_cls,
) -> list[dict]:
    """Split a large stage into sub-chunks at step boundaries."""
    stage_obj = stage_entry.get("stage", stage_entry)
    if not isinstance(stage_obj, dict):
        return []

    # Navigate to steps: stage.spec.execution.steps
    spec = stage_obj.get("spec", {})
    if not isinstance(spec, dict):
        return []
    execution = spec.get("execution", {})
    if not isinstance(execution, dict):
        return []
    steps = execution.get("steps", [])
    if not steps or not isinstance(steps, list):
        return []

    chunks = []
    current_steps = []
    current_size = 0

    for step in steps:
        step_yaml = _yaml_dump_to_str(yaml_cls, step)
        step_size = len(step_yaml)

        if current_size + step_size > max_chunk_chars and current_steps:
            # Flush current accumulation
            header = f"# File: {file_path}\n# Stage: {stage_name} (part {len(chunks) + 1})\n\n"
            combined = "\n".join(_yaml_dump_to_str(yaml_cls, s) for s in current_steps)
            chunks.append({
                "text": header + combined,
                "metadata": {
                    "chunk_type": "harness_stage",
                    "stage_name": str(stage_name),
                    "stage_index": stage_index,
                    "source_file": file_path,
                    "chunking_strategy": "structural_harness",
                    "line_start": None,
                },
            })
            current_steps = []
            current_size = 0

        current_steps.append(step)
        current_size += step_size

    # Flush remaining
    if current_steps:
        header = f"# File: {file_path}\n# Stage: {stage_name} (part {len(chunks) + 1})\n\n"
        combined = "\n".join(_yaml_dump_to_str(yaml_cls, s) for s in current_steps)
        chunks.append({
            "text": header + combined,
            "metadata": {
                "chunk_type": "harness_stage",
                "stage_name": str(stage_name),
                "stage_index": stage_index,
                "source_file": file_path,
                "chunking_strategy": "structural_harness",
                "line_start": None,
            },
        })

    return chunks


def _chunk_harness_yaml_regex(
    content: str,
    file_path: str,
    max_chunk_chars: int,
) -> list[dict]:
    """Regex fallback: split on '  - stage:' pattern."""
    # Match lines like "      - stage:" with varying indent
    pattern = re.compile(r'^(\s+- stage:\s*)$', re.MULTILINE)
    positions = [m.start() for m in pattern.finditer(content)]

    if not positions:
        # Try alternate pattern (inline stage)
        pattern2 = re.compile(r'^(\s+- stage:\s*\n)', re.MULTILINE)
        positions = [m.start() for m in pattern2.finditer(content)]

    if not positions:
        return []

    chunks = []
    for idx, start in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(content)
        stage_text = content[start:end].rstrip()

        # Try to extract stage name from the text
        name_match = re.search(r'name:\s*(.+)', stage_text)
        stage_name = name_match.group(1).strip().strip('"\'') if name_match else f"stage_{idx}"

        line_start = _char_offset_to_line(content, start)
        header = f"# File: {file_path}\n# Stage: {stage_name}\n\n"
        chunks.append({
            "text": header + stage_text,
            "metadata": {
                "chunk_type": "harness_stage",
                "stage_name": stage_name,
                "stage_index": idx,
                "source_file": file_path,
                "chunking_strategy": "structural_harness",
                "line_start": line_start,
            },
        })

    return chunks


# ─────────────────────────────────────────────────────────────
# 3b. TERRAFORM HCL CHUNKER
# ─────────────────────────────────────────────────────────────

def chunk_terraform_hcl(
    content: str,
    file_path: str,
    max_chunk_chars: int = 3000,
) -> list[dict]:
    """
    Chunk a Terraform HCL file by resource/data/module block boundaries.

    Each top-level block becomes one chunk. Related variable blocks
    are grouped up to max_chunk_chars.
    """
    try:
        chunks = _chunk_terraform_parsed(content, file_path, max_chunk_chars)
        if chunks:
            return chunks
    except Exception:
        pass

    try:
        chunks = _chunk_terraform_regex(content, file_path, max_chunk_chars)
        if chunks:
            return chunks
    except Exception:
        pass

    return []


def _chunk_terraform_parsed(
    content: str,
    file_path: str,
    max_chunk_chars: int,
) -> list[dict]:
    """Parse with python-hcl2 and chunk by top-level block."""
    hcl2_mod, ok = _try_import_hcl2()
    if not ok:
        return []

    import io
    parsed = hcl2_mod.load(io.StringIO(content))
    if not isinstance(parsed, dict):
        return []

    chunks = []
    # Group small blocks (variables, outputs) together
    groupable_types = {"variable", "output", "locals"}
    group_buffer = []
    group_size = 0

    def _flush_group():
        nonlocal group_buffer, group_size
        if not group_buffer:
            return
        combined_text = "\n\n".join(t for t, _ in group_buffer)
        # Use first block's name as representative
        first_name = group_buffer[0][1]
        line_start = _find_line_for_pattern(content, first_name)
        header = f"# File: {file_path}\n# Block: variables/outputs ({len(group_buffer)} blocks)\n\n"
        chunks.append({
            "text": header + combined_text,
            "metadata": {
                "chunk_type": "terraform_block",
                "block_type": "variable_group",
                "block_name": first_name,
                "source_file": file_path,
                "chunking_strategy": "structural_terraform",
                "line_start": line_start,
            },
        })
        group_buffer = []
        group_size = 0

    for block_type, blocks in parsed.items():
        if not isinstance(blocks, list):
            continue

        for block in blocks:
            if not isinstance(block, dict):
                continue

            # Extract block name
            block_name_parts = []
            for key in block:
                if isinstance(block[key], dict):
                    block_name_parts.append(key)
                    break
            if not block_name_parts:
                block_name_parts = list(block.keys())[:1]

            if block_type == "resource" or block_type == "data":
                # resource blocks have: {"type": {"name": {...}}}
                for type_name, instances in block.items():
                    if isinstance(instances, dict):
                        for inst_name in instances:
                            full_name = f"{type_name}.{inst_name}"
                            block_text = _hcl_block_to_text(block_type, type_name, inst_name, instances[inst_name])
                            line_start = _find_line_for_pattern(content, inst_name)
                            header = f"# File: {file_path}\n# Block: {block_type} {full_name}\n\n"
                            chunks.append({
                                "text": header + block_text,
                                "metadata": {
                                    "chunk_type": "terraform_block",
                                    "block_type": block_type,
                                    "block_name": full_name,
                                    "source_file": file_path,
                                    "chunking_strategy": "structural_terraform",
                                    "line_start": line_start,
                                },
                            })
                    else:
                        # Simple key-value
                        block_str = f'{block_type} "{type_name}" = {instances}'
                        if block_type in groupable_types:
                            if group_size + len(block_str) > max_chunk_chars:
                                _flush_group()
                            group_buffer.append((block_str, type_name))
                            group_size += len(block_str)
                        else:
                            header = f"# File: {file_path}\n# Block: {block_type} {type_name}\n\n"
                            chunks.append({
                                "text": header + block_str,
                                "metadata": {
                                    "chunk_type": "terraform_block",
                                    "block_type": block_type,
                                    "block_name": type_name,
                                    "source_file": file_path,
                                    "chunking_strategy": "structural_terraform",
                                    "line_start": _find_line_for_pattern(content, type_name),
                                },
                            })
            elif block_type in groupable_types:
                for var_name, var_val in block.items():
                    block_str = f'{block_type} "{var_name}" {{\n  {_dict_to_hcl_attrs(var_val) if isinstance(var_val, dict) else f"default = {var_val!r}"}\n}}'
                    if group_size + len(block_str) > max_chunk_chars:
                        _flush_group()
                    group_buffer.append((block_str, var_name))
                    group_size += len(block_str)
            else:
                # module, provider, terraform, etc.
                for name, body in block.items():
                    block_str = _hcl_block_to_text(block_type, name, None, body)
                    header = f"# File: {file_path}\n# Block: {block_type} {name}\n\n"
                    chunks.append({
                        "text": header + block_str,
                        "metadata": {
                            "chunk_type": "terraform_block",
                            "block_type": block_type,
                            "block_name": name,
                            "source_file": file_path,
                            "chunking_strategy": "structural_terraform",
                            "line_start": _find_line_for_pattern(content, name),
                        },
                    })

    _flush_group()
    return chunks


def _hcl_block_to_text(block_type: str, type_name: str, inst_name: Optional[str], body) -> str:
    """Convert an HCL block back to a readable text representation."""
    if inst_name:
        header = f'{block_type} "{type_name}" "{inst_name}" {{'
    else:
        header = f'{block_type} "{type_name}" {{'
    if isinstance(body, dict):
        attrs = _dict_to_hcl_attrs(body)
        return f"{header}\n{attrs}\n}}"
    return f"{header}\n  {body!r}\n}}"


def _dict_to_hcl_attrs(d: dict, indent: int = 2) -> str:
    """Convert a dict to HCL-like attribute text."""
    lines = []
    prefix = " " * indent
    for k, v in d.items():
        if isinstance(v, dict):
            inner = _dict_to_hcl_attrs(v, indent + 2)
            lines.append(f"{prefix}{k} {{\n{inner}\n{prefix}}}")
        elif isinstance(v, list):
            lines.append(f"{prefix}{k} = {v!r}")
        elif isinstance(v, bool):
            lines.append(f"{prefix}{k} = {'true' if v else 'false'}")
        elif isinstance(v, str):
            lines.append(f'{prefix}{k} = "{v}"')
        else:
            lines.append(f"{prefix}{k} = {v}")
    return "\n".join(lines)


def _chunk_terraform_regex(
    content: str,
    file_path: str,
    max_chunk_chars: int,
) -> list[dict]:
    """Regex fallback: split on top-level block declarations."""
    block_pattern = re.compile(
        r'^(resource|data|module|variable|locals|output|provider|terraform)\s',
        re.MULTILINE,
    )
    positions = [m.start() for m in block_pattern.finditer(content)]

    if not positions:
        return []

    chunks = []
    groupable_types = {"variable", "output"}
    group_buffer = []
    group_size = 0

    def _flush_group():
        nonlocal group_buffer, group_size
        if not group_buffer:
            return
        combined = "\n\n".join(t for t, _ in group_buffer)
        first_name = group_buffer[0][1]
        line_start = _find_line_for_pattern(content, first_name)
        header = f"# File: {file_path}\n# Block: variables/outputs ({len(group_buffer)} blocks)\n\n"
        chunks.append({
            "text": header + combined,
            "metadata": {
                "chunk_type": "terraform_block",
                "block_type": "variable_group",
                "block_name": first_name,
                "source_file": file_path,
                "chunking_strategy": "structural_terraform",
                "line_start": line_start,
            },
        })
        group_buffer = []
        group_size = 0

    for idx, start in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(content)
        block_text = content[start:end].rstrip()

        # Determine block type and name
        first_line = block_text.split('\n')[0]
        parts = first_line.split()
        block_type = parts[0] if parts else "unknown"
        block_name = parts[1].strip('"') if len(parts) > 1 else "unnamed"
        if len(parts) > 2:
            block_name += "." + parts[2].strip('"')

        line_start = _char_offset_to_line(content, start)

        if block_type in groupable_types:
            if group_size + len(block_text) > max_chunk_chars:
                _flush_group()
            group_buffer.append((block_text, block_name))
            group_size += len(block_text)
        else:
            _flush_group()
            header = f"# File: {file_path}\n# Block: {block_type} {block_name}\n\n"
            chunks.append({
                "text": header + block_text,
                "metadata": {
                    "chunk_type": "terraform_block",
                    "block_type": block_type,
                    "block_name": block_name,
                    "source_file": file_path,
                    "chunking_strategy": "structural_terraform",
                    "line_start": line_start,
                },
            })

    _flush_group()
    return chunks


# ─────────────────────────────────────────────────────────────
# 3c. HELM VALUES YAML CHUNKER
# ─────────────────────────────────────────────────────────────

def chunk_helm_values(
    content: str,
    file_path: str,
    max_chunk_chars: int = 3000,
) -> list[dict]:
    """
    Chunk a Helm values.yaml by top-level service key boundaries.

    Each top-level key becomes one chunk.
    """
    YAML, ok = _try_import_ruamel()
    if not ok:
        return []

    try:
        y = YAML()
        y.preserve_quotes = True
        doc = y.load(content)
    except Exception:
        return []

    if not isinstance(doc, dict):
        return []

    chunks = []
    scalar_buffer = []

    for key, value in doc.items():
        if isinstance(value, (dict, list)):
            section_yaml = _yaml_dump_to_str(YAML, {key: value})
            header = f"# File: {file_path}\n# Section: {key}\n\n"
            line_start = _find_line_for_pattern(content, str(key) + ":")

            if len(section_yaml) <= max_chunk_chars:
                chunks.append({
                    "text": header + section_yaml,
                    "metadata": {
                        "chunk_type": "helm_values_section",
                        "section_key": str(key),
                        "source_file": file_path,
                        "chunking_strategy": "structural_helm",
                        "line_start": line_start,
                    },
                })
            else:
                # Split at second-level keys
                sub_chunks = _split_large_helm_section(
                    key, value, file_path, content, max_chunk_chars, YAML
                )
                if sub_chunks:
                    chunks.extend(sub_chunks)
                else:
                    chunks.append({
                        "text": header + section_yaml,
                        "metadata": {
                            "chunk_type": "helm_values_section",
                            "section_key": str(key),
                            "source_file": file_path,
                            "chunking_strategy": "structural_helm",
                            "line_start": line_start,
                        },
                    })
        else:
            # Scalar values — accumulate into one chunk
            scalar_buffer.append(f"{key}: {value}")

    # Flush scalars
    if scalar_buffer:
        header = f"# File: {file_path}\n# Section: root_scalars\n\n"
        chunks.append({
            "text": header + "\n".join(scalar_buffer),
            "metadata": {
                "chunk_type": "helm_values_section",
                "section_key": "root_scalars",
                "source_file": file_path,
                "chunking_strategy": "structural_helm",
                "line_start": 1,
            },
        })

    return chunks


def _split_large_helm_section(
    parent_key: str,
    value: dict,
    file_path: str,
    content: str,
    max_chunk_chars: int,
    yaml_cls,
) -> list[dict]:
    """Split a large Helm section at second-level keys."""
    if not isinstance(value, dict):
        return []

    chunks = []
    for sub_key, sub_val in value.items():
        sub_yaml = _yaml_dump_to_str(yaml_cls, {parent_key: {sub_key: sub_val}})
        header = f"# File: {file_path}\n# Section: {parent_key}.{sub_key}\n\n"
        line_start = _find_line_for_pattern(content, str(sub_key) + ":")
        chunks.append({
            "text": header + sub_yaml,
            "metadata": {
                "chunk_type": "helm_values_section",
                "section_key": f"{parent_key}.{sub_key}",
                "source_file": file_path,
                "chunking_strategy": "structural_helm",
                "line_start": line_start,
            },
        })

    return chunks


# ─────────────────────────────────────────────────────────────
# 3d. GENERIC YAML CHUNKER
# ─────────────────────────────────────────────────────────────

def chunk_generic_yaml(
    content: str,
    file_path: str,
    max_chunk_chars: int = 3000,
) -> list[dict]:
    """
    Chunk any YAML file by top-level key boundaries.
    Fallback for YAML files that aren't Harness pipelines or Helm values.
    """
    YAML, ok = _try_import_ruamel()
    if not ok:
        return []

    try:
        y = YAML()
        y.preserve_quotes = True
        doc = y.load(content)
    except Exception:
        return []

    if not isinstance(doc, dict):
        return []

    chunks = []
    small_buffer = []
    small_size = 0

    for key, value in doc.items():
        section_yaml = _yaml_dump_to_str(YAML, {key: value})
        section_size = len(section_yaml)

        # Group small keys together
        if section_size < 200:
            small_buffer.append(section_yaml)
            small_size += section_size
            if small_size >= max_chunk_chars:
                header = f"# File: {file_path}\n# Section: grouped_keys\n\n"
                chunks.append({
                    "text": header + "\n".join(small_buffer),
                    "metadata": {
                        "chunk_type": "yaml_section",
                        "section_key": "grouped_keys",
                        "source_file": file_path,
                        "chunking_strategy": "structural_yaml",
                        "line_start": None,
                    },
                })
                small_buffer = []
                small_size = 0
            continue

        # Flush small buffer before adding a big key
        if small_buffer:
            header = f"# File: {file_path}\n# Section: grouped_keys\n\n"
            chunks.append({
                "text": header + "\n".join(small_buffer),
                "metadata": {
                    "chunk_type": "yaml_section",
                    "section_key": "grouped_keys",
                    "source_file": file_path,
                    "chunking_strategy": "structural_yaml",
                    "line_start": None,
                },
            })
            small_buffer = []
            small_size = 0

        line_start = _find_line_for_pattern(content, str(key) + ":")
        header = f"# File: {file_path}\n# Section: {key}\n\n"
        chunks.append({
            "text": header + section_yaml,
            "metadata": {
                "chunk_type": "yaml_section",
                "section_key": str(key),
                "source_file": file_path,
                "chunking_strategy": "structural_yaml",
                "line_start": line_start,
            },
        })

    # Flush remaining small keys
    if small_buffer:
        header = f"# File: {file_path}\n# Section: grouped_keys\n\n"
        chunks.append({
            "text": header + "\n".join(small_buffer),
            "metadata": {
                "chunk_type": "yaml_section",
                "section_key": "grouped_keys",
                "source_file": file_path,
                "chunking_strategy": "structural_yaml",
                "line_start": None,
            },
        })

    return chunks


# ─────────────────────────────────────────────────────────────
# 3e. DISPATCHER
# ─────────────────────────────────────────────────────────────

def _is_harness_pipeline(content: str) -> bool:
    """Check if content looks like a Harness pipeline YAML."""
    return ("pipeline:" in content and
            "stages:" in content and
            "stage:" in content)


def _is_helm_values(content: str, file_path: str) -> bool:
    """Check if content looks like a Helm values.yaml."""
    fname = Path(file_path).name.lower()
    if fname == "values.yaml" or fname.startswith("values-"):
        return True
    # Content-based detection
    return "image:" in content and "replicaCount:" in content


def chunk_structured_file(
    content: str,
    file_path: str,
    max_chunk_chars: int = 3000,
) -> Optional[list[dict]]:
    """
    Route to the correct structural chunker based on file type.

    Returns None if file type is not handled structurally
    (caller should use existing fixed-size chunking).

    NEVER raises exceptions — always returns None on any failure.
    """
    try:
        suffix = Path(file_path).suffix.lower()

        # Terraform HCL files
        if suffix in ('.tf', '.tfvars'):
            result = chunk_terraform_hcl(content, file_path, max_chunk_chars)
            return result if result else None

        # YAML files — route by content
        if suffix in ('.yaml', '.yml'):
            if not content or not content.strip():
                return None

            if _is_harness_pipeline(content):
                result = chunk_harness_pipeline(content, file_path, max_chunk_chars)
                return result if result else None

            if _is_helm_values(content, file_path):
                result = chunk_helm_values(content, file_path, max_chunk_chars)
                return result if result else None

            # Generic YAML fallback
            result = chunk_generic_yaml(content, file_path, max_chunk_chars)
            return result if result else None

        # Not a structurally-chunkable file type
        return None

    except Exception:
        # Never crash — let caller use fixed-size chunking
        return None
