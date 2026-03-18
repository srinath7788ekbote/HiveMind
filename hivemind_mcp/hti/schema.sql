-- HTI (HiveMind Tree Intelligence) Schema
-- Two tables for skeleton-based structural retrieval of YAML/HCL files.
-- DO NOT modify existing graph.sqlite tables — these are new, separate tables.

CREATE TABLE IF NOT EXISTS hti_skeletons (
    id TEXT PRIMARY KEY,            -- "{client}:{repo}:{branch}:{relative_filepath}"
    client TEXT NOT NULL,
    repo TEXT NOT NULL,
    branch TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL,        -- "harness" | "terraform" | "helm" | "generic"
    skeleton_json TEXT NOT NULL,    -- compact JSON tree of keys + metadata only
    node_count INTEGER,
    mtime_epoch INTEGER,            -- file mtime for incremental indexing
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS hti_nodes (
    id TEXT PRIMARY KEY,            -- "{client}:{repo}:{branch}:{filepath}:{node_path}"
    skeleton_id TEXT NOT NULL,
    node_path TEXT NOT NULL,        -- e.g. "root.pipeline.stages[1].spec.execution"
    depth INTEGER NOT NULL,
    content_json TEXT NOT NULL,     -- full subtree at this path as JSON
    FOREIGN KEY (skeleton_id) REFERENCES hti_skeletons(id)
);

CREATE INDEX IF NOT EXISTS idx_hti_nodes_skeleton ON hti_nodes(skeleton_id);
CREATE INDEX IF NOT EXISTS idx_hti_skeletons_repo ON hti_skeletons(repo);
CREATE INDEX IF NOT EXISTS idx_hti_skeletons_client ON hti_skeletons(client);
