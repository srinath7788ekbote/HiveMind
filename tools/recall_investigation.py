"""
Recall Investigation — Search past saved investigations

Searches the investigation memory using BM25 (consistent with
query_memory.py) to find past investigations matching a query.

Usage:
    python tools/recall_investigation.py --client dfin --query "tagging-service startup failure"
    python tools/recall_investigation.py --client dfin --query "OOMKilled" --incident_type OOMKilled
    python tools/recall_investigation.py --client dfin --query "spring bean" --service tagging-service
"""

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _tokenize(text: str) -> list[str]:
    """Tokenize text for BM25 with compound-name expansion."""
    tokens = re.findall(r'[a-zA-Z0-9][a-zA-Z0-9_-]*', text.lower())
    expanded = []
    for t in tokens:
        expanded.append(t)
        parts = re.split(r'[-_]', t)
        if len(parts) > 1:
            expanded.extend(p for p in parts if len(p) > 1)
    return expanded


def _load_investigations_from_json(client: str) -> list[dict]:
    """Load all investigations from JSON files for a client."""
    inv_dir = PROJECT_ROOT / "memory" / client / "investigations"
    if not inv_dir.exists():
        return []

    investigations = []
    for jf in sorted(inv_dir.glob("*.json")):
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "id" in data:
                    investigations.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return investigations


def recall_investigation(
    client: str,
    query: str,
    service_name: str = None,
    incident_type: str = None,
    top_k: int = 3,
) -> list[dict]:
    """
    Search past saved investigations for similar incidents.

    Args:
        client: Client name (e.g. "dfin").
        query: Search query text.
        service_name: Optional exact-match filter on service name.
        incident_type: Optional exact-match filter on incident type.
        top_k: Number of results to return (default 3).

    Returns:
        List of matching investigations ranked by relevance.
        Empty list if no investigations saved yet.
    """
    if not client or not client.strip():
        return []
    if not query or not query.strip():
        return []

    # BM25 over JSON files — primary search path
    # Investigation corpus is small; BM25 gives predictable, high-quality
    # results consistent with query_memory.py approach.
    return _fallback_json_search(client, query, service_name, incident_type, top_k)


def _fallback_json_search(
    client: str,
    query: str,
    service_name: str = None,
    incident_type: str = None,
    top_k: int = 3,
) -> list[dict]:
    """BM25 search over investigation JSON files."""
    investigations = _load_investigations_from_json(client)
    if not investigations:
        return []

    # Apply filters
    if service_name:
        investigations = [inv for inv in investigations if inv.get("service_name") == service_name]
    if incident_type:
        investigations = [inv for inv in investigations if inv.get("incident_type") == incident_type]

    if not investigations:
        return []

    # Build BM25 index over investigations
    corpus_tokens = []
    for inv in investigations:
        text = (
            f"{inv.get('root_cause_summary', '')} "
            f"{inv.get('resolution', '')} "
            f"{inv.get('service_name', '')} "
            f"{inv.get('incident_type', '')} "
            f"{' '.join(inv.get('tags', []))}"
        )
        corpus_tokens.append(_tokenize(text))

    try:
        from rank_bm25 import BM25Plus
        bm25 = BM25Plus(corpus_tokens)
    except ImportError:
        # rank_bm25 not available — simple token overlap scoring
        query_tokens = set(_tokenize(query))
        scored = []
        for i, tokens in enumerate(corpus_tokens):
            token_set = set(tokens)
            overlap = len(query_tokens & token_set)
            if overlap > 0:
                score = overlap / len(query_tokens) if query_tokens else 0
                scored.append((score, i))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [_format_investigation(investigations[i], round(s * 100, 1)) for s, i in scored[:top_k]]

    query_tokens = _tokenize(query)
    scores = bm25.get_scores(query_tokens)

    scored = [(scores[i], i) for i in range(len(investigations)) if scores[i] > 0]
    if not scored:
        return []

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:top_k]

    max_score = scored[0][0] if scored else 1
    return [
        _format_investigation(investigations[i], round((s / max_score) * 100, 1))
        for s, i in scored
    ]


def _format_investigation(inv: dict, relevance_pct: float) -> dict:
    """Format an investigation dict for output."""
    return {
        "id": inv.get("id", ""),
        "service_name": inv.get("service_name", ""),
        "incident_type": inv.get("incident_type", ""),
        "timestamp": inv.get("timestamp", ""),
        "root_cause_summary": inv.get("root_cause_summary", ""),
        "resolution": inv.get("resolution", ""),
        "files_cited": inv.get("files_cited", []),
        "tags": inv.get("tags", []),
        "relevance_pct": relevance_pct,
    }


def main():
    parser = argparse.ArgumentParser(
        description="HiveMind Recall Investigation — search past investigations"
    )
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--service", default=None, help="Filter by service name")
    parser.add_argument("--incident_type", default=None, help="Filter by incident type")
    parser.add_argument("--top_k", type=int, default=3, help="Number of results")
    args = parser.parse_args()

    results = recall_investigation(
        client=args.client,
        query=args.query,
        service_name=args.service,
        incident_type=args.incident_type,
        top_k=args.top_k,
    )

    if not results:
        print("No past investigations found.")
        return

    print(f"Found {len(results)} past investigation(s):\n")
    for i, inv in enumerate(results, 1):
        print(f"--- Investigation {i} (relevance: {inv['relevance_pct']}%) ---")
        print(f"  ID: {inv['id']}")
        print(f"  Service: {inv['service_name']}")
        print(f"  Type: {inv['incident_type']}")
        print(f"  Time: {inv['timestamp']}")
        print(f"  Root Cause: {inv['root_cause_summary']}")
        print(f"  Resolution: {inv['resolution']}")
        if inv.get("tags"):
            print(f"  Tags: {', '.join(inv['tags'])}")
        if inv.get("files_cited"):
            print(f"  Files:")
            for fc in inv["files_cited"]:
                if isinstance(fc, dict):
                    print(f"    - {fc.get('file_path', '')} [{fc.get('repo', '')}:{fc.get('branch', '')}]")
        print()


if __name__ == "__main__":
    main()
