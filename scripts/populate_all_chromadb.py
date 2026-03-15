"""
Populate All ChromaDB — discovers all clients and runs populate_chromadb.py for each.

Usage:
    python scripts/populate_all_chromadb.py              # populate all
    python scripts/populate_all_chromadb.py --verify      # verify all
    python scripts/populate_all_chromadb.py --dry-run     # dry run all
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
    clients = discover_clients(PROJECT_ROOT)

    if not clients:
        print("No clients found in clients/ directory.")
        print("Run: make add-client  (or create clients/<name>/repos.yaml)")
        sys.exit(0)

    # Pass through all extra args (--verify, --dry-run, --batch-size, etc.)
    extra_args = sys.argv[1:]

    print("=" * 60)
    print("HIVEMIND — POPULATE CHROMADB ALL CLIENTS")
    print("=" * 60)
    print(f"Discovered clients: {', '.join(clients)}\n")

    python = sys.executable

    for client in clients:
        print(f"── CLIENT: {client} " + "─" * (46 - len(client)))
        cmd = [
            python, str(PROJECT_ROOT / "scripts" / "populate_chromadb.py"),
            "--client", client,
        ] + extra_args
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))
        print()

    print("=" * 60)
    print(f"DONE — processed {len(clients)} client(s)")
    print("=" * 60)


if __name__ == "__main__":
    main()
