"""
Benchmark Evaluator — Automated scoring of benchmark results

Applies validators to tool results and computes scores (0-3) per question.

Scoring rubric:
    3 = no errors + results found + file citations present + content matches
    2 = no errors + results found + content matches (but missing file path)
    1 = results found but incomplete (partial matches or errors in some tools)
    0 = no results, all errors, or no content matches at all
"""

import json
import re


def _check_no_error(result: dict) -> bool:
    """Return True if no tool in the result set returned a hard error."""
    for tr in result.get("tool_results", []):
        if tr.get("error"):
            return False
        raw = tr.get("result")
        if isinstance(raw, dict) and raw.get("error"):
            # "Multiple matches" from get_entity is informational, not a failure
            err_msg = str(raw["error"])
            if "Multiple matches" in err_msg:
                continue
            return False
    return True


def _check_has_results(result: dict) -> bool:
    """Return True if at least one tool returned non-trivial results."""
    for tr in result.get("tool_results", []):
        raw = tr.get("result")
        if raw is None:
            continue
        if isinstance(raw, dict):
            if raw.get("error"):
                continue
            # Check for non-empty content indicators
            for key in ("results", "skeletons", "nodes", "affected_entities",
                        "outbound", "inbound", "files", "matches",
                        "entity", "pipeline", "chains"):
                val = raw.get(key)
                if val and (isinstance(val, list) and len(val) > 0
                            or isinstance(val, dict) and len(val) > 0):
                    return True
            # If it has meaningful keys beyond just "error"
            meaningful = {k for k in raw if k not in ("error", "summary") and raw[k]}
            if meaningful:
                return True
        elif isinstance(raw, str) and len(raw) > 20:
            return True
        elif isinstance(raw, list) and len(raw) > 0:
            return True
    return False


def _check_file_in_results(result: dict, pattern: str) -> bool:
    """Return True if a file path pattern appears in the accumulated text."""
    text = result.get("accumulated_text", "")
    return pattern.lower() in text.lower()


def _check_content_matches(result: dict, patterns: list[str]) -> bool:
    """Return True if ALL patterns appear in the accumulated text (case-insensitive)."""
    text = result.get("accumulated_text", "").lower()
    return all(p.lower() in text for p in patterns)


def _check_content_any(result: dict, patterns: list[str]) -> bool:
    """Return True if AT LEAST ONE pattern appears in the accumulated text."""
    text = result.get("accumulated_text", "").lower()
    return any(p.lower() in text for p in patterns)


def _check_result_count_gte(result: dict, threshold: int) -> bool:
    """Return True if result count metrics >= threshold."""
    text = result.get("accumulated_text", "")
    # Look for common count patterns in results
    for tr in result.get("tool_results", []):
        raw = tr.get("result")
        if isinstance(raw, dict):
            for key in ("total_found", "returned", "total"):
                if key in raw and isinstance(raw[key], (int, float)):
                    if raw[key] >= threshold:
                        return True
            # Count list lengths
            for key in ("results", "skeletons", "affected_entities",
                        "affected_files", "matches"):
                if key in raw and isinstance(raw[key], list):
                    if len(raw[key]) >= threshold:
                        return True
    return False


VALIDATOR_DISPATCH = {
    "no_error": lambda r, _: _check_no_error(r),
    "has_results": lambda r, _: _check_has_results(r),
    "file_in_results": lambda r, v: _check_file_in_results(r, v.get("value", "")),
    "content_matches": lambda r, v: _check_content_matches(r, v.get("patterns", [])),
    "content_any": lambda r, v: _check_content_any(r, v.get("patterns", [])),
    "result_count_gte": lambda r, v: _check_result_count_gte(r, v.get("threshold", 1)),
}


def evaluate_question(result: dict, question: dict) -> dict:
    """
    Evaluate a single question's tool results against its validators.

    Returns:
        {
            "id": "A1",
            "score": 3,
            "max_score": 3,
            "validator_results": [
                {"type": "no_error", "passed": True},
                {"type": "has_results", "passed": True},
                ...
            ],
            "notes": "All validators passed",
        }
    """
    validators = question.get("validators", [])
    validator_results = []

    for v in validators:
        vtype = v["type"]
        check_fn = VALIDATOR_DISPATCH.get(vtype)
        if check_fn:
            passed = check_fn(result, v)
        else:
            passed = False
        validator_results.append({
            "type": vtype,
            "passed": passed,
            "detail": v.get("value") or v.get("patterns") or v.get("threshold"),
        })

    # Compute score
    total_validators = len(validator_results)
    passed_count = sum(1 for vr in validator_results if vr["passed"])

    if total_validators == 0:
        score = 0
    elif passed_count == total_validators:
        score = 3  # All passed — full marks
    elif passed_count >= total_validators - 1:
        # Determine if the failure is file citation (score 2) or content (score 1)
        failed = [vr for vr in validator_results if not vr["passed"]]
        if all(f["type"] == "file_in_results" for f in failed):
            score = 2  # Correct content but missing file citation
        else:
            score = 2  # Most validators passed
    elif passed_count >= total_validators // 2:
        score = 1  # Partial correctness
    else:
        score = 0  # Mostly failed

    # Build notes
    if score == 3:
        notes = "All validators passed"
    elif score == 0:
        failed_types = [vr["type"] for vr in validator_results if not vr["passed"]]
        notes = f"Failed: {', '.join(failed_types)}"
    else:
        failed_types = [vr["type"] for vr in validator_results if not vr["passed"]]
        passed_types = [vr["type"] for vr in validator_results if vr["passed"]]
        notes = f"Passed: {', '.join(passed_types)} | Failed: {', '.join(failed_types)}"

    # Check for tool errors and add detail
    tool_errors = []
    for tr in result.get("tool_results", []):
        if tr.get("error"):
            tool_errors.append(f"{tr['tool']}: {tr['error']}")
    if tool_errors:
        notes += f" | Tool errors: {'; '.join(tool_errors)}"

    return {
        "id": question["id"],
        "category": question["category"],
        "question": question["question"],
        "score": score,
        "max_score": 3,
        "validator_results": validator_results,
        "notes": notes,
        "duration_ms": result.get("total_duration_ms", 0),
    }


def evaluate_all(results: list, questions: list) -> list:
    """
    Evaluate all benchmark results against their questions.

    Args:
        results: list of dicts from runner.run_all_questions()
        questions: list of question defs from questions.py

    Returns:
        list of evaluation dicts (one per question)
    """
    # Build lookup by ID
    result_by_id = {r["id"]: r for r in results}
    question_by_id = {q["id"]: q for q in questions}

    evaluations = []
    for qid in sorted(question_by_id.keys(), key=lambda x: (x[0], int(x[1:]))):
        result = result_by_id.get(qid)
        question = question_by_id[qid]
        if result:
            evaluations.append(evaluate_question(result, question))
        else:
            evaluations.append({
                "id": qid,
                "category": question["category"],
                "question": question["question"],
                "score": 0,
                "max_score": 3,
                "validator_results": [],
                "notes": "No result — question was not executed",
                "duration_ms": 0,
            })

    return evaluations
