"""
Propose Edit — Propose or apply an edit to a file in a repo

Reads the current file content, generates a diff preview, and optionally
applies the change to non-protected branches.  Never git adds, commits,
or pushes — the user reviews and does that manually.

Usage:
    python tools/propose_edit.py --client dfin --repo dfin-harness-pipelines \\
        --file newad/cd/cd_deploy_env/pipeline.yaml --branch feat/add-parsers \\
        --description "Add parser stages to deployment" --auto-apply

    python tools/propose_edit.py --client dfin --repo Eastwood-terraform \\
        --file layer_5/secrets.tf --branch main \\
        --description "Add new secret" --changes "full file content here"
"""

import argparse
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# Force UTF-8 output on Windows to avoid charmap encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.branch_protection import BranchProtection
from tools.read_file import read_file as hm_read_file


# ---------------------------------------------------------------------------
# Repo Resolution (same pattern as read_file / write_file)
# ---------------------------------------------------------------------------

def _find_repo_path(client: str, repo_name: str) -> str:
    """Find the local path for a repo from clients/<client>/repos.yaml."""
    repos_yaml = PROJECT_ROOT / "clients" / client / "repos.yaml"
    if not repos_yaml.exists():
        raise FileNotFoundError(
            f"Client config not found: {repos_yaml}\n"
            f"Ensure clients/{client}/repos.yaml exists."
        )

    with open(repos_yaml, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    repos = config.get("repos", [])
    for repo in repos:
        if repo.get("name") == repo_name:
            repo_path = repo.get("path", "")
            if not repo_path:
                raise ValueError(
                    f"Repo '{repo_name}' has no path in {repos_yaml}"
                )
            return repo_path

    available = [r.get("name", "?") for r in repos]
    raise ValueError(
        f"Repo '{repo_name}' not found in {repos_yaml}.\n"
        f"Available repos: {', '.join(available)}"
    )


# ---------------------------------------------------------------------------
# Diff Generation
# ---------------------------------------------------------------------------

def _generate_diff(
    old_content: str,
    new_content: str,
    file_path: str,
) -> str:
    """Generate a unified diff between old and new content."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm="",
    )
    return "".join(diff)


def _count_changes(old_content: str, new_content: str) -> dict:
    """Count lines added, removed, and changed."""
    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
    added = 0
    removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            removed += i2 - i1
            added += j2 - j1

    return {"added": added, "removed": removed, "changed": added + removed}


# ---------------------------------------------------------------------------
# Main Propose Edit Logic
# ---------------------------------------------------------------------------

def propose_edit(
    client: str,
    repo: str,
    file_path: str,
    branch: str,
    description: str,
    proposed_changes: str,
    auto_apply: bool = False,
) -> dict:
    """
    Propose or apply an edit to a file in a repo.

    Args:
        client: Client name (e.g., 'dfin').
        repo: Repository name.
        file_path: Path within the repo.
        branch: Target branch for the edit.
        description: Human-readable description of the edit.
        proposed_changes: The edit content (full file replacement).
        auto_apply: If True and branch is not protected, write directly.

    Returns:
        Dict with edit proposal/application details.
    """
    result = {
        "action": "proposed",
        "file_path": file_path,
        "repo": repo,
        "branch": branch,
        "description": description,
        "lines_before": 0,
        "lines_after": 0,
        "lines_changed": 0,
        "diff_preview": "",
        "full_diff": "",
        "applied_at": None,
        "note": "",
    }

    # Step 1: Branch protection check
    bp = BranchProtection()
    if bp.is_protected(branch):
        tier = bp.get_protection_tier(branch)
        result["action"] = "blocked"
        result["note"] = (
            f"Branch '{branch}' is a {tier}-tier protected branch. "
            f"Direct modifications are not allowed. "
            f"Create a working branch first using: "
            f"hivemind/<{branch}>-<description>"
        )
        return result

    # Step 2: Read current file content
    current = hm_read_file(
        client=client,
        repo=repo,
        file_path=file_path,
        branch=branch,
    )

    old_content = current.get("content", "")
    is_new_file = current.get("source") == "none" or not old_content

    # Step 3: Use proposed_changes as full file content
    new_content = proposed_changes

    # Step 4: Generate diff
    full_diff = _generate_diff(old_content, new_content, file_path)
    diff_lines = full_diff.splitlines()
    diff_preview = "\n".join(diff_lines[:50])
    if len(diff_lines) > 50:
        diff_preview += f"\n... ({len(diff_lines) - 50} more lines)"

    changes = _count_changes(old_content, new_content)
    old_line_count = len(old_content.splitlines()) if old_content else 0
    new_line_count = len(new_content.splitlines()) if new_content else 0

    result["lines_before"] = old_line_count
    result["lines_after"] = new_line_count
    result["lines_changed"] = changes["changed"]
    result["diff_preview"] = diff_preview
    result["full_diff"] = full_diff

    # Step 5: Apply if auto_apply and branch is safe
    if auto_apply:
        try:
            repo_path = _find_repo_path(client, repo)
        except (FileNotFoundError, ValueError) as e:
            result["action"] = "proposed"
            result["note"] = (
                f"Cannot auto-apply: {e}. "
                f"Edit proposed but not written."
            )
            return result

        target_path = Path(repo_path) / file_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(new_content, encoding="utf-8")

        result["action"] = "applied"
        result["applied_at"] = datetime.now(timezone.utc).isoformat()
        if is_new_file:
            result["note"] = (
                f"New file created at {file_path}. "
                f"{new_line_count} lines written. "
                f"NOT committed — review and git add/commit/push when ready."
            )
        else:
            result["note"] = (
                f"File updated: +{changes['added']}/-{changes['removed']} lines. "
                f"NOT committed — review and git add/commit/push when ready."
            )
    else:
        if is_new_file:
            result["note"] = (
                f"New file proposed ({new_line_count} lines). "
                f"Set auto_apply=True to write, or review and apply manually."
            )
        else:
            result["note"] = (
                f"Edit proposed: +{changes['added']}/-{changes['removed']} lines. "
                f"Set auto_apply=True to write, or review and apply manually."
            )

    return result


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Propose or apply an edit to a file in a repo."
    )
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--file", required=True, help="File path within the repo")
    parser.add_argument("--branch", required=True, help="Target branch")
    parser.add_argument("--description", required=True, help="Description of the edit")
    parser.add_argument(
        "--changes", default="",
        help="Proposed changes (full file content). If empty, reads from stdin.",
    )
    parser.add_argument(
        "--auto-apply", action="store_true",
        help="Auto-apply if branch is not protected",
    )
    parser.add_argument(
        "--json", dest="json_output", action="store_true",
        help="Output raw JSON instead of formatted text",
    )

    args = parser.parse_args()

    changes = args.changes
    if not changes and not sys.stdin.isatty():
        changes = sys.stdin.read()

    if not changes:
        print("[ERROR] No proposed changes provided. Use --changes or pipe content via stdin.", file=sys.stderr)
        sys.exit(1)

    try:
        result = propose_edit(
            client=args.client,
            repo=args.repo,
            file_path=args.file,
            branch=args.branch,
            description=args.description,
            proposed_changes=changes,
            auto_apply=args.auto_apply,
        )

        if args.json_output:
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"[ACTION] {result['action']}")
            print(f"[FILE] {result['file_path']}")
            print(f"[REPO] {result['repo']}")
            print(f"[BRANCH] {result['branch']}")
            print(f"[DESCRIPTION] {result['description']}")
            print(f"[LINES] before={result['lines_before']} after={result['lines_after']} changed={result['lines_changed']}")
            if result["applied_at"]:
                print(f"[APPLIED] {result['applied_at']}")
            print(f"[NOTE] {result['note']}")
            if result["diff_preview"]:
                print("--- DIFF PREVIEW ---")
                print(result["diff_preview"])

    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
