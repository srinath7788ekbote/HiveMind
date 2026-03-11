"""
Write File — General-purpose file writer for HiveMind agents

Creates or overwrites a file in a local client repo on a safe working branch.
Does NOT git add, commit, or push — the user reviews and does that manually.

Usage:
    python tools/write_file.py --client dfin --repo dfin-harness-pipelines \\
        --branch main --path some/path/file.yaml --content "..."

    python tools/write_file.py --client dfin --repo dfin-harness-pipelines \\
        --branch release_26_3 --path ci/precheck.yaml --content "..." \\
        --intent "create release precheck pipeline"

Workflow:
    1. Finds local repo path from clients/<client>/repos.yaml
    2. git checkout <branch> + git pull origin <branch> to get latest
    3. Creates new branch using intent-based naming (feat/*, fix/*, chore/*, release/*)
    4. Writes file content to path (creates directories if needed)
    5. Prints summary — nothing else. No git add, no commit, no push.
"""

import argparse
import os
import os
import re
import sys
import time
from pathlib import Path

import yaml

# Force UTF-8 output on Windows to avoid charmap encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.git_utils import run_git
from sync.branch_protection import BranchProtection, ProtectedBranchError, BranchCreationError


# ---------------------------------------------------------------------------
# Branch Naming Logic
# ---------------------------------------------------------------------------

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'for', 'in', 'on', 'at', 'to', 'from',
    'with', 'we', 'i', 'it', 'is', 'are', 'be', 'this', 'that', 'please',
    'can', 'you', 'need', 'want', 'should', 'would', 'create', 'make',
    'new', 'file', 'pipeline', 'branch', 'repo', 'harness', 'just', 'also',
    'all', 'but', 'not', 'do', 'does', 'our', 'my', 'so', 'have', 'has',
}

FIX_WORDS = {'fix', 'bug', 'patch', 'hotfix', 'repair'}
CREATE_WORDS = {'create', 'add', 'new', 'generate', 'build'}
UPDATE_WORDS = {'update', 'modify', 'change', 'refactor', 'improve'}


def get_branch_name(prompt: str, source_branch: str) -> str:
    """
    Generate a conventional branch name from intent detected in the prompt.

    Examples:
        "create a release precheck pipeline" → feat/release-precheck-pipeline
        "fix the deploy stage timeout" → fix/deploy-stage-timeout
        "update terraform module versions" → chore/terraform-module-versions
        "add release precheck from release_26_2" → feat/release-precheck-release-26
    """
    prompt_lower = prompt.lower()
    words_in_prompt = set(re.findall(r'[a-z]+', prompt_lower))

    # Detect prefix from intent
    if words_in_prompt & FIX_WORDS:
        prefix = 'fix'
    elif words_in_prompt & UPDATE_WORDS:
        prefix = 'chore'
    elif words_in_prompt & CREATE_WORDS:
        prefix = 'feat'
    else:
        prefix = 'feat'

    # Slugify key words from prompt (skip stop words, take first 4 meaningful words)
    raw_words = [w.strip('.,?!:;()[]{}"\'/') for w in prompt_lower.split()]
    meaningful = [
        w for w in raw_words
        if w not in STOP_WORDS and len(w) > 2 and re.match(r'^[a-z0-9_]+$', w)
    ]
    slug = '-'.join(meaningful[:4])

    if not slug:
        # Fallback: use source branch name (no timestamps)
        clean_source = source_branch.replace('/', '-').replace('_', '-')
        slug = clean_source

    # Truncate very long slugs
    if len(slug) > 50:
        slug = slug[:50].rstrip('-')

    return f"{prefix}/{slug}"


# ---------------------------------------------------------------------------
# Repo Resolution
# ---------------------------------------------------------------------------

def _guess_repo_type(file_path: str = "", content: str = "") -> list:
    """
    Guess the likely repo type/platform from a file path and content.
    Returns a list of type/platform hints (e.g., ['cicd', 'harness']).
    """
    hints = []
    fp = file_path.lower()
    c = content.lower() if content else ""

    # CI/CD / Harness signals
    if any(kw in fp for kw in ['pipeline', 'stage', 'step', '.harness']):
        hints.extend(['cicd', 'harness'])
    if any(kw in c for kw in ['pipeline:', 'stage:', 'step:', 'type: pipeline']):
        hints.extend(['cicd', 'harness'])

    # Terraform signals
    if fp.endswith(('.tf', '.tfvars')) or 'terraform' in fp:
        hints.extend(['infrastructure', 'terraform'])
    if any(kw in c for kw in ['resource "', 'provider "', 'module "', 'terraform {']):
        hints.extend(['infrastructure', 'terraform'])

    # Helm signals
    if any(kw in fp for kw in ['values', 'chart', 'templates/', 'helm']):
        hints.extend(['mixed', 'helm'])
    if any(kw in c for kw in ['apiversion:', 'kind:', 'helm.sh']):
        hints.extend(['mixed', 'helm'])

    return list(set(hints))


def find_repo_path(client: str, repo_name: str, file_path: str = "", content: str = "") -> str:
    """
    Find the local path for a repo from clients/<client>/repos.yaml.

    Args:
        client: Client name (e.g., 'dfin').
        repo_name: Repository name (e.g., 'dfin-harness-pipelines').
        file_path: Optional file path hint for type-based disambiguation.
        content: Optional content hint for type-based disambiguation.

    Returns:
        Absolute local path to the repo.

    Raises:
        FileNotFoundError: If repos.yaml is missing.
        ValueError: If repo is not found in repos.yaml.
    """
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

    # Fuzzy match: check if repo_name is a substring of any repo or vice versa
    fuzzy = [
        r.get("name", "")
        for r in repos
        if repo_name.lower() in r.get("name", "").lower()
        or r.get("name", "").lower() in repo_name.lower()
    ]
    if len(fuzzy) == 1:
        # Unambiguous fuzzy match — use it
        match = fuzzy[0]
        matched_repo = next(r for r in repos if r.get("name") == match)
        repo_path = matched_repo.get("path", "")
        if repo_path:
            print(
                f"[WARN] Repo '{repo_name}' not found exactly; "
                f"auto-resolved to '{match}'.",
                file=sys.stderr,
            )
            return repo_path
    elif len(fuzzy) > 1:
        # Multiple fuzzy matches — try type-based disambiguation using
        # the file_path extension or content hints
        type_hints = _guess_repo_type(file_path, content)
        scored = []
        for name in fuzzy:
            repo_entry = next(r for r in repos if r.get("name") == name)
            score = 0
            rtype = repo_entry.get("type", "").lower()
            rplatform = repo_entry.get("platform", "").lower()
            for hint_type in type_hints:
                if hint_type in (rtype, rplatform):
                    score += 2
            scored.append((name, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        if scored[0][1] > scored[1][1]:
            match = scored[0][0]
            matched_repo = next(r for r in repos if r.get("name") == match)
            repo_path = matched_repo.get("path", "")
            if repo_path:
                print(
                    f"[WARN] Repo '{repo_name}' not found exactly; "
                    f"auto-resolved to '{match}' (type-based disambiguation).",
                    file=sys.stderr,
                )
                return repo_path

    hint = ""
    if fuzzy:
        hint = f"\nDid you mean one of: {', '.join(fuzzy)}?"

    raise ValueError(
        f"Repo '{repo_name}' not found in {repos_yaml}.\n"
        f"Available repos: {', '.join(available)}{hint}"
    )


# ---------------------------------------------------------------------------
# Main Write Logic
# ---------------------------------------------------------------------------

def write_file(
    client: str,
    repo_name: str,
    branch: str,
    file_path: str,
    content: str,
    intent: str = "",
) -> dict:
    """
    Write a file to a local repo on a safe working branch.

    Args:
        client: Client name.
        repo_name: Repository name.
        branch: Source branch to branch from.
        file_path: Relative path within the repo for the file.
        content: File content to write.
        intent: Optional intent description for branch naming.

    Returns:
        Dict with keys: branch_created, file_written, repo_name, repo_path, source_branch
    """
    # 1. Resolve repo path
    repo_path = find_repo_path(client, repo_name, file_path, content)
    if not os.path.isdir(repo_path):
        raise FileNotFoundError(
            f"Repo directory not found: {repo_path}\n"
            f"Clone the repo first, then update clients/{client}/repos.yaml."
        )

    # 2. Checkout source branch and pull latest
    code, _, stderr = run_git(repo_path, ["checkout", branch])
    if code != 0:
        raise RuntimeError(
            f"Failed to checkout branch '{branch}' in {repo_path}: {stderr}"
        )

    code, _, stderr = run_git(repo_path, ["pull", "origin", branch])
    if code != 0:
        # Non-fatal: might be offline or branch doesn't exist on remote yet
        pass

    # 3. Create safe working branch
    bp = BranchProtection()

    if intent:
        branch_name = get_branch_name(intent, branch)
    else:
        branch_name = get_branch_name(content[:200], branch)

    # Check if branch already exists, append incremental counter
    code, _, _ = run_git(repo_path, ["rev-parse", "--verify", branch_name])
    if code == 0:
        for _i in range(2, 100):
            candidate = f"{branch_name}-{_i}"
            c, _, _ = run_git(repo_path, ["rev-parse", "--verify", candidate])
            if c != 0:
                branch_name = candidate
                break

    # Create the branch from current HEAD (already on source branch)
    code, _, stderr = run_git(repo_path, ["checkout", "-b", branch_name])
    if code != 0:
        raise BranchCreationError(
            f"Failed to create branch '{branch_name}': {stderr}"
        )

    # 4. Write the file
    full_path = Path(repo_path) / file_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.write_text(content, encoding="utf-8")

    return {
        "branch_created": branch_name,
        "file_written": file_path,
        "repo_name": repo_name,
        "repo_path": repo_path,
        "source_branch": branch,
    }


def format_summary(result: dict) -> str:
    """Format the write result as a user-friendly summary."""
    return (
        f"[OK] Branch created: {result['branch_created']}\n"
        f"[FILE] File written: {result['file_written']}\n"
        f"[REPO] Repo: {result['repo_name']} (local path: {result['repo_path']})\n"
        f"[NEXT] Review changes, then git add / commit / push when ready"
    )


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Write a file to a local repo on a safe working branch."
    )
    parser.add_argument("--client", required=True, help="Client name (e.g., dfin)")
    parser.add_argument("--repo", required=True, help="Repository name")
    parser.add_argument("--branch", default="main", help="Source branch (default: main)")
    parser.add_argument("--path", required=True, help="Relative file path within the repo")
    parser.add_argument("--content", required=True, help="File content to write")
    parser.add_argument(
        "--intent", default="",
        help="Intent description for branch naming (e.g., 'create release precheck pipeline')"
    )

    args = parser.parse_args()

    try:
        result = write_file(
            client=args.client,
            repo_name=args.repo,
            branch=args.branch,
            file_path=args.path,
            content=args.content,
            intent=args.intent,
        )
        print(format_summary(result))
    except (FileNotFoundError, ValueError, RuntimeError, BranchCreationError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
