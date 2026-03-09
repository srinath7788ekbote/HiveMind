"""
Watch Repos

Background process that periodically syncs repos.
Runs as a long-lived process started by start_hivemind.bat.

Usage:
    python sync/watch_repos.py --client dfin --config clients/dfin/repos.yaml
    python sync/watch_repos.py --client dfin --config clients/dfin/repos.yaml --interval 300
"""

import argparse
import json
import os
import signal
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sync.incremental_sync import sync_all

# Global flag for graceful shutdown
_running = True


def _signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global _running
    print("\nShutdown signal received. Stopping after current sync...")
    _running = False


def _load_config(config_path: str) -> dict:
    """Load client configuration."""
    p = Path(config_path)
    if not p.exists():
        print(f"ERROR: Config not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    content = p.read_text(encoding='utf-8')
    try:
        import yaml
        return yaml.safe_load(content) or {}
    except ImportError:
        pass

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Simple parser fallback
    config = {"repos": []}
    current_repo = None
    for line in content.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('client_name:'):
            config['client_name'] = line.split(':', 1)[1].strip().strip('"\'')
        elif line.startswith('- name:'):
            if current_repo:
                config["repos"].append(current_repo)
            current_repo = {"name": line.split(':', 1)[1].strip().strip('"\''), "branches": []}
        elif current_repo and line.startswith('path:'):
            current_repo["path"] = line.split(':', 1)[1].strip().strip('"\'')
        elif current_repo and line.startswith('- ') and not line.startswith('- name:'):
            branch = line[2:].strip().strip('"\'')
            if branch:
                current_repo["branches"].append(branch)
    if current_repo:
        config["repos"].append(current_repo)
    return config


def watch(
    client: str,
    config_path: str,
    interval: int = 300,
    verbose: bool = False,
) -> None:
    """
    Main watch loop. Syncs repos periodically.

    Args:
        client: Client name.
        config_path: Path to repos.yaml.
        interval: Seconds between sync cycles.
        verbose: Print detailed progress.
    """
    global _running

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    config = _load_config(config_path)

    # Write PID file for stop script
    pid_file = PROJECT_ROOT / "memory" / client / "watcher.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding='utf-8')

    print(f"HiveMind Watcher started for client: {client}")
    print(f"PID: {os.getpid()}")
    print(f"Sync interval: {interval}s")
    print(f"Config: {config_path}")
    print()

    cycle = 0
    while _running:
        cycle += 1
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] Sync cycle {cycle}...")

        try:
            results = sync_all(client=client, config=config, verbose=verbose)

            updated = [r for r in results if r.get("status") == "updated"]
            if updated:
                print(f"  Updated: {len(updated)} repo-branch combinations")
                for r in updated:
                    print(f"    {r['repo']}:{r['branch']} — {r.get('changed_files', '?')} files")
            else:
                print(f"  All repos up to date")
        except Exception as e:
            print(f"  ERROR during sync: {e}", file=sys.stderr)

        # Wait for next cycle, checking _running periodically
        waited = 0
        while waited < interval and _running:
            time.sleep(min(5, interval - waited))
            waited += 5

    # Cleanup
    if pid_file.exists():
        pid_file.unlink()
    print("Watcher stopped.")


def main():
    parser = argparse.ArgumentParser(description="HiveMind Repo Watcher — background sync")
    parser.add_argument("--client", required=True, help="Client name")
    parser.add_argument("--config", required=True, help="Path to repos.yaml")
    parser.add_argument("--interval", type=int, default=300, help="Sync interval in seconds")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    watch(
        client=args.client,
        config_path=args.config,
        interval=args.interval,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
