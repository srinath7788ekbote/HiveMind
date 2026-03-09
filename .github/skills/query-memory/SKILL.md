---
name: query-memory
description: >
  Semantic search over the HiveMind knowledge base. Use when searching for
  files, services, pipelines, or configurations by meaning.
---

## When to use this skill

- Finding relevant files, services, or configurations by concept
- Searching by meaning rather than exact text match
- "What files are related to X"
- "Find pipelines that mention Y"
- General knowledge base exploration when you don't know exact names

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/query_memory.py "{query}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --branch | Filter by branch | --branch release_26_1 |
| --filter_type | Filter by file type | --filter_type pipeline |
| --top | Number of results | --top 10 |

### Filter types

`pipeline`, `terraform`, `helm`, `service`, `environment`, `template`, `secret`, `readme`

## Output

Returns a ranked list of text chunks from indexed repositories, each with:
- **file_path**: The source file
- **relevance**: Similarity score (0-100%)
- **branch**: Which branch the chunk was indexed from
- **text**: The matching content snippet

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
