"""
Set Client — Switch the active client context

Writes/updates the active client marker so all tools know which
client's repos and memory to operate on.

Usage:
    python tools/set_client.py dfin
    python tools/set_client.py --client dfin
    python tools/set_client.py --list
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def get_active_client() -> str:
    """Return the currently active client name."""
    marker = PROJECT_ROOT / "memory" / "active_client.txt"
    if marker.exists():
        return marker.read_text(encoding="utf-8").strip()
    return ""


def set_active_client(client: str) -> dict:
    """
    Set the active client.

    Args:
        client: Client name to activate.

    Returns:
        dict with status and details.
    """
    client_dir = PROJECT_ROOT / "clients" / client
    if not client_dir.exists():
        return {"error": f"Client '{client}' not found. No directory at {client_dir}"}

    config_path = client_dir / "repos.yaml"
    if not config_path.exists():
        return {"error": f"Client '{client}' has no repos.yaml configuration"}

    # Ensure memory directory exists
    memory_dir = PROJECT_ROOT / "memory"
    memory_dir.mkdir(parents=True, exist_ok=True)

    # Also ensure client memory dir exists
    client_memory = memory_dir / client
    client_memory.mkdir(parents=True, exist_ok=True)

    # Write active client marker
    marker = memory_dir / "active_client.txt"
    marker.write_text(client, encoding="utf-8")

    # Count repos in config
    repo_count = 0
    content = config_path.read_text(encoding="utf-8")
    for line in content.split("\n"):
        if line.strip().startswith("- name:"):
            repo_count += 1

    return {
        "client": client,
        "config": str(config_path),
        "memory_dir": str(client_memory),
        "repos": repo_count,
        "status": "active",
    }


def list_clients() -> list:
    """Return a list of available clients."""
    clients_dir = PROJECT_ROOT / "clients"
    if not clients_dir.exists():
        return []

    clients = []
    active = get_active_client()

    for item in sorted(clients_dir.iterdir()):
        if item.is_dir() and (item / "repos.yaml").exists():
            clients.append({
                "name": item.name,
                "active": item.name == active,
                "config": str(item / "repos.yaml"),
            })

    return clients


def main():
    parser = argparse.ArgumentParser(description="HiveMind Set Client — switch active client context")
    parser.add_argument("client_pos", nargs="?", default=None, help="Client name (positional)")
    parser.add_argument("--client", default=None, help="Client name")
    parser.add_argument("--list", action="store_true", help="List available clients")
    args = parser.parse_args()

    if args.list:
        clients = list_clients()
        if not clients:
            print("No clients configured. Create clients/<name>/repos.yaml")
            return

        print("Available clients:\n")
        for c in clients:
            marker = " ← active" if c["active"] else ""
            print(f"  {c['name']}{marker}")
            print(f"    Config: {c['config']}")
        return

    client_name = args.client_pos or args.client
    if not client_name:
        current = get_active_client()
        if current:
            print(f"Active client: {current}")
        else:
            print("No active client. Use: python tools/set_client.py <name>")
        return

    result = set_active_client(client_name)
    if result.get("error"):
        print(f"Error: {result['error']}")
        return

    print(f"Active client set to: {result['client']}")
    print(f"  Config: {result['config']}")
    print(f"  Memory: {result['memory_dir']}")
    print(f"  Repos:  {result['repos']}")


if __name__ == "__main__":
    main()

