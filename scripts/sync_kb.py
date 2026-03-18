"""
HiveMind KB Sync -- Incremental knowledge base synchronisation.

Detects changed files across all client repos and re-indexes only what
changed.  Supports multi-client operation: when no --client flag is given
it discovers all clients from the clients/ directory.

Usage:
    python scripts/sync_kb.py                          # sync all clients
    python scripts/sync_kb.py --client dfin            # sync one client
    python scripts/sync_kb.py --status                 # show status (all)
    python scripts/sync_kb.py --client dfin --status   # show status (one)
    python scripts/sync_kb.py --force                  # force re-index all
    python scripts/sync_kb.py --client dfin --force    # force re-index one
    python scripts/sync_kb.py --client dfin --repo dfin-harness-pipelines
    python scripts/sync_kb.py --client dfin --repo X --branch main
    python scripts/sync_kb.py --auto-yes               # no prompts (cron)
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Client discovery
# ---------------------------------------------------------------------------

def discover_clients(project_root: Path | None = None) -> list[str]:
    """Return sorted list of client names that have a repos.yaml."""
    root = project_root or PROJECT_ROOT
    clients_dir = root / "clients"
    if not clients_dir.exists():
        return []
    return sorted(
        d.name
        for d in clients_dir.iterdir()
        if d.is_dir()
        and not d.name.startswith("_")
        and (d / "repos.yaml").exists()
    )


def _load_config(config_path: Path) -> dict:
    """Load client config from YAML (or JSON fallback)."""
    if not config_path.exists():
        print(f"  ERROR: config not found: {config_path}", file=sys.stderr)
        return {}
    content = config_path.read_text(encoding="utf-8")
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Minimal manual YAML parser
    config: dict = {"repos": []}
    current_repo: dict | None = None
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("client_name:"):
            config["client_name"] = stripped.split(":", 1)[1].strip().strip("\"'")
        elif stripped.startswith("- name:"):
            if current_repo:
                config["repos"].append(current_repo)
            current_repo = {"name": stripped.split(":", 1)[1].strip().strip("\"'"), "branches": []}
        elif current_repo and stripped.startswith("path:"):
            current_repo["path"] = stripped.split(":", 1)[1].strip().strip("\"'")
        elif current_repo and stripped.startswith("type:"):
            current_repo["type"] = stripped.split(":", 1)[1].strip().strip("\"'")
        elif current_repo and stripped.startswith("- ") and current_repo.get("branches") is not None:
            branch = stripped[2:].strip().strip("\"'")
            if branch and not branch.startswith("name:"):
                current_repo["branches"].append(branch)
    if current_repo:
        config["repos"].append(current_repo)
    return config


# ---------------------------------------------------------------------------
# State management -- per-client sync state
# ---------------------------------------------------------------------------

def _state_path(client: str, project_root: Path | None = None) -> Path:
    root = project_root or PROJECT_ROOT
    return root / "memory" / client / "sync_state.json"


def _load_state(client: str, project_root: Path | None = None) -> dict:
    p = _state_path(client, project_root)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(client: str, state: dict, project_root: Path | None = None):
    p = _state_path(client, project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_file_hash(repo_path: str, branch: str, file_path: str) -> str | None:
    """Return the hash of a file on a given branch via git show."""
    try:
        result = subprocess.run(
            ["git", "show", f"{branch}:{file_path}"],
            capture_output=True, cwd=repo_path, timeout=30,
        )
        if result.returncode == 0:
            return hashlib.sha256(result.stdout).hexdigest()
    except Exception:
        pass
    return None


def _git_changed_files(repo_path: str, branch: str, since_commit: str | None = None) -> list[str]:
    """Return list of files changed on *branch* since *since_commit*."""
    try:
        if since_commit:
            result = subprocess.run(
                ["git", "diff", "--name-only", since_commit, branch],
                capture_output=True, text=True, cwd=repo_path, timeout=30,
            )
        else:
            result = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", branch],
                capture_output=True, text=True, cwd=repo_path, timeout=30,
            )
        if result.returncode == 0:
            return [f for f in result.stdout.strip().split("\n") if f]
    except Exception:
        pass
    return []


def _git_head_commit(repo_path: str, branch: str) -> str | None:
    """Return HEAD commit hash for *branch*."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", branch],
            capture_output=True, text=True, cwd=repo_path, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Sync logic -- single repo/branch
# ---------------------------------------------------------------------------

def _sync_repo_branch(
    repo_path: str,
    repo_name: str,
    branch: str,
    state: dict,
    force: bool = False,
) -> dict:
    """
    Check a single repo/branch for changes and return a status dict.

    Returns:
        {"status": "up_to_date"|"changed"|"error",
         "files_changed": int, "new_commit": str}
    """
    key = f"{repo_name}/{branch}"
    prev = state.get(key, {})
    prev_commit = prev.get("commit")

    head = _git_head_commit(repo_path, branch)
    if head is None:
        return {"status": "error", "files_changed": 0, "new_commit": None,
                "message": f"cannot resolve {branch}"}

    if not force and prev_commit == head:
        return {"status": "up_to_date", "files_changed": 0, "new_commit": head}

    changed = _git_changed_files(repo_path, branch, prev_commit if not force else None)
    return {"status": "changed", "files_changed": len(changed), "new_commit": head}


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------

def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def show_status(clients: list[str], project_root: Path | None = None):
    """Print sync status for one or more clients."""
    root = project_root or PROJECT_ROOT
    header = "ALL CLIENTS" if len(clients) != 1 else clients[0].upper()
    print("=" * 60)
    print(f"HIVEMIND KB STATUS -- {header}")
    print("=" * 60)

    for client in clients:
        config_path = root / "clients" / client / "repos.yaml"
        config = _load_config(config_path)
        state = _load_state(client, root)
        repos = config.get("repos", [])

        print(f"\n-- CLIENT: {client} " + "-" * (46 - len(client)))
        if not repos:
            print("  (no repos configured)")
            continue

        for repo in repos:
            repo_name = repo.get("name", "unknown")
            repo_path = repo.get("path", "")
            branches = repo.get("branches", ["main"])
            for branch in branches:
                key = f"{repo_name}/{branch}"
                info = state.get(key, {})
                commit = info.get("commit", "")[:8] if info.get("commit") else "n/a"
                ts = info.get("synced_at", "never")
                print(f"  {key:<45} {commit}  {ts}")

    print("\n" + "=" * 60)


# ---------------------------------------------------------------------------
# Sync -- single client
# ---------------------------------------------------------------------------

def sync_client(
    client: str,
    force: bool = False,
    repo_filter: str | None = None,
    branch_filter: str | None = None,
    auto_yes: bool = False,
    project_root: Path | None = None,
) -> dict:
    """
    Sync a single client. Returns summary dict.
    """
    root = project_root or PROJECT_ROOT
    config_path = root / "clients" / client / "repos.yaml"
    config = _load_config(config_path)
    repos = config.get("repos", [])
    state = _load_state(client, root)

    synced = 0
    skipped = 0
    errors = 0
    start = time.time()

    for repo in repos:
        repo_name = repo.get("name", "unknown")
        repo_path = repo.get("path", "")

        if repo_filter and repo_name != repo_filter:
            continue

        if not repo_path or not Path(repo_path).exists():
            print(f"  [X] {repo_name} -- path not found: {repo_path}")
            errors += 1
            continue

        branches = repo.get("branches", ["main"])
        if branch_filter:
            branches = [branch_filter] if branch_filter in branches else []

        for branch in branches:
            result = _sync_repo_branch(repo_path, repo_name, branch, state, force)
            key = f"{repo_name}/{branch}"

            if result["status"] == "up_to_date":
                print(f"  [OK] {key} -- up to date")
                skipped += 1
            elif result["status"] == "changed":
                print(f"  [!] {key} -- {result['files_changed']} files changed")
                # Re-index this branch
                try:
                    from ingest.crawl_repos import crawl
                    if not auto_yes and not force:
                        answer = input(f"    Re-index {key}? [Y/n] ").strip().lower()
                        if answer and answer != "y":
                            skipped += 1
                            continue
                    crawl(
                        client=client,
                        config_path=str(config_path),
                        branches=[branch],
                        verbose=False,
                    )
                    synced += 1
                except Exception as exc:
                    print(f"    [X] Error re-indexing {key}: {exc}")
                    errors += 1
                    continue
                # Update state
                state[key] = {
                    "commit": result["new_commit"],
                    "synced_at": time.strftime("%Y-%m-%d %H:%M"),
                }
            else:
                print(f"  [X] {key} -- {result.get('message', 'error')}")
                errors += 1

        # Update state for up-to-date branches too
        for branch in branches:
            key = f"{repo_name}/{branch}"
            result = _sync_repo_branch(repo_path, repo_name, branch, state, force=False)
            if result["status"] == "up_to_date" and result["new_commit"]:
                if key not in state:
                    state[key] = {}
                state[key]["commit"] = result["new_commit"]
                if "synced_at" not in state[key]:
                    state[key]["synced_at"] = "initial"

    _save_state(client, state, root)

    # --- HTI incremental sync (fast — only re-indexes changed files) ---
    if synced > 0:
        try:
            from hivemind_mcp.hti.indexer import index_client as hti_index_client
            hti_result = hti_index_client(client, force=False, project_root=root)
            hti_skels = hti_result.get("skeleton_count", 0)
            print(f"  HTI: {hti_skels} skeletons updated")
        except ImportError:
            pass  # HTI not available, skip silently
        except Exception as e:
            print(f"  HTI sync warning: {e}")  # Don't fail sync if HTI fails

    elapsed = time.time() - start

    return {
        "client": client,
        "synced": synced,
        "skipped": skipped,
        "errors": errors,
        "elapsed": elapsed,
    }


# ---------------------------------------------------------------------------
# Multi-client orchestration
# ---------------------------------------------------------------------------

def sync_all(
    clients: list[str],
    force: bool = False,
    repo_filter: str | None = None,
    branch_filter: str | None = None,
    auto_yes: bool = False,
    project_root: Path | None = None,
):
    """Sync one or many clients, with summary output."""
    root = project_root or PROJECT_ROOT
    multi = len(clients) > 1

    if multi:
        print("=" * 60)
        print("HIVEMIND KB SYNC -- ALL CLIENTS")
        print("=" * 60)
        print(f"Discovered clients: {', '.join(clients)}")

    summaries = []
    total_start = time.time()

    for client in clients:
        print(f"\n-- CLIENT: {client} " + "-" * (46 - len(client)))
        summary = sync_client(
            client=client,
            force=force,
            repo_filter=repo_filter,
            branch_filter=branch_filter,
            auto_yes=auto_yes,
            project_root=root,
        )
        summaries.append(summary)

    total_elapsed = time.time() - total_start
    total_synced = sum(s["synced"] for s in summaries)
    total_skipped = sum(s["skipped"] for s in summaries)

    if multi:
        print("\n" + "=" * 60)
        print("SYNC COMPLETE -- ALL CLIENTS")
        print("=" * 60)
        for s in summaries:
            print(f"  {s['client']:<12} {s['synced']} synced, {s['skipped']} skipped")
        print(f"  {'Total':<12} {total_synced} synced, {total_skipped} skipped, "
              f"{_format_time(total_elapsed)}")
        print("=" * 60)
    else:
        s = summaries[0]
        print(f"\nSync complete: {s['synced']} synced, {s['skipped']} skipped, "
              f"{_format_time(s['elapsed'])}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="HiveMind KB Sync -- incremental knowledge base synchronisation"
    )
    parser.add_argument("--client", default=None,
                        help="Sync a specific client (default: all discovered clients)")
    parser.add_argument("--status", action="store_true",
                        help="Show sync status without syncing")
    parser.add_argument("--force", action="store_true",
                        help="Force re-index (ignore cached state)")
    parser.add_argument("--repo", default=None,
                        help="Sync a specific repo only (requires --client)")
    parser.add_argument("--branch", default=None,
                        help="Sync a specific branch only (requires --repo)")
    parser.add_argument("--auto-yes", action="store_true",
                        help="Skip confirmation prompts (for scheduled runs)")
    args = parser.parse_args()

    # Determine client list
    if args.client:
        clients = [args.client]
    else:
        clients = discover_clients(PROJECT_ROOT)
        if not clients:
            print("No clients found in clients/ directory.")
            print("Run: make add-client  (or create clients/<name>/repos.yaml)")
            sys.exit(0)

    # Validate flags
    if args.repo and not args.client:
        parser.error("--repo requires --client")
    if args.branch and not args.repo:
        parser.error("--branch requires --repo")

    if args.status:
        show_status(clients, PROJECT_ROOT)
    else:
        sync_all(
            clients=clients,
            force=args.force,
            repo_filter=args.repo,
            branch_filter=args.branch,
            auto_yes=args.auto_yes,
            project_root=PROJECT_ROOT,
        )


if __name__ == "__main__":
    main()
