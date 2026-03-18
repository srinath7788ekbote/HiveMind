"""
HTI Index All Clients -- discovers all clients and runs HTI indexer for each.

Usage:
    python scripts/hti_index_all.py            # index all clients
    python scripts/hti_index_all.py --verbose   # verbose output
    python scripts/hti_index_all.py --force     # force re-index all files
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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


def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    force = "--force" in sys.argv
    clients = discover_clients(PROJECT_ROOT)

    if not clients:
        print("No clients found in clients/ directory.")
        print("Run: make add-client  (or create clients/<name>/repos.yaml)")
        sys.exit(0)

    print("=" * 60)
    print("HIVEMIND -- HTI INDEX ALL CLIENTS")
    print("=" * 60)
    print(f"Discovered clients: {', '.join(clients)}\n")

    python = sys.executable
    failed = []

    for client in clients:
        print(f"-- CLIENT: {client} " + "-" * (46 - len(client)))

        cmd = [
            python, str(PROJECT_ROOT / "hivemind_mcp" / "hti" / "indexer.py"),
            "--client", client,
        ]
        if verbose:
            cmd.append("--verbose")
        if force:
            cmd.append("--force")

        result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        if result.returncode != 0:
            print(f"  [X] {client} -- HTI indexing failed (exit code {result.returncode})")
            failed.append(client)
        else:
            print(f"  [OK] {client} -- HTI indexing complete\n")

    print("=" * 60)
    if failed:
        print(f"HTI INDEX COMPLETE -- {len(failed)} client(s) had errors: {', '.join(failed)}")
    else:
        print(f"HTI INDEX COMPLETE -- all {len(clients)} client(s) indexed successfully")
    print("=" * 60)


if __name__ == "__main__":
    main()
