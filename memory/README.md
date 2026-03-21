# `memory/` — Runtime Data (Gitignored)

This directory is created automatically by `setup.bat` and populated by the ingest pipeline during `start_hivemind.bat`.

**Do not commit the contents of this directory.** Everything here is generated from your repos and will be rebuilt on ingest.

## What gets generated

```
memory/
├── active_client.txt          # Currently active client name
├── active_branch.txt          # Currently active branch
├── sync_log.txt               # Nightly sync log output
├── sync_state.json            # Last sync timestamps per repo/branch
├── clients/
│   └── <your-client>/
│       └── discovered_profile.yaml   # Auto-discovered architecture profile
├── <your-client>/
│   ├── discovered_profile.yaml       # Architecture: services, environments, layers
│   ├── entities.json                 # Entity catalog (services, pipelines, secrets, etc.)
│   ├── branch_index.json             # Branch tier tracking
│   ├── hti.sqlite                    # HTI structural index (skeletons + nodes)
│   ├── investigations/               # Saved incident investigations
│   └── vectors/                      # Embedded chunks for semantic search
│       ├── <repo>_<branch>.json      # One file per repo+branch combo
│       └── ...
├── graph.db                          # SQLite entity relationship graph
└── chromadb/                         # ChromaDB vector store (if populated)
```

## Regenerating

To rebuild memory from scratch:

```bash
make crawl CLIENT=<your-client>
make chromadb CLIENT=<your-client>
```

Or run a daily incremental sync:

```bash
make sync CLIENT=<your-client>
```

## Switching clients

Use the MCP tool via Copilot Chat or Claude Agent:

```
"Switch to client acme"
```

Or from the command line:

```bash
echo acme > memory\active_client.txt
```

This updates `active_client.txt` and re-loads the client context.
