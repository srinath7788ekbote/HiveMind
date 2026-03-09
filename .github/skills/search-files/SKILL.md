---
name: search-files
description: >
  Exact pattern or regex search across actual repo files. Use for finding
  specific strings, resource names, or code patterns.
---

## When to use this skill

- "Find all references to X"
- "Which files contain Y"
- "Grep for Z across repos"
- Searching by exact string or regex pattern
- Finding resource definitions by name

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/search_files.py "{pattern}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --repo | Search specific repo only | --repo terraform-infra |
| --ext | Filter by file extension | --ext tf |
| --max | Maximum results | --max 20 |

### Common extensions

`yaml`, `yml`, `tf`, `py`, `json`, `md`, `hcl`

## Output

Returns a list of matching files with:
- **file_path**: Full path to the file
- **line_number**: Where the match was found
- **content**: The matching line(s)
- **repo**: Which repository the file belongs to

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
