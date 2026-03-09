---
name: get-entity
description: >
  Get full profile of a named entity -- metadata, all edges, related files.
  Use for detailed lookups of services, pipelines, or resources.
---

## When to use this skill

- "Tell me about X"
- "What is X"
- "List all services / pipelines / environments"
- Getting complete details of a known entity
- Looking up metadata for a service, pipeline, or resource

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/get_entity.py "{entity_name}" --client {client}
```

To list all entities of a type:

```
python tools/get_entity.py --list {type} --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --type | Filter by entity type | --type pipeline |
| --list TYPE | List all entities of a type | --list service |

### Entity types

`pipeline`, `service`, `secret`, `environment`, `chart`, `template`, `resource`, `identity`

## Output

Returns the full entity profile:
- **name**: Entity name
- **type**: Entity type
- **source_file**: Where it was discovered
- **edges**: All relationships (inbound and outbound)
- **metadata**: Type-specific details (stages, resources, etc.)

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
