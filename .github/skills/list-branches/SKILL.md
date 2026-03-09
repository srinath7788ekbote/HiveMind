---
name: list-branches
description: >
  Lists all indexed branches with tier classification (production/integration/
  release/hotfix/feature) and last sync time.
---

## When to use this skill

- "What branches exist"
- "List branches"
- "Which branches are indexed"
- "Active release branches"
- Understanding branch landscape before a diff or query

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/list_branches.py --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --repo | List branches for specific repo | --repo terraform-infra |

## Output

Returns a list of all indexed branches:
- **branch_name**: The branch name
- **tier**: production / integration / release / hotfix / feature
- **repo**: Which repository
- **last_indexed**: Timestamp of last sync
- **chunk_count**: Number of indexed chunks

### Tier classification

| Pattern | Tier |
|---------|------|
| main / master | production |
| develop / development | integration |
| release_* / release/* | release |
| hotfix/* / hotfix_* | hotfix |
| feature/* / feature_* | feature |

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
