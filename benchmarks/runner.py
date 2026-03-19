"""
Benchmark Runner — Executes tool calls for each benchmark question

Calls HiveMind Python tools directly (not through MCP protocol) to measure
the quality of the knowledge base and tool infrastructure.

Two modes:
    1. Tool-level: Executes pre-defined tool sequences per question and
       evaluates the raw tool outputs (fully automated, no LLM needed).
    2. End-to-end: Sends questions to an LLM via the MCP server and
       evaluates the full response (requires an LLM endpoint).

This module implements mode 1 (tool-level).
"""

import json
import sys
import time
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import all HiveMind tools directly
from tools.query_memory import query_memory
from tools.query_graph import query_graph
from tools.get_entity import get_entity
from tools.search_files import search_files
from tools.get_pipeline import get_pipeline
from tools.get_secret_flow import get_secret_flow
from tools.impact_analysis import impact_analysis
from tools.diff_branches import diff_branches
from tools.list_branches import list_branches
from tools.check_branch import check_branch

# HTI imports
from hivemind_mcp.hti.utils import get_hti_connection

# Tool dispatch table — maps short names to callable functions
TOOL_DISPATCH = {
    "query_memory": query_memory,
    "query_graph": query_graph,
    "get_entity": get_entity,
    "search_files": search_files,
    "get_pipeline": get_pipeline,
    "get_secret_flow": get_secret_flow,
    "impact_analysis": impact_analysis,
    "diff_branches": diff_branches,
    "list_branches": list_branches,
    "check_branch": check_branch,
}


def _call_hti_get_skeleton(client: str, **kwargs) -> dict:
    """Call hti_get_skeleton directly via SQLite."""
    conn = get_hti_connection(client)
    cursor = conn.cursor()

    query = "SELECT id, file_path, repo, branch, file_type, node_count, skeleton_json FROM hti_skeletons WHERE client = ?"
    params = [client]

    repo = kwargs.get("repo", "all")
    if repo != "all":
        query += " AND repo = ?"
        params.append(repo)

    file_type = kwargs.get("file_type", "all")
    if file_type != "all":
        query += " AND file_type = ?"
        params.append(file_type)

    file_path = kwargs.get("file_path")
    if file_path:
        query += " AND file_path LIKE ?"
        params.append(f"%{file_path}%")

    branch = kwargs.get("branch")
    if branch:
        query += " AND branch = ?"
        params.append(branch)

    max_skeletons = kwargs.get("max_skeletons", 50)
    query += " ORDER BY indexed_at DESC LIMIT ?"
    params.append(max_skeletons)

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Total count
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
    }


def _call_hti_fetch_nodes(skeleton_id: str, node_paths: str) -> dict:
    """Call hti_fetch_nodes directly via SQLite."""
    parts = skeleton_id.split(":", 3)
    if len(parts) < 4:
        return {"error": f"Invalid skeleton_id format: {skeleton_id}"}

    client = parts[0]
    conn = get_hti_connection(client)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT file_path, repo, branch FROM hti_skeletons WHERE id = ?",
        (skeleton_id,),
    )
    skel_row = cursor.fetchone()
    if not skel_row:
        conn.close()
        return {"error": f"Skeleton not found: {skeleton_id}"}

    file_path, repo, branch = skel_row
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
            # Prefix match fallback
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


def _resolve_arg(value, context: dict):
    """Replace placeholder strings like $CLIENT, $SKELETON_ID."""
    if not isinstance(value, str):
        return value
    if value == "$CLIENT":
        return context.get("client", "dfin")
    if value == "$SKELETON_ID":
        return context.get("skeleton_id", "")
    return value


def run_question(question: dict, client: str) -> dict:
    """
    Execute all tool calls for a single benchmark question.

    Returns:
        {
            "id": "A1",
            "question": "...",
            "tool_results": [
                {"tool": "hti_get_skeleton", "result": {...}, "duration_ms": 123, "error": None},
                ...
            ],
            "accumulated_text": "... all results as text ...",
            "total_duration_ms": 456,
        }
    """
    context = {"client": client, "skeleton_id": ""}
    tool_results = []
    accumulated_text = ""
    total_start = time.time()

    for call in question["tool_calls"]:
        tool_name = call["tool"]
        raw_args = call.get("args", {})

        # Resolve placeholders
        resolved_args = {k: _resolve_arg(v, context) for k, v in raw_args.items()}

        start = time.time()
        result = None
        error = None

        try:
            if tool_name == "hti_get_skeleton":
                result = _call_hti_get_skeleton(**resolved_args)
                # Extract first skeleton_id for follow-up fetch_nodes calls
                if result and "skeletons" in result and result["skeletons"]:
                    context["skeleton_id"] = result["skeletons"][0]["skeleton_id"]

            elif tool_name == "hti_fetch_nodes":
                skeleton_id = resolved_args.get("skeleton_id", "")
                node_paths_str = resolved_args.get("node_paths", "")
                if skeleton_id:
                    result = _call_hti_fetch_nodes(skeleton_id, node_paths_str)
                else:
                    result = {"error": "No skeleton_id available (hti_get_skeleton may have returned no results)"}

            elif tool_name in TOOL_DISPATCH:
                fn = TOOL_DISPATCH[tool_name]
                result = fn(**resolved_args)

            else:
                result = {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            result = {"error": error}

        elapsed_ms = int((time.time() - start) * 1000)

        # Convert result to text for accumulation
        result_text = ""
        if isinstance(result, str):
            result_text = result
        elif isinstance(result, dict):
            result_text = json.dumps(result, indent=2, default=str)
        elif isinstance(result, list):
            result_text = json.dumps(result, indent=2, default=str)
        else:
            result_text = str(result)

        accumulated_text += f"\n--- {tool_name} ---\n{result_text}\n"

        tool_results.append({
            "tool": tool_name,
            "args": resolved_args,
            "result": result,
            "result_text": result_text,
            "duration_ms": elapsed_ms,
            "error": error,
        })

    total_duration_ms = int((time.time() - total_start) * 1000)

    return {
        "id": question["id"],
        "category": question["category"],
        "question": question["question"],
        "tool_results": tool_results,
        "accumulated_text": accumulated_text,
        "total_duration_ms": total_duration_ms,
    }


def run_all_questions(questions: list, client: str, verbose: bool = False) -> list:
    """
    Execute all benchmark questions sequentially.

    Returns a list of result dicts (one per question).
    """
    results = []
    total = len(questions)

    for i, question in enumerate(questions, 1):
        qid = question["id"]
        if verbose:
            print(f"  [{i}/{total}] Running {qid}: {question['question'][:60]}...", flush=True)

        try:
            result = run_question(question, client)
            results.append(result)
            if verbose:
                status = "OK" if not any(
                    tr.get("error") for tr in result["tool_results"]
                ) else "ERR"
                print(f"           {status} ({result['total_duration_ms']}ms)", flush=True)
        except Exception as e:
            results.append({
                "id": qid,
                "category": question["category"],
                "question": question["question"],
                "tool_results": [],
                "accumulated_text": f"RUNNER ERROR: {e}\n{traceback.format_exc()}",
                "total_duration_ms": 0,
            })
            if verbose:
                print(f"           FATAL: {e}", flush=True)

    return results
