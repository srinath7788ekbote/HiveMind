---
name: query-graph
description: >
  Traverse the relationship graph between infrastructure components.
  Use for dependency chains and relationship mapping.
---

## When to use this skill

- "What depends on X"
- "What does X call / use / reference"
- Finding dependency chains between components
- "Relationship between service A and template B"
- Mapping upstream or downstream connections

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/query_graph.py "{entity}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --direction | Traversal direction | --direction out |
| --depth | How many hops to traverse | --depth 3 |
| --branch | Filter by branch | --branch develop |

### Direction values

- `out` -- what does this entity depend on (outbound edges)
- `in` -- what depends on this entity (inbound edges)
- `both` -- bidirectional traversal

## Output

Returns a graph result containing:
- **nodes**: List of related entities with type and metadata
- **edges**: Relationships (edge_type, source, target, file_path)
- **depth**: How far each node is from the query entity

Edge types include: `CALLS_TEMPLATE`, `USES_SERVICE`, `DEPLOYS_TO`, `CREATES_SECRET`, `READS_SECRET`, `MOUNTS_SECRET`, `DEPENDS_ON`

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
