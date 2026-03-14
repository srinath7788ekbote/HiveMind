"""
Save Investigation — Persist a completed investigation to memory

Stores the investigation as JSON and indexes it in ChromaDB for
future recall via BM25/semantic search.

Usage:
    python tools/save_investigation.py --client dfin \
        --service tagging-service \
        --incident_type CrashLoopBackOff \
        --root_cause "Spring bean failed to initialize" \
        --resolution "Restarted dependency pod" \
        --files "charts/tagging-service/templates/deployment.yaml:newAd_Artifacts:release_26_2" \
        --tags "spring-boot,bean-init,dependency"
"""

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

VALID_INCIDENT_TYPES = {
    "CrashLoopBackOff",
    "OOMKilled",
    "SecretMount",
    "ProbeFailure",
    "PipelineFailure",
    "InfraFailure",
    "AppStartup",
    "NetworkPolicy",
    "ImagePull",
    "Unknown",
}


def save_investigation(
    client: str,
    service_name: str,
    incident_type: str,
    root_cause_summary: str,
    resolution: str,
    files_cited: list[dict] | None = None,
    tags: list[str] | None = None,
) -> dict:
    """
    Save a completed investigation to memory.

    Args:
        client: Client name (e.g. "dfin").
        service_name: Primary service investigated.
        incident_type: One of the VALID_INCIDENT_TYPES.
        root_cause_summary: 2-3 sentence factual summary of root cause.
        resolution: What fix was applied or recommended.
        files_cited: List of dicts with file_path, repo, branch, relevance.
        tags: Searchable tags (e.g. ["keyvault", "spring-boot"]).

    Returns:
        dict with id, saved, path keys.
    """
    if not client or not client.strip():
        return {"error": "client is required"}
    if not service_name or not service_name.strip():
        return {"error": "service_name is required"}
    if not root_cause_summary or not root_cause_summary.strip():
        return {"error": "root_cause_summary is required"}
    if not resolution or not resolution.strip():
        return {"error": "resolution is required"}

    if incident_type not in VALID_INCIDENT_TYPES:
        incident_type = "Unknown"

    files_cited = files_cited or []
    tags = tags or []

    investigation_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    investigation = {
        "id": investigation_id,
        "timestamp": timestamp,
        "client": client,
        "service_name": service_name,
        "incident_type": incident_type,
        "root_cause_summary": root_cause_summary,
        "resolution": resolution,
        "files_cited": files_cited,
        "tags": tags,
    }

    # --- JSON storage ---
    inv_dir = PROJECT_ROOT / "memory" / client / "investigations"
    inv_dir.mkdir(parents=True, exist_ok=True)

    json_path = inv_dir / f"{investigation_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(investigation, f, indent=2, ensure_ascii=False)

    # --- ChromaDB storage ---
    try:
        import chromadb

        vectors_path = str(PROJECT_ROOT / "memory" / client / "vectors")
        chroma_client = chromadb.PersistentClient(path=vectors_path)
        collection = chroma_client.get_or_create_collection(
            name="investigations",
        )

        document = f"{root_cause_summary}\n{resolution}"
        metadata = {
            "service_name": service_name,
            "incident_type": incident_type,
            "timestamp": timestamp,
            "tags": json.dumps(tags),
            "files_cited": json.dumps(files_cited),
        }

        collection.add(
            ids=[investigation_id],
            documents=[document],
            metadatas=[metadata],
        )
    except ImportError:
        # ChromaDB not available — JSON-only storage is fine
        pass
    except Exception:
        # ChromaDB error — JSON was already saved, don't fail
        pass

    return {
        "id": investigation_id,
        "saved": True,
        "path": str(json_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="HiveMind Save Investigation — persist investigation to memory"
    )
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--service", required=True, help="Service name")
    parser.add_argument(
        "--incident_type",
        default="Unknown",
        help="Incident type (e.g. CrashLoopBackOff, OOMKilled)",
    )
    parser.add_argument("--root_cause", required=True, help="Root cause summary")
    parser.add_argument("--resolution", required=True, help="Resolution applied")
    parser.add_argument(
        "--files",
        default="",
        help="Comma-separated file citations as path:repo:branch",
    )
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    args = parser.parse_args()

    files_cited = []
    if args.files:
        for entry in args.files.split(","):
            parts = entry.strip().split(":")
            if len(parts) >= 3:
                files_cited.append({
                    "file_path": parts[0],
                    "repo": parts[1],
                    "branch": parts[2],
                    "relevance": parts[3] if len(parts) > 3 else "cited in investigation",
                })
            elif len(parts) == 1 and parts[0]:
                files_cited.append({
                    "file_path": parts[0],
                    "repo": "unknown",
                    "branch": "unknown",
                    "relevance": "cited in investigation",
                })

    tags = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []

    result = save_investigation(
        client=args.client,
        service_name=args.service,
        incident_type=args.incident_type,
        root_cause_summary=args.root_cause,
        resolution=args.resolution,
        files_cited=files_cited,
        tags=tags,
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    print(f"Investigation saved successfully.")
    print(f"  ID: {result['id']}")
    print(f"  Path: {result['path']}")


if __name__ == "__main__":
    main()
