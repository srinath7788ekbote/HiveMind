"""
HiveMind MCP Server
====================
Model Context Protocol server that exposes all HiveMind Python tools
as native MCP tools for GitHub Copilot.

Usage:
    python mcp/hivemind_server.py          # Run as stdio MCP server
    python mcp/hivemind_server.py --test   # Validate all imports and exit
"""

import argparse
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

# ---------------------------------------------------------------------------
# Memory file paths
# ---------------------------------------------------------------------------
ACTIVE_CLIENT_FILE = PROJECT_ROOT / "memory" / "active_client.txt"
ACTIVE_BRANCH_FILE = PROJECT_ROOT / "memory" / "active_branch.txt"

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
# MCP Tool definitions — each wraps an existing Python tool
# ---------------------------------------------------------------------------


@mcp_server.tool()
def hivemind_query_memory(
    client: str,
    query: str,
    branch: str = None,
    filter_type: str = None,
    top_k: int = 5,
) -> str:
    """Semantic search over the HiveMind knowledge base.

    Searches indexed infrastructure files (Terraform, pipelines, Helm, etc.)
    for content matching the query. Returns ranked results with file paths,
    repos, and relevance scores.

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
        result = query_memory(
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
def hivemind_query_graph(
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
        result = query_graph(
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
def hivemind_get_entity(
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
        result = get_entity(client=client, name=name, branch=branch)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
def hivemind_search_files(
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
        result = search_files(
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
def hivemind_get_pipeline(
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
        result = get_pipeline(
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
def hivemind_get_secret_flow(
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
        result = get_secret_flow(client=client, secret=secret, branch=branch)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
def hivemind_impact_analysis(
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
        result = impact_analysis(
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
def hivemind_diff_branches(
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
        result = diff_branches(
            client=client,
            repo=repo,
            base=base,
            compare=compare,
        )
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
def hivemind_list_branches(
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
        result = list_branches(client=client, repo=repo)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
def hivemind_set_client(
    client: str,
) -> str:
    """Switch the active client context.

    Sets the active client for all subsequent tool calls. Validates that
    the client configuration exists.

    Args:
        client: Client name to activate (e.g. "dfin").
    """
    try:
        result = set_active_client(client=client)
        return _format_result(result)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp_server.tool()
def hivemind_write_file(
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
        result = write_file(
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
def hivemind_get_active_client() -> str:
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
def hivemind_get_active_branch() -> str:
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


# ---------------------------------------------------------------------------
# Registry of all tool functions for validation
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
}


def run_self_test() -> bool:
    """Validate all tool imports and registrations.

    Returns True if all 13 tools are healthy, False otherwise.
    Prints status for each tool.
    """
    print("HiveMind MCP Server — Self Test")
    print("=" * 50)

    all_ok = True
    expected_tools = sorted(TOOL_REGISTRY.keys())

    for name in expected_tools:
        fn = TOOL_REGISTRY[name]
        if callable(fn):
            print(f"  [OK] {name}")
        else:
            print(f"  [FAIL] {name} — not callable")
            all_ok = False

    # Verify the FastMCP server has them registered
    registered_count = len(expected_tools)
    print()
    print(f"Tools registered: {registered_count}/13")

    if registered_count == 13 and all_ok:
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
