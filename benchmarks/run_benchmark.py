"""
run_benchmark.py — HiveMind Automated Benchmark Runner

Executes all 30 benchmark questions against the live knowledge base,
evaluates tool outputs, and generates a scored report.

Usage:
    python benchmarks/run_benchmark.py                          # Run all
    python benchmarks/run_benchmark.py --category A             # Only HTI questions
    python benchmarks/run_benchmark.py --category B             # Only broad search
    python benchmarks/run_benchmark.py --category C             # Only cross-repo
    python benchmarks/run_benchmark.py --question A1            # Single question
    python benchmarks/run_benchmark.py --client dfin            # Specify client
    python benchmarks/run_benchmark.py --verbose                # Show progress
    python benchmarks/run_benchmark.py --json                   # Output raw JSON
    python benchmarks/run_benchmark.py --output results.md      # Save report to file
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.runner import run_all_questions
from benchmarks.evaluator import evaluate_all


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

CATEGORY_NAMES = {
    "A_HTI_Structural": "A: HTI Structural Queries",
    "B_Broad_Search": "B: ChromaDB/BM25 Broad Search",
    "C_Cross_Repo": "C: Cross-repo Dependencies",
    # v2 categories
    "A_Deep_Structural": "A: Deep Structural Queries",
    "B_Cross_Repo_Search": "B: Cross-Repo Search",
    "C_Multi_Signal": "C: Multi-Signal Reasoning",
}

CATEGORY_TARGETS = {
    "A_HTI_Structural": "88-95%",
    "B_Broad_Search": "65-75%",
    "C_Cross_Repo": "70-80%",
    # v2 targets (harder questions → lower targets)
    "A_Deep_Structural": "75-85%",
    "B_Cross_Repo_Search": "60-70%",
    "C_Multi_Signal": "55-65%",
}


def _score_emoji(score: int) -> str:
    if score == 3:
        return "✅"
    elif score == 2:
        return "🟡"
    elif score == 1:
        return "🟠"
    else:
        return "❌"


def generate_markdown_report(evaluations: list, client: str, total_duration_ms: int) -> str:
    """Generate a formatted Markdown benchmark report."""
    lines = []
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines.append("# HiveMind Automated Benchmark Report")
    lines.append(f"**Date:** {now}")
    lines.append(f"**Client:** {client}")
    lines.append(f"**Total Duration:** {total_duration_ms / 1000:.1f}s")
    lines.append(f"**Questions:** {len(evaluations)}")
    lines.append(f"**Scoring:** 3=correct+citation+path | 2=correct+citation | 1=correct only | 0=wrong/missing")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Group by category
    categories = {}
    for ev in evaluations:
        cat = ev["category"]
        categories.setdefault(cat, []).append(ev)

    for cat in sorted(categories.keys()):
        evals = categories[cat]
        cat_label = CATEGORY_NAMES.get(cat, cat)
        cat_target = CATEGORY_TARGETS.get(cat, "N/A")

        cat_score = sum(e["score"] for e in evals)
        cat_max = sum(e["max_score"] for e in evals)
        cat_pct = (cat_score / cat_max * 100) if cat_max > 0 else 0

        lines.append(f"## {cat_label}")
        lines.append(f"**Score: {cat_score}/{cat_max} ({cat_pct:.0f}%)** | Target: {cat_target}")
        lines.append("")
        lines.append("| ID | Question | Score | Duration | Notes |")
        lines.append("|---|---|---|---|---|")

        for ev in evals:
            emoji = _score_emoji(ev["score"])
            q_short = ev["question"][:60] + ("..." if len(ev["question"]) > 60 else "")
            dur = f"{ev['duration_ms']}ms"
            notes = ev["notes"][:80] + ("..." if len(ev["notes"]) > 80 else "")
            lines.append(f"| {ev['id']} | {q_short} | {emoji} {ev['score']}/3 | {dur} | {notes} |")

        lines.append("")

    # Summary table
    lines.append("---")
    lines.append("")
    lines.append("## Summary")
    lines.append("")

    total_score = sum(e["score"] for e in evaluations)
    total_max = sum(e["max_score"] for e in evaluations)
    total_pct = (total_score / total_max * 100) if total_max > 0 else 0

    lines.append("| Category | Score | Max | Accuracy | Target |")
    lines.append("|---|---|---|---|---|")

    for cat in sorted(categories.keys()):
        evals = categories[cat]
        cat_label = CATEGORY_NAMES.get(cat, cat)
        cat_target = CATEGORY_TARGETS.get(cat, "N/A")
        cat_score = sum(e["score"] for e in evals)
        cat_max = sum(e["max_score"] for e in evals)
        cat_pct = (cat_score / cat_max * 100) if cat_max > 0 else 0
        lines.append(f"| {cat_label} | {cat_score} | {cat_max} | {cat_pct:.0f}% | {cat_target} |")

    lines.append(f"| **TOTAL** | **{total_score}** | **{total_max}** | **{total_pct:.0f}%** | ~75% |")
    lines.append("")

    # Failure analysis
    failures = [e for e in evaluations if e["score"] <= 1]
    if failures:
        lines.append("## Failure Analysis")
        lines.append("")
        lines.append("Questions scoring 0 or 1:")
        lines.append("")
        for f in failures:
            lines.append(f"- **{f['id']}** (score {f['score']}): {f['notes']}")
        lines.append("")

    # Validator breakdown
    lines.append("## Detailed Validator Results")
    lines.append("")
    for ev in evaluations:
        lines.append(f"### {ev['id']}: {ev['question'][:70]}")
        lines.append(f"Score: {_score_emoji(ev['score'])} {ev['score']}/3 | Duration: {ev['duration_ms']}ms")
        lines.append("")
        if ev["validator_results"]:
            for vr in ev["validator_results"]:
                icon = "✅" if vr["passed"] else "❌"
                detail = f" ({vr['detail']})" if vr.get("detail") else ""
                lines.append(f"  - {icon} {vr['type']}{detail}")
        else:
            lines.append("  - (no validators executed)")
        lines.append("")

    return "\n".join(lines)


def generate_json_report(evaluations: list, results: list, client: str, total_duration_ms: int) -> dict:
    """Generate a JSON benchmark report with full detail."""
    categories = {}
    for ev in evaluations:
        cat = ev["category"]
        categories.setdefault(cat, []).append(ev)

    category_scores = {}
    for cat, evals in categories.items():
        cat_score = sum(e["score"] for e in evals)
        cat_max = sum(e["max_score"] for e in evals)
        category_scores[cat] = {
            "score": cat_score,
            "max": cat_max,
            "accuracy_pct": round(cat_score / cat_max * 100, 1) if cat_max > 0 else 0,
            "target": CATEGORY_TARGETS.get(cat, "N/A"),
        }

    total_score = sum(e["score"] for e in evaluations)
    total_max = sum(e["max_score"] for e in evaluations)

    return {
        "benchmark": "hivemind_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "client": client,
        "total_duration_ms": total_duration_ms,
        "total_score": total_score,
        "total_max": total_max,
        "total_accuracy_pct": round(total_score / total_max * 100, 1) if total_max > 0 else 0,
        "category_scores": category_scores,
        "evaluations": evaluations,
        "raw_results": [
            {
                "id": r["id"],
                "tool_results": [
                    {
                        "tool": tr["tool"],
                        "duration_ms": tr["duration_ms"],
                        "error": tr["error"],
                        "result_preview": tr["result_text"][:500],
                    }
                    for tr in r.get("tool_results", [])
                ],
                "total_duration_ms": r.get("total_duration_ms", 0),
            }
            for r in results
        ],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HiveMind Automated Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python benchmarks/run_benchmark.py                     # Run all 30 questions
    python benchmarks/run_benchmark.py --category A        # Only HTI structural
    python benchmarks/run_benchmark.py --question A1       # Single question
    python benchmarks/run_benchmark.py --verbose --output benchmarks/results.md
    python benchmarks/run_benchmark.py --json > results.json
        """,
    )
    parser.add_argument(
        "--version", choices=["v1", "v2"], default="v2",
        help="Question set to use: v1 (original) or v2 (hard) — default: v2",
    )
    parser.add_argument(
        "--client", default=None,
        help="Client name (default: read from memory/active_client.txt)",
    )
    parser.add_argument(
        "--category", choices=["A", "B", "C"],
        help="Run only questions from this category",
    )
    parser.add_argument(
        "--question",
        help="Run a single question by ID (e.g. A1, B3, C7)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show progress during execution",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output raw JSON instead of Markdown",
    )
    parser.add_argument(
        "--output", "-o",
        help="Save report to file (default: print to stdout)",
    )

    args = parser.parse_args()

    # Load question module
    if args.version == "v1":
        from benchmarks.questions_v1 import (
            BENCHMARK_QUESTIONS, get_questions_by_category, get_question_by_id,
        )
    else:
        from benchmarks.questions_v2 import (
            BENCHMARK_QUESTIONS, get_questions_by_category, get_question_by_id,
        )

    # Determine client
    client = args.client
    if not client:
        client_file = PROJECT_ROOT / "memory" / "active_client.txt"
        if client_file.exists():
            client = client_file.read_text(encoding="utf-8").strip()
        if not client:
            print("ERROR: No client specified and memory/active_client.txt is empty.", file=sys.stderr)
            print("  Use --client <name> or set an active client first.", file=sys.stderr)
            sys.exit(1)

    # Select questions
    if args.question:
        q = get_question_by_id(args.question)
        if not q:
            print(f"ERROR: Question '{args.question}' not found.", file=sys.stderr)
            sys.exit(1)
        questions = [q]
    elif args.category:
        questions = get_questions_by_category(args.category)
        if not questions:
            print(f"ERROR: No questions in category '{args.category}'.", file=sys.stderr)
            sys.exit(1)
    else:
        questions = BENCHMARK_QUESTIONS

    # Run
    print(f"HiveMind Benchmark {args.version} — {len(questions)} questions for client '{client}'", file=sys.stderr)
    print("=" * 60, file=sys.stderr)

    total_start = time.time()
    results = run_all_questions(questions, client, verbose=args.verbose)
    total_duration_ms = int((time.time() - total_start) * 1000)

    # Evaluate
    evaluations = evaluate_all(results, questions)

    # Report
    if args.json:
        report = generate_json_report(evaluations, results, client, total_duration_ms)
        output_text = json.dumps(report, indent=2, default=str)
    else:
        output_text = generate_markdown_report(evaluations, client, total_duration_ms)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output_text, encoding="utf-8")
        print(f"\nReport saved to: {output_path}", file=sys.stderr)
    else:
        print(output_text)

    # Print summary to stderr
    total_score = sum(e["score"] for e in evaluations)
    total_max = sum(e["max_score"] for e in evaluations)
    total_pct = (total_score / total_max * 100) if total_max > 0 else 0
    print(f"\nFinal Score: {total_score}/{total_max} ({total_pct:.0f}%)", file=sys.stderr)

    # Exit code: 0 if >= 75%, 1 otherwise
    sys.exit(0 if total_pct >= 75 else 1)


if __name__ == "__main__":
    main()
