"""
Discover Naming Conventions

Analyzes resource names across all repos to detect patterns:
- Azure resource naming (e.g., kv-{region}-{env}-{project}-{service})
- Terraform resource naming
- Kubernetes resource naming
- Pipeline naming

Returns patterns with confidence scores.
"""

import re
from pathlib import Path
from typing import Optional
from collections import Counter


# Common tokens that map to placeholders
TOKEN_CATEGORIES = {
    "region": [
        'eus2', 'eus', 'wus2', 'wus', 'cus', 'ncus', 'scus',
        'weu', 'neu', 'sea', 'eas', 'eastus2', 'westus2',
        'centralus', 'eastus', 'westus',
    ],
    "env": [
        'dev', 'stg', 'staging', 'prod', 'prd', 'uat', 'np',
        'sandbox', 'sbx', 'test', 'qa',
    ],
    "tier": [
        'prd', 'npd', 'np', 'prod', 'nonprod',
    ],
}


def _tokenize_name(name: str, separator: str = '-') -> list[str]:
    """Split a resource name into tokens."""
    return [t for t in name.split(separator) if t]


def _detect_separator(names: list[str]) -> str:
    """Detect the most common separator in a list of names."""
    sep_counts = Counter()
    for name in names:
        if '-' in name:
            sep_counts['-'] += name.count('-')
        if '_' in name:
            sep_counts['_'] += name.count('_')
    if not sep_counts:
        return '-'
    return sep_counts.most_common(1)[0][0]


def _detect_pattern_from_names(names: list[str], resource_type: str = "") -> list[dict]:
    """
    Try to detect naming patterns from a list of resource names.
    Returns patterns with confidence scores.
    """
    if not names:
        return []

    separator = _detect_separator(names)
    patterns = []

    for name in names:
        tokens = _tokenize_name(name, separator)
        if len(tokens) < 2:
            continue

        pattern_tokens = []
        replacements_made = 0
        for token in tokens:
            token_lower = token.lower()
            replaced = False
            for category, values in TOKEN_CATEGORIES.items():
                if token_lower in values:
                    pattern_tokens.append('{' + category + '}')
                    replacements_made += 1
                    replaced = True
                    break
            if not replaced:
                pattern_tokens.append(token_lower)

        if replacements_made > 0:
            pattern = separator.join(pattern_tokens)
            confidence = min(1.0, 0.5 + (replacements_made * 0.15))
            patterns.append({
                "pattern": pattern,
                "example": name,
                "resource_type": resource_type,
                "separator": separator,
                "token_count": len(tokens),
                "confidence": round(confidence, 2),
            })

    # Deduplicate by pattern string
    seen = set()
    unique = []
    for p in patterns:
        if p["pattern"] not in seen:
            seen.add(p["pattern"])
            unique.append(p)

    return unique


def _extract_tf_resource_names(repo_path: Path) -> list[tuple[str, str]]:
    """
    Extract resource names from Terraform files.
    Returns list of (resource_type, name_value) tuples.
    """
    names = []
    for tf_file in repo_path.rglob("*.tf"):
        try:
            content = tf_file.read_text(encoding='utf-8')
            # Find name = "..." in resource blocks
            for match in re.finditer(
                r'resource\s+"(\w+)"\s+"(\w+)"\s*\{[^}]*?name\s*=\s*"([^"]+)"',
                content,
                re.DOTALL,
            ):
                resource_type = match.group(1)
                name_value = match.group(3)
                # Skip names with interpolation
                if '${' not in name_value and '{' not in name_value:
                    names.append((resource_type, name_value))
        except (OSError, UnicodeDecodeError):
            continue
    return names


def discover_naming(repo_paths: list[str]) -> dict:
    """
    Discover naming conventions across multiple repositories.

    Args:
        repo_paths: List of absolute paths to repository roots.

    Returns:
        dict with keys:
            conventions: list[dict] — detected naming patterns with confidence
            separator: str — most common separator
            examples: list[str] — example resource names
    """
    all_names_by_type: dict[str, list[str]] = {}

    for repo_path_str in repo_paths:
        repo_path = Path(repo_path_str)
        if not repo_path.exists():
            continue

        for resource_type, name_value in _extract_tf_resource_names(repo_path):
            if resource_type not in all_names_by_type:
                all_names_by_type[resource_type] = []
            all_names_by_type[resource_type].append(name_value)

    # Detect patterns per resource type
    all_conventions = []
    all_examples = []
    for resource_type, names in all_names_by_type.items():
        conventions = _detect_pattern_from_names(names, resource_type)
        all_conventions.extend(conventions)
        all_examples.extend(names[:3])  # Keep a few examples per type

    # Detect overall separator
    flat_names = [n for names in all_names_by_type.values() for n in names]
    separator = _detect_separator(flat_names) if flat_names else '-'

    # Sort by confidence descending
    all_conventions.sort(key=lambda c: c["confidence"], reverse=True)

    return {
        "conventions": all_conventions,
        "separator": separator,
        "examples": all_examples[:20],
    }
