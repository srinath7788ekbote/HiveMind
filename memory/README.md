# `memory/` — Runtime Data (Gitignored)

This directory is created automatically by `setup.bat` and populated by the ingest pipeline during `start_hivemind.bat`.

**Do not commit the contents of this directory.** Everything here is generated from your repos and will be rebuilt on ingest.

## What gets generated

```
memory/
├── active_client.txt          # Currently active client name
├── active_branch.txt          # Currently active branch (set by VS Code extension)
├── clients/
│   └── <your-client>/
│       └── discovered_profile.yaml   # Auto-discovered architecture profile
├── <your-client>/
│   ├── discovered_profile.yaml       # Architecture: services, environments, layers
│   ├── entities.json                 # Entity catalog (services, pipelines, secrets, etc.)
│   ├── branch_index.json             # Branch tier tracking
│   └── vectors/                      # Embedded chunks for semantic search
│       ├── <repo>_<branch>.json      # One file per repo+branch combo
│       └── ...
├── graph.db                          # SQLite entity relationship graph (if available)
└── chunks/                           # ChromaDB collection (if available)
```

## Regenerating

To rebuild memory from scratch:

```bat
start_hivemind.bat
```

Or trigger a re-ingest from VS Code:

```
@hivemind /ingest
```

## Switching clients

```
@hivemind /switch acme
```

This updates `active_client.txt` and re-loads the client context.
