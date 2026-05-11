"""
HiveMind MCP Server
====================
Model Context Protocol server that exposes all HiveMind Python tools
as native MCP tools for GitHub Copilot.

All tool wrappers are async and run the underlying synchronous Python
tools via ``asyncio.to_thread`` so that one slow tool never blocks
another.  Each tool call has a configurable per-tool timeout (default
60 s) — if a tool exceeds the timeout its ``asyncio.Task`` is cancelled
and a friendly error message is returned instead of hanging forever.

Usage:
    python hivemind_mcp/hivemind_server.py          # Run as stdio MCP server
    python hivemind_mcp/hivemind_server.py --test   # Validate all imports and exit
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path so tools/ can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Import all existing HiveMind tools
# ---------------------------------------------------------------------------
from tools.query_memory import query_memory
from tools.query_graph import query_graph
from tools.get_entity import get_entity
from tools.search_files import search_files
from tools.get_pipeline import get_pipeline
from tools.get_secret_flow import get_secret_flow
from tools.impact_analysis import impact_analysis
from tools.diff_branches import diff_branches
from tools.list_branches import list_branches
from tools.set_client import set_active_client, get_active_client, list_clients
from tools.write_file import write_file
from tools.read_file import read_file
from tools.propose_edit import propose_edit
from tools.check_branch import check_branch
from tools.save_investigation import save_investigation
from tools.recall_investigation import recall_investigation

# Sync: pre-flight freshness check
from scripts.sync_kb import check_and_sync_if_stale

# HTI (Tree Intelligence) imports
from hivemind_mcp.hti.utils import get_hti_connection
from hivemind_mcp.hawkeye_bridge import get_bridge, hawkeye_available

# ---------------------------------------------------------------------------
# ChromaDB availability check (printed once at import time)
# ---------------------------------------------------------------------------
try:
    import chromadb  # noqa: F401
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    print("⚠️  WARNING: ChromaDB not available. Using JSON fallback (slower).", file=sys.stderr)
    print("   Fix: Use Python 3.12/3.13 and run: pip install chromadb", file=sys.stderr)
    print(f"   Current Python: {sys.version}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Memory file paths
# ---------------------------------------------------------------------------
ACTIVE_CLIENT_FILE = PROJECT_ROOT / "memory" / "active_client.txt"
ACTIVE_BRANCH_FILE = PROJECT_ROOT / "memory" / "active_branch.txt"

# ---------------------------------------------------------------------------
# Per-tool timeout (seconds).  Any tool exceeding this limit will return a
# timeout error rather than blocking the server indefinitely.
# ---------------------------------------------------------------------------
TOOL_TIMEOUT_SECS = 60

# ---------------------------------------------------------------------------
# Create the MCP server
# ---------------------------------------------------------------------------
mcp_server = FastMCP(
    name="hivemind",
    instructions=(
        "HiveMind SRE Knowledge Base. Use these tools to query indexed "
        "infrastructure knowledge including Terraform, Harness pipelines, "
        "Helm charts, secrets, and service dependencies. Always call "
        "get_active_client first to determine the current client context."
    ),
)


# ---------------------------------------------------------------------------
# Helper: safe JSON serialisation of tool results
# ---------------------------------------------------------------------------
def _format_result(result) -> str:
    """Convert a tool result to a readable string for Copilot."""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, indent=2, default=str)
    except (TypeError, ValueError):
        return str(result)


# ---------------------------------------------------------------------------
# Helper: run a blocking tool function with a timeout
# ---------------------------------------------------------------------------
async def _run_with_timeout(func, *args, timeout: int = TOOL_TIMEOUT_SECS, **kwargs):
    """
    Execute *func* in a thread-pool thread with an asyncio timeout.

    If the function completes before *timeout* seconds its return value is
    passed through.  On timeout, a human-readable error dict is returned
    so the caller never sees an unhandled exception.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args, **kwargs),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        return {
            "error": (
                f"Tool timed out after {timeout}s. "
                "Try a more specific query or narrower branch filter."
            )
        }


# ---------------------------------------------------------------------------
# MCP Tool definitions — each wraps an existing Python tool
# ---------------------------------------------------------------------------


@mcp_server.tool()
async def hivemind_query_memory(
    client: str,
    query: str,
    branch: str = None,
    filter_type: str = None,
    top_k: int = 5,
) -> str:
    """Semantic search over the HiveMind knowledge base.

    Searches indexed infrastructure files (Terraform, pipelines, Helm, etc.)
    for content matching the query.

    Results use a 3-stage hybrid retrieval pipeline:
      Stage 1: ChromaDB semantic search + BM25 keyword search (top-20 each)
      Stage 2: Reciprocal Rank Fusion (RRF, k=60) merges both into top-20
      Stage 3: FlashRank cross-encoder reranks top-20 → returns top-N

    Result fields:
    - rrf_score:       fusion confidence from RRF (higher = ranked high
                       in both BM25 and ChromaDB)
    - flashrank_score: reranker relevance score (higher = more relevant
                       to the specific query)
    - retrieval_method: 'hybrid_rrf_reranked' (normal) or
                        'hybrid_rrf_no_rerank' (FlashRank unavailable)

    Each result includes a `source_citation` field formatted as:
        [Source: <file_path> | repo: <repo> | branch: <branch> | relevance: <score>%]
    Use this field directly in your response to cite sources.

    Use this tool FIRST for any question about infrastructure, pipelines,
    services, secrets, or environments.

    Args:
        client: Client name (e.g. "dfin"). Call get_active_client to find this.
        query: Natural language search query.
        branch: Optional branch filter (e.g. "main", "release_26_3").
        filter_type: Optional file type filter (e.g. "terraform", "pipeline").
        top_k: Number of results to return (default 5).
    """
    try:
        result = await _run_with_timeout(
            query_memory,
            client=client,
            query=query,
            branch=branch,
            filter_type=filter_type,
            top_k=top_k,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_query_graph(
    client: str,
    entity: str,
    direction: str = "both",
    depth: int = 1,
    branch: str = None,
) -> str:
    """Traverse the entity relationship graph.

    Finds entities connected to the given entity via dependency edges.
    Supports outbound (what does it depend on), inbound (what depends on it),
    or both directions.

    Use this to understand dependency chains, service relationships,
    and infrastructure connections.

    Args:
        client: Client name (e.g. "dfin").
        entity: Entity name or ID to search from.
        direction: "out" (dependencies), "in" (dependents), or "both".
        depth: How many hops to traverse (default 1).
        branch: Optional branch filter.
    """
    try:
        result = await _run_with_timeout(
            query_graph,
            client=client,
            entity=entity,
            direction=direction,
            depth=depth,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_get_entity(
    client: str,
    name: str,
    branch: str = None,
) -> str:
    """Look up a specific entity by name.

    Returns full details of a named entity including its type, file location,
    repo, and all inbound/outbound relationships.

    Use this when you know the exact name of a resource, pipeline, service,
    or secret and want its full details.

    Args:
        client: Client name (e.g. "dfin").
        name: Entity name to look up.
        branch: Optional branch filter.
    """
    try:
        result = await _run_with_timeout(
            get_entity,
            client=client,
            name=name,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_search_files(
    client: str,
    query: str = "",
    file_type: str = None,
    repo: str = None,
    branch: str = None,
    limit: int = 25,
) -> str:
    """Search for indexed files by name, type, or repo.

    Finds files in the knowledge base matching the given criteria.
    Useful for locating Terraform files, pipeline YAMLs, Helm charts, etc.

    Args:
        client: Client name (e.g. "dfin").
        query: Search pattern for file names/paths.
        file_type: File type filter (e.g. "terraform", "pipeline", "helm_values").
        repo: Repository name filter.
        branch: Optional branch filter.
        limit: Maximum results (default 25).
    """
    try:
        result = await _run_with_timeout(
            search_files,
            client=client,
            query=query,
            file_type=file_type,
            repo=repo,
            branch=branch,
            limit=limit,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_get_pipeline(
    client: str,
    name: str = None,
    file: str = None,
    repo: str = None,
    branch: str = None,
) -> str:
    """Deep-parse a Harness pipeline YAML.

    Retrieves and parses a pipeline definition, extracting stages, steps,
    template references, service references, environment bindings,
    variables, connectors, triggers, and approval gates.

    Args:
        client: Client name (e.g. "dfin").
        name: Pipeline name or identifier to find.
        file: Exact file path of the pipeline YAML.
        repo: Repository name to search in.
        branch: Optional branch filter.
    """
    try:
        result = await _run_with_timeout(
            get_pipeline,
            client=client,
            name=name,
            file=file,
            repo=repo,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_get_secret_flow(
    client: str,
    secret: str,
    branch: str = None,
) -> str:
    """Trace the full lifecycle of a secret.

    Follows a secret from creation in Key Vault -> Kubernetes secret ->
    Helm mount -> consuming service pod. Returns the complete chain with
    file paths at each stage.

    Use this for any question about secrets, credentials, Key Vault,
    or secret rotation.

    Args:
        client: Client name (e.g. "dfin").
        secret: Secret name to trace (e.g. "automation-dev-dbauditservice").
        branch: Optional branch filter.
    """
    try:
        result = await _run_with_timeout(
            get_secret_flow,
            client=client,
            secret=secret,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_impact_analysis(
    client: str,
    file: str = None,
    entity: str = None,
    repo: str = None,
    branch: str = None,
    depth: int = 3,
) -> str:
    """Assess the blast radius of changing an entity or file.

    Finds all direct and transitive dependents of a given entity or file,
    classifies risk level (LOW/MEDIUM/HIGH/CRITICAL), and lists affected
    services and environments.

    Use this BEFORE making changes to understand impact.

    Args:
        client: Client name (e.g. "dfin").
        file: File path to analyse (provide file or entity, not both).
        entity: Entity name to analyse.
        repo: Repository name filter.
        branch: Optional branch filter.
        depth: Traversal depth for transitive dependencies (default 3).
    """
    try:
        result = await _run_with_timeout(
            impact_analysis,
            client=client,
            file=file,
            entity=entity,
            repo=repo,
            branch=branch,
            depth=depth,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_diff_branches(
    client: str,
    repo: str,
    base: str,
    compare: str,
) -> str:
    """Compare two branches of a repository.

    Shows files added, modified, and deleted between the base and compare
    branches, categorised by file type.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name.
        base: Base branch name (e.g. "main").
        compare: Compare branch name (e.g. "release_26_3").
    """
    try:
        result = await _run_with_timeout(
            diff_branches,
            client=client,
            repo=repo,
            base=base,
            compare=compare,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_list_branches(
    client: str,
    repo: str = "all",
) -> str:
    """List indexed branches for a client's repositories.

    Shows all branches with their tier classification (production,
    integration, release, feature), last commit time, and indexing status.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name, or "all" for all repos (default "all").
    """
    try:
        result = await _run_with_timeout(
            list_branches,
            client=client,
            repo=repo,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_set_client(
    client: str,
) -> str:
    """Switch the active client context.

    Sets the active client for all subsequent tool calls. Validates that
    the client configuration exists.

    Args:
        client: Client name to activate (e.g. "dfin").
    """
    try:
        result = await _run_with_timeout(
            set_active_client,
            client=client,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_write_file(
    client: str,
    repo_name: str,
    branch: str,
    file_path: str,
    content: str,
    intent: str = "",
) -> str:
    """Write a file to a repository with branch protection.

    Creates or updates a file in a local repo clone. Automatically creates
    a working branch if the target is a protected branch (main, release_*,
    etc.) — never writes directly to protected branches.

    Args:
        client: Client name (e.g. "dfin").
        repo_name: Repository name.
        branch: Target branch name.
        file_path: Path within the repo for the file.
        content: File content to write.
        intent: Optional description of the change intent.
    """
    try:
        result = await _run_with_timeout(
            write_file,
            client=client,
            repo_name=repo_name,
            branch=branch,
            file_path=file_path,
            content=content,
            intent=intent,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_save_investigation(
    client: str,
    service_name: str,
    incident_type: str,
    root_cause_summary: str,
    resolution: str,
    files_cited: str = "[]",
    tags: str = "",
) -> str:
    """Save a completed investigation to memory for future recall.

    Call ONLY when the user explicitly asks to save or remember the
    investigation (e.g. "save this investigation", "remember the fix").
    Never auto-save.

    Args:
        client: Client name (e.g. "dfin").
        service_name: Primary service investigated.
        incident_type: One of: CrashLoopBackOff, OOMKilled, SecretMount,
            ProbeFailure, PipelineFailure, InfraFailure, AppStartup,
            NetworkPolicy, ImagePull, Unknown.
        root_cause_summary: 2-3 sentence factual summary of root cause.
        resolution: What fix was applied or recommended.
        files_cited: JSON string — list of {file_path, repo, branch, relevance}.
        tags: Comma-separated searchable tags (e.g. "keyvault,spring-boot").
    """
    try:
        parsed_files = []
        if files_cited:
            try:
                parsed_files = json.loads(files_cited)
            except (json.JSONDecodeError, TypeError):
                parsed_files = []

        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else []

        result = await _run_with_timeout(
            save_investigation,
            client=client,
            service_name=service_name,
            incident_type=incident_type,
            root_cause_summary=root_cause_summary,
            resolution=resolution,
            files_cited=parsed_files,
            tags=parsed_tags,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_recall_investigation(
    client: str,
    query: str,
    service_name: str = None,
    incident_type: str = None,
    top_k: int = 3,
) -> str:
    """Search past saved investigations for similar incidents.

    Use when the user says 'have we seen this before', 'similar issue',
    'last time this happened', or 'recall'. Also use at the start of
    any new investigation to check for prior art.

    Args:
        client: Client name (e.g. "dfin").
        query: Natural language search query.
        service_name: Optional exact-match filter on service name.
        incident_type: Optional exact-match filter on incident type.
        top_k: Number of results to return (default 3).
    """
    try:
        result = await _run_with_timeout(
            recall_investigation,
            client=client,
            query=query,
            service_name=service_name,
            incident_type=incident_type,
            top_k=top_k,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_read_file(
    client: str,
    repo: str,
    file_path: str,
    branch: str = None,
) -> str:
    """Read actual file content from a repo.

    Searches the HiveMind KB first for chunk coverage, then reads from
    disk for complete content.  Use BEFORE proposing any edits — always
    read before writing.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name (e.g. "dfin-harness-pipelines").
        file_path: Path within the repo (e.g. "newad/cd/cd_deploy_env/pipeline.yaml").
        branch: Optional branch to read from (uses git show).
    """
    try:
        result = await _run_with_timeout(
            read_file,
            client=client,
            repo=repo,
            file_path=file_path,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_propose_edit(
    client: str,
    repo: str,
    file_path: str,
    branch: str,
    description: str,
    proposed_changes: str,
    auto_apply: bool = False,
) -> str:
    """Propose or apply an edit to a file in a repo.

    Auto-applies to non-protected branches (never commits or pushes).
    Always reads the file first and shows a diff preview.
    NEVER use on main/release/hotfix branches.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name.
        file_path: Path within the repo.
        branch: Target branch for the edit.
        description: Human-readable description of the edit.
        proposed_changes: The new file content (full replacement).
        auto_apply: If True and branch is safe, write to disk (default False).
    """
    try:
        result = await _run_with_timeout(
            propose_edit,
            client=client,
            repo=repo,
            file_path=file_path,
            branch=branch,
            description=description,
            proposed_changes=proposed_changes,
            auto_apply=auto_apply,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_check_branch(
    client: str,
    repo: str,
    branch: str,
) -> str:
    """Check if a branch is indexed and/or exists on remote.

    Always call this BEFORE any branch-specific investigation, comparison,
    or analysis. Returns whether the branch is indexed in HiveMind,
    whether it exists on the remote repo, and suggests the closest
    indexed branch if not indexed.

    Args:
        client: Client name (e.g. "dfin").
        repo: Repository name (e.g. "Eastwood-terraform").
        branch: Branch name to check (e.g. "release_26_1").
    """
    try:
        result = await _run_with_timeout(
            check_branch,
            client=client,
            repo=repo,
            branch=branch,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_get_active_client() -> str:
    """Get the currently active client name.

    Reads from memory/active_client.txt. Call this FIRST before any other
    tool to know which client context to use.

    Returns the client name string, or an error if no client is configured.
    """
    try:
        if ACTIVE_CLIENT_FILE.exists():
            client = ACTIVE_CLIENT_FILE.read_text(encoding="utf-8").strip()
            if client:
                return json.dumps({"client": client})
            return json.dumps({"error": "active_client.txt is empty. Run set_client first."})
        return json.dumps({"error": "No active_client.txt found. Run set_client first."})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_get_active_branch() -> str:
    """Get the currently active branch.

    Reads from memory/active_branch.txt. Use this to know which branch
    context is active for the current workspace.

    Returns the branch name string.
    """
    try:
        if ACTIVE_BRANCH_FILE.exists():
            branch = ACTIVE_BRANCH_FILE.read_text(encoding="utf-8").strip()
            if branch:
                return json.dumps({"branch": branch})
            return json.dumps({"error": "active_branch.txt is empty."})
        return json.dumps({"error": "No active_branch.txt found."})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_ensure_fresh(
    client: str,
    repos: str = None,
    branches: str = None,
) -> str:
    """Pre-flight freshness check: compare local sync state against remote HEAD.

    If any branch is stale, automatically runs incremental sync before
    returning.  Fast (~1-2s) if everything is fresh.  Safe — only reads
    remote refs and never pushes.  Network failures are warnings, not errors.

    Call this FIRST at the start of every investigation to ensure the KB
    has the latest data.

    Args:
        client: Client name (e.g. "dfin").
        repos: Optional comma-separated repo names to check (default: all).
        branches: Optional comma-separated branch names to check (default: all).
    """
    try:
        repo_list = [r.strip() for r in repos.split(",") if r.strip()] if repos else None
        branch_list = [b.strip() for b in branches.split(",") if b.strip()] if branches else None

        result = await _run_with_timeout(
            check_and_sync_if_stale,
            client=client,
            repos=repo_list,
            branches=branch_list,
            auto_sync=True,
            timeout=180,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e), "message": "Freshness check failed — proceeding with cached data."})


@mcp_server.tool()
async def hivemind_hti_get_skeleton(
    client: str,
    repo: str = "all",
    file_type: str = "all",
    file_path: str = None,
    branch: str = None,
    max_skeletons: int = 50,
) -> str:
    """Get the structural skeleton of YAML/HCL infrastructure files
    for reasoning-based retrieval. Returns a compact JSON tree showing file
    structure (keys, paths, metadata) without full values. Use this when you
    need to find specific structural elements like pipeline stages, Terraform
    modules, Helm values, or approval gates. After receiving the skeleton,
    identify the node_paths that likely contain the answer, then call
    hivemind_hti_fetch_nodes to get the full content.

    Args:
        client: Client name (e.g. "dfin"). Call get_active_client to find this.
        repo: Repository name, or "all" for all repos (default "all").
        file_type: Filter by type: "harness", "terraform", "helm", "generic", or "all".
        file_path: Optional specific file path to look up.
        branch: Optional branch filter.
        max_skeletons: Maximum number of skeleton files to return (default 50).
    """
    try:
        def _get_skeletons():
            conn = get_hti_connection(client)
            cursor = conn.cursor()

            query = "SELECT id, file_path, repo, branch, file_type, node_count, skeleton_json FROM hti_skeletons WHERE client = ?"
            params = [client]

            if repo != "all":
                query += " AND repo = ?"
                params.append(repo)

            if file_type != "all":
                query += " AND file_type = ?"
                params.append(file_type)

            if file_path:
                query += " AND file_path LIKE ?"
                params.append(f"%{file_path}%")

            if branch:
                query += " AND branch = ?"
                params.append(branch)

            query += " ORDER BY indexed_at DESC LIMIT ?"
            params.append(max_skeletons)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Get total count for this filter
            count_query = "SELECT COUNT(*) FROM hti_skeletons WHERE client = ?"
            count_params = [client]
            if repo != "all":
                count_query += " AND repo = ?"
                count_params.append(repo)
            if file_type != "all":
                count_query += " AND file_type = ?"
                count_params.append(file_type)
            if file_path:
                count_query += " AND file_path LIKE ?"
                count_params.append(f"%{file_path}%")
            if branch:
                count_query += " AND branch = ?"
                count_params.append(branch)

            cursor.execute(count_query, count_params)
            total = cursor.fetchone()[0]

            conn.close()

            skeletons = []
            for row in rows:
                skeletons.append({
                    "skeleton_id": row[0],
                    "file_path": row[1],
                    "repo": row[2],
                    "branch": row[3],
                    "file_type": row[4],
                    "node_count": row[5],
                    "skeleton": json.loads(row[6]),
                })

            return {
                "skeletons": skeletons,
                "total_found": total,
                "returned": len(skeletons),
                "usage_hint": "Identify node_paths from the skeletons above, then call hivemind_hti_fetch_nodes",
            }

        result = await _run_with_timeout(_get_skeletons)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
async def hivemind_hti_fetch_nodes(
    skeleton_id: str,
    node_paths: str,
) -> str:
    """Fetch full content of specific nodes from YAML/HCL files by
    node path. Call this after hivemind_hti_get_skeleton — provide the
    node_paths you identified from the skeleton. Returns complete subtree
    content at each path with full values, ready to answer the original query.

    Args:
        skeleton_id: Skeleton ID from hivemind_hti_get_skeleton result.
        node_paths: Comma-separated list of node paths to fetch,
                    e.g. "root.pipeline.stages[2],root.pipeline.variables".
    """
    try:
        def _fetch_nodes():
            # Parse skeleton_id to get client
            parts = skeleton_id.split(":", 3)
            if len(parts) < 4:
                return {"error": f"Invalid skeleton_id format: {skeleton_id}"}

            client = parts[0]
            conn = get_hti_connection(client)
            cursor = conn.cursor()

            # Get skeleton metadata
            cursor.execute(
                "SELECT file_path, repo, branch FROM hti_skeletons WHERE id = ?",
                (skeleton_id,),
            )
            skel_row = cursor.fetchone()
            if not skel_row:
                conn.close()
                return {"error": f"Skeleton not found: {skeleton_id}"}

            file_path, repo, branch = skel_row

            # Parse requested paths
            requested = [p.strip() for p in node_paths.split(",") if p.strip()]

            found_nodes = []
            missing_paths = []

            for req_path in requested:
                cursor.execute(
                    "SELECT node_path, depth, content_json FROM hti_nodes WHERE skeleton_id = ? AND node_path = ?",
                    (skeleton_id, req_path),
                )
                row = cursor.fetchone()
                if row:
                    found_nodes.append({
                        "node_path": row[0],
                        "depth": row[1],
                        "content": json.loads(row[2]),
                        "found": True,
                    })
                else:
                    # Try prefix match for partial paths
                    cursor.execute(
                        "SELECT node_path, depth, content_json FROM hti_nodes WHERE skeleton_id = ? AND node_path LIKE ? ORDER BY depth LIMIT 1",
                        (skeleton_id, f"{req_path}%"),
                    )
                    prefix_row = cursor.fetchone()
                    if prefix_row:
                        found_nodes.append({
                            "node_path": prefix_row[0],
                            "depth": prefix_row[1],
                            "content": json.loads(prefix_row[2]),
                            "found": True,
                            "matched_via": "prefix",
                        })
                    else:
                        missing_paths.append(req_path)
                        found_nodes.append({
                            "node_path": req_path,
                            "depth": -1,
                            "content": None,
                            "found": False,
                        })

            conn.close()

            return {
                "file_path": file_path,
                "repo": repo,
                "branch": branch,
                "nodes": found_nodes,
                "missing_paths": missing_paths,
            }

        result = await _run_with_timeout(_fetch_nodes)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Hawkeye Pipeline Observability Tools (MCP-to-MCP bridge)
# ---------------------------------------------------------------------------
# These tools proxy calls to the Hawkeye MCP server running as a subprocess.
# Hawkeye connects to Harness APIs to fetch pipeline execution data, logs,
# and investigation results.  Each tool here is a thin async wrapper.
# ---------------------------------------------------------------------------

@mcp_server.tool()
async def hivemind_hawkeye_diagnose(
    url: str = "",
    execution_id: str = "",
    mode: str = "full",
    include_logs: bool = True,
) -> str:
    """Unified pipeline diagnosis — single-call failure investigation via Hawkeye.

    Accepts a Harness UI URL (preferred — just paste the URL) or an execution_id.
    Fetches full execution detail, failed stages/steps, console logs, pipeline
    history, and synthesizes a failure analysis.

    Modes:
    - mode="summary": Execution overview, failed stage/step identification, quick analysis.
    - mode="full": Everything from summary PLUS step details, child pipeline following,
      rollback detection, console logs, and deep links.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID (alternative to URL).
        mode: "summary" or "full" (default: "full").
        include_logs: Include console logs in full mode (default: True).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_diagnose", {
        "url": url, "execution_id": execution_id,
        "mode": mode, "include_logs": include_logs,
    })


@mcp_server.tool()
async def hivemind_hawkeye_investigate_failure(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Deep failure triage with parallel data gathering via Hawkeye.

    Fires MULTIPLE API calls in parallel: full execution detail, execution graph,
    step logs for ALL failed steps, and last 5 executions of the same pipeline.
    Synthesizes everything into a unified failure investigation report.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID (alternative to URL).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_investigate_failure", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_execution(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Get full pipeline execution details — status, stages, failures, and deep link.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID (alternative to URL).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_execution", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_stage_detail(
    url: str = "",
    execution_id: str = "",
    stage_id: str = "",
) -> str:
    """Get detailed step-by-step breakdown of a pipeline stage.

    Args:
        url: Harness UI URL with stage param (preferred).
        execution_id: Pipeline execution ID.
        stage_id: Stage identifier.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_stage_detail", {
        "url": url, "execution_id": execution_id, "stage_id": stage_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_step_logs(
    url: str = "",
    execution_id: str = "",
    stage_id: str = "",
    step_id: str = "",
) -> str:
    """Get detailed step execution information including script source, outputs, and failures.

    Args:
        url: Harness UI URL with stage and step params (preferred).
        execution_id: Pipeline execution ID.
        stage_id: Stage identifier.
        step_id: Step identifier.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_step_logs", {
        "url": url, "execution_id": execution_id,
        "stage_id": stage_id, "step_id": step_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_execution_inputs(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Get the runtime input YAML used for a specific pipeline execution.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_execution_inputs", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_list_recent_executions(
    pipeline_id: str,
    limit: int = 10,
    status: str = "",
) -> str:
    """List recent pipeline executions with optional status filter.

    Args:
        pipeline_id: Pipeline identifier (supports fuzzy matching).
        limit: Maximum number of executions to return (default: 10).
        status: Filter by status (e.g., "Failed", "Success"). Empty for all.
    """
    bridge = get_bridge()
    args: dict = {"pipeline_id": pipeline_id, "limit": limit}
    if status:
        args["status"] = status
    return await bridge.call_tool("hawkeye_list_recent_executions", args)


@mcp_server.tool()
async def hivemind_hawkeye_get_all_stages(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Get all stages with steps in one call for a pipeline execution.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_all_stages", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_child_execution(
    url: str = "",
    execution_id: str = "",
    stage_id: str = "",
) -> str:
    """Follow child pipeline executions from a parent pipeline stage.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Parent pipeline execution ID.
        stage_id: Stage that triggered the child pipeline.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_child_execution", {
        "url": url, "execution_id": execution_id, "stage_id": stage_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_check_approvals(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Check pending, completed, or rejected approval gates in a pipeline execution.

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_check_approvals", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_compare_executions(
    execution_id_1: str,
    execution_id_2: str,
) -> str:
    """Diff two pipeline executions — compare stages, steps, and outcomes.

    Args:
        execution_id_1: First execution ID.
        execution_id_2: Second execution ID.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_compare_executions", {
        "execution_id_1": execution_id_1, "execution_id_2": execution_id_2,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_failure_pattern(
    pipeline_id: str,
    limit: int = 10,
) -> str:
    """Detect recurring failure patterns across recent pipeline executions.

    Args:
        pipeline_id: Pipeline identifier (supports fuzzy matching).
        limit: Number of recent executions to analyze (default: 10).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_failure_pattern", {
        "pipeline_id": pipeline_id, "limit": limit,
    })


@mcp_server.tool()
async def hivemind_hawkeye_get_pipeline_definition(
    pipeline_id: str,
    branch: str = "",
) -> str:
    """Get the YAML definition of a pipeline.

    Args:
        pipeline_id: Pipeline identifier (supports fuzzy matching).
        branch: Git branch for remote pipelines (optional).
    """
    bridge = get_bridge()
    args: dict = {"pipeline_id": pipeline_id}
    if branch:
        args["branch"] = branch
    return await bridge.call_tool("hawkeye_get_pipeline_definition", args)


@mcp_server.tool()
async def hivemind_hawkeye_list_pipelines(
    search: str = "",
    module: str = "",
) -> str:
    """List all pipelines in the current Harness project.

    Args:
        search: Search term to filter pipelines by name.
        module: Filter by module ("CI" or "CD").
    """
    bridge = get_bridge()
    args: dict = {}
    if search:
        args["search"] = search
    if module:
        args["module"] = module
    return await bridge.call_tool("hawkeye_list_pipelines", args)


@mcp_server.tool()
async def hivemind_hawkeye_get_input_sets(
    pipeline_id: str,
) -> str:
    """Get all available input sets for a pipeline.

    Args:
        pipeline_id: Pipeline identifier (supports fuzzy matching).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_get_input_sets", {
        "pipeline_id": pipeline_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_connect_account(
    profile_name: str,
) -> str:
    """Switch the active Hawkeye/Harness profile and test connectivity.

    Tokens must be pre-configured via 'make connect' in the Hawkeye project.
    This tool only switches between pre-configured profiles.

    Args:
        profile_name: Name of the profile to activate.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_connect_account", {
        "profile_name": profile_name,
    })


@mcp_server.tool()
async def hivemind_hawkeye_list_profiles() -> str:
    """List all configured Hawkeye/Harness profiles with active indicator."""
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_list_profiles", {})


@mcp_server.tool()
async def hivemind_hawkeye_list_delegates() -> str:
    """List all Harness delegate groups with health status.

    Returns delegate name, connection status, last heartbeat, type, and tags.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_list_delegates", {})


@mcp_server.tool()
async def hivemind_hawkeye_check_delegate(
    name: str,
) -> str:
    """Check health of a specific Harness delegate by name (supports fuzzy matching).

    Args:
        name: Full or partial delegate name (e.g., "tanr" for "newad-eswd-tanr-dlgt").
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_check_delegate", {"name": name})


@mcp_server.tool()
async def hivemind_hawkeye_list_connectors(
    search: str = "",
) -> str:
    """List Harness connectors with their connectivity status.

    Args:
        search: Search term to filter connectors by name.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_list_connectors", {
        "search": search,
    })


@mcp_server.tool()
async def hivemind_hawkeye_check_connector(
    identifier: str,
) -> str:
    """Test connectivity of a specific Harness connector.

    Args:
        identifier: Connector identifier (e.g., "account.GHConnector" or project-scoped ID).
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_check_connector", {
        "identifier": identifier,
    })


@mcp_server.tool()
async def hivemind_hawkeye_build_link(
    pipeline_id: str,
    execution_id: str = "",
    stage_id: str = "",
    step_id: str = "",
) -> str:
    """Build a Harness deep link URL from pipeline/execution/stage/step components.

    Args:
        pipeline_id: Pipeline identifier.
        execution_id: Execution ID (optional — omit for pipeline-level link).
        stage_id: Stage ID (optional).
        step_id: Step ID (optional).
    """
    bridge = get_bridge()
    args: dict = {"pipeline_id": pipeline_id}
    if execution_id:
        args["execution_id"] = execution_id
    if stage_id:
        args["stage_id"] = stage_id
    if step_id:
        args["step_id"] = step_id
    return await bridge.call_tool("hawkeye_build_link", args)


@mcp_server.tool()
async def hivemind_hawkeye_parse_terraform_plan(
    url: str = "",
    execution_id: str = "",
) -> str:
    """Parse Terraform plan output from a pipeline execution.

    Extracts plan summary per layer (X to add, Y to change, Z to destroy).

    Args:
        url: Harness UI URL (preferred).
        execution_id: Pipeline execution ID.
    """
    bridge = get_bridge()
    return await bridge.call_tool("hawkeye_parse_terraform_plan", {
        "url": url, "execution_id": execution_id,
    })


@mcp_server.tool()
async def hivemind_hawkeye_release_precheck_report(
    infra_builder_execution_id: str,
    infra_createenv_execution_id: str,
    branch: str = "",
) -> str:
    """Generate a combined release precheck report from two pipeline executions.

    Args:
        infra_builder_execution_id: Infra builder pipeline execution ID.
        infra_createenv_execution_id: Infra create-env pipeline execution ID.
        branch: Release branch name (optional, for context).
    """
    bridge = get_bridge()
    args: dict = {
        "infra_builder_execution_id": infra_builder_execution_id,
        "infra_createenv_execution_id": infra_createenv_execution_id,
    }
    if branch:
        args["branch"] = branch
    return await bridge.call_tool("hawkeye_release_precheck_report", args)


@mcp_server.tool()
async def hivemind_hawkeye_ping() -> str:
    """Health check — verify Hawkeye MCP server is running and connected."""
    bridge = get_bridge()
    return await bridge.call_tool("ping", {})


# ---------------------------------------------------------------------------
TOOL_REGISTRY = {
    "hivemind_query_memory": hivemind_query_memory,
    "hivemind_query_graph": hivemind_query_graph,
    "hivemind_get_entity": hivemind_get_entity,
    "hivemind_search_files": hivemind_search_files,
    "hivemind_get_pipeline": hivemind_get_pipeline,
    "hivemind_get_secret_flow": hivemind_get_secret_flow,
    "hivemind_impact_analysis": hivemind_impact_analysis,
    "hivemind_diff_branches": hivemind_diff_branches,
    "hivemind_list_branches": hivemind_list_branches,
    "hivemind_set_client": hivemind_set_client,
    "hivemind_write_file": hivemind_write_file,
    "hivemind_get_active_client": hivemind_get_active_client,
    "hivemind_get_active_branch": hivemind_get_active_branch,
    "hivemind_read_file": hivemind_read_file,
    "hivemind_propose_edit": hivemind_propose_edit,
    "hivemind_check_branch": hivemind_check_branch,
    "hivemind_ensure_fresh": hivemind_ensure_fresh,
    "hivemind_save_investigation": hivemind_save_investigation,
    "hivemind_recall_investigation": hivemind_recall_investigation,
    "hivemind_hti_get_skeleton": hivemind_hti_get_skeleton,
    "hivemind_hti_fetch_nodes": hivemind_hti_fetch_nodes,
    # Hawkeye pipeline observability tools (MCP-to-MCP bridge)
    "hivemind_hawkeye_diagnose": hivemind_hawkeye_diagnose,
    "hivemind_hawkeye_investigate_failure": hivemind_hawkeye_investigate_failure,
    "hivemind_hawkeye_get_execution": hivemind_hawkeye_get_execution,
    "hivemind_hawkeye_get_stage_detail": hivemind_hawkeye_get_stage_detail,
    "hivemind_hawkeye_get_step_logs": hivemind_hawkeye_get_step_logs,
    "hivemind_hawkeye_get_execution_inputs": hivemind_hawkeye_get_execution_inputs,
    "hivemind_hawkeye_list_recent_executions": hivemind_hawkeye_list_recent_executions,
    "hivemind_hawkeye_get_all_stages": hivemind_hawkeye_get_all_stages,
    "hivemind_hawkeye_get_child_execution": hivemind_hawkeye_get_child_execution,
    "hivemind_hawkeye_check_approvals": hivemind_hawkeye_check_approvals,
    "hivemind_hawkeye_compare_executions": hivemind_hawkeye_compare_executions,
    "hivemind_hawkeye_get_failure_pattern": hivemind_hawkeye_get_failure_pattern,
    "hivemind_hawkeye_get_pipeline_definition": hivemind_hawkeye_get_pipeline_definition,
    "hivemind_hawkeye_list_pipelines": hivemind_hawkeye_list_pipelines,
    "hivemind_hawkeye_get_input_sets": hivemind_hawkeye_get_input_sets,
    "hivemind_hawkeye_connect_account": hivemind_hawkeye_connect_account,
    "hivemind_hawkeye_list_profiles": hivemind_hawkeye_list_profiles,
    "hivemind_hawkeye_list_delegates": hivemind_hawkeye_list_delegates,
    "hivemind_hawkeye_check_delegate": hivemind_hawkeye_check_delegate,
    "hivemind_hawkeye_list_connectors": hivemind_hawkeye_list_connectors,
    "hivemind_hawkeye_check_connector": hivemind_hawkeye_check_connector,
    "hivemind_hawkeye_build_link": hivemind_hawkeye_build_link,
    "hivemind_hawkeye_parse_terraform_plan": hivemind_hawkeye_parse_terraform_plan,
    "hivemind_hawkeye_release_precheck_report": hivemind_hawkeye_release_precheck_report,
    "hivemind_hawkeye_ping": hivemind_hawkeye_ping,
}


# Expected tool counts
_HIVEMIND_TOOL_COUNT = 21
_HAWKEYE_TOOL_COUNT = 25
_TOTAL_TOOL_COUNT = _HIVEMIND_TOOL_COUNT + _HAWKEYE_TOOL_COUNT


def run_self_test() -> bool:
    """Validate all tool imports and registrations.

    Returns True if all tools are healthy, False otherwise.
    Prints status for each tool.
    """
    print("HiveMind MCP Server — Self Test")
    print("=" * 50)

    all_ok = True
    hivemind_tools = sorted(k for k in TOOL_REGISTRY if not k.startswith("hivemind_hawkeye_"))
    hawkeye_tools = sorted(k for k in TOOL_REGISTRY if k.startswith("hivemind_hawkeye_"))

    print(f"\n  HiveMind core tools ({len(hivemind_tools)}/{_HIVEMIND_TOOL_COUNT}):")
    for name in hivemind_tools:
        fn = TOOL_REGISTRY[name]
        if callable(fn):
            print(f"    [OK] {name}")
        else:
            print(f"    [FAIL] {name} — not callable")
            all_ok = False

    print(f"\n  Hawkeye bridge tools ({len(hawkeye_tools)}/{_HAWKEYE_TOOL_COUNT}):")
    for name in hawkeye_tools:
        fn = TOOL_REGISTRY[name]
        if callable(fn):
            print(f"    [OK] {name}")
        else:
            print(f"    [FAIL] {name} — not callable")
            all_ok = False

    registered_count = len(TOOL_REGISTRY)
    print()
    print(f"Tools registered: {registered_count}/{_TOTAL_TOOL_COUNT}")

    if registered_count == _TOTAL_TOOL_COUNT and all_ok:
        print("All tools healthy.")
        return True
    else:
        print("SOME TOOLS FAILED.")
        return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="HiveMind MCP Server")
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run self-test and exit (validates all tool imports)",
    )
    args = parser.parse_args()

    if args.test:
        success = run_self_test()
        sys.exit(0 if success else 1)

    # Run as stdio MCP server
    mcp_server.run(transport="stdio")


if __name__ == "__main__":
    main()
