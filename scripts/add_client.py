"""
Add Client -- Interactive wizard to add a new client to HiveMind.

Creates the client directory structure and repos.yaml configuration
by prompting the user for repo details interactively.

Usage:
    python scripts/add_client.py
"""

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# File patterns used to auto-detect repo type/platform
_DETECTION_PATTERNS = {
    ("cicd", "harness"): ["**/.harness/**/*.yaml", "**/pipeline*.yaml"],
    ("infrastructure", "terraform"): ["**/*.tf"],
    ("mixed", "helm"): ["**/Chart.yaml", "**/values.yaml"],
    ("monitoring", "newrelic"): ["**/*newrelic*", "**/*nrql*"],
}


def _detect_type_platform(repo_path: Path) -> tuple[str, str]:
    """
    Try to auto-detect repo type and platform from file patterns.
    Returns (type, platform) or ("mixed", "unknown") as fallback.
    """
    for (rtype, platform), patterns in _DETECTION_PATTERNS.items():
        for pat in patterns:
            if list(repo_path.glob(pat)):
                return rtype, platform
    return "mixed", "unknown"


def _prompt(msg: str, default: str = "") -> str:
    """Prompt with optional default."""
    if default:
        val = input(f"  {msg} [{default}]: ").strip()
        return val or default
    return input(f"  {msg}: ").strip()


def _prompt_choices(msg: str, choices: list[str], default: str = "") -> str:
    """Prompt with a list of valid choices."""
    choices_str = "/".join(choices)
    while True:
        val = _prompt(f"{msg} ({choices_str})", default)
        if val in choices:
            return val
        print(f"    Invalid choice. Pick one of: {choices_str}")


def main():
    print("=" * 60)
    print("HIVEMIND -- ADD NEW CLIENT")
    print("=" * 60)
    print()

    # --- Client name ---
    client_name = _prompt("Client name (lowercase, no spaces, e.g. 'acme')")
    if not client_name:
        print("Client name is required.")
        sys.exit(1)
    client_name = client_name.lower().replace(" ", "-")

    client_dir = PROJECT_ROOT / "clients" / client_name
    if client_dir.exists():
        print(f"\n  [!] Client directory already exists: {client_dir}")
        overwrite = _prompt("Overwrite? (y/n)", "n")
        if overwrite != "y":
            print("Aborted.")
            sys.exit(0)

    display_name = _prompt("Display name (e.g. 'Acme Corp')", client_name.upper())

    # --- Repos ---
    repos = []
    print("\n  Add repos one at a time. Type 'done' when finished.\n")

    while True:
        repo_name = _prompt("Repo name (or 'done' to finish)")
        if repo_name.lower() == "done":
            break
        if not repo_name:
            continue

        # Path
        while True:
            repo_path_str = _prompt(f"Local path for {repo_name}")
            repo_path = Path(repo_path_str)
            if repo_path.exists() and repo_path.is_dir():
                break
            print(f"    [X] Path does not exist or is not a directory: {repo_path_str}")

        # Auto-detect type/platform
        detected_type, detected_platform = _detect_type_platform(repo_path)
        print(f"    Auto-detected: type={detected_type}, platform={detected_platform}")

        repo_type = _prompt_choices(
            "Repo type",
            ["cicd", "infrastructure", "mixed", "monitoring"],
            detected_type,
        )
        platform = _prompt_choices(
            "Platform",
            ["harness", "terraform", "helm", "newrelic", "unknown"],
            detected_platform,
        )

        # Branches
        branches_str = _prompt("Branches to index (comma-separated)", "main")
        branches = [b.strip() for b in branches_str.split(",") if b.strip()]

        description = _prompt("Description (optional)", "")

        repo_config = {
            "name": repo_name,
            "path": str(repo_path),
            "type": repo_type,
            "platform": platform,
            "branches": branches,
        }
        if description:
            repo_config["description"] = description

        repos.append(repo_config)
        print(f"    [OK] Added {repo_name}\n")

    if not repos:
        print("\nNo repos added. Aborted.")
        sys.exit(0)

    # --- Build YAML ---
    client_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = client_dir / "repos.yaml"

    lines = [
        f"# {display_name} Client Repository Configuration",
        f"",
        f"client_name: {client_name}",
        f'display_name: "{display_name}"',
        f"",
        f"repos:",
    ]
    for repo in repos:
        lines.append(f"  - name: {repo['name']}")
        # Escape backslashes for Windows paths in YAML
        escaped_path = repo["path"].replace("\\", "\\\\")
        lines.append(f'    path: "{escaped_path}"')
        lines.append(f"    type: {repo['type']}")
        lines.append(f"    platform: {repo['platform']}")
        lines.append(f"    branches:")
        for branch in repo["branches"]:
            lines.append(f"      - {branch}")
        if repo.get("description"):
            lines.append(f'    description: "{repo["description"]}"')
        lines.append("")

    lines.extend([
        "# Default branch to query when no --branch flag is specified",
        "default_branch: main",
        "",
        "# Sync settings",
        "sync:",
        "  interval_seconds: 300",
        "  watch_enabled: true",
        "  auto_ingest: true",
        "",
        "# Discovery settings",
        "discovery:",
        "  detect_naming_conventions: true",
        "  detect_secret_patterns: true",
        "  min_confidence: 0.7",
    ])

    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[OK] Created {yaml_path}")
    print(f"  Repos: {len(repos)}")
    for r in repos:
        print(f"    - {r['name']} ({r['type']}/{r['platform']})")

    # --- Set as active client ---
    active_file = PROJECT_ROOT / "memory" / "active_client.txt"
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(client_name, encoding="utf-8")
    print(f"\n[OK] Set {client_name} as active client")

    # --- Offer initial crawl ---
    print()
    run_crawl = _prompt("Run initial crawl now? (y/n)", "y")
    if run_crawl.lower() == "y":
        print(f"\nStarting crawl for {client_name}...\n")
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "ingest" / "crawl_repos.py"),
            "--client", client_name,
            "--config", str(yaml_path),
            "--verbose",
        ]
        subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    else:
        print(f"\nTo crawl later: make crawl CLIENT={client_name}")

    print("\nDone! Next steps:")
    print(f"  1. make crawl CLIENT={client_name}    (if you skipped crawl above)")
    print(f"  2. make chromadb CLIENT={client_name}  (populate vector store)")
    print(f"  3. make server                         (start MCP server)")


if __name__ == "__main__":
    main()
