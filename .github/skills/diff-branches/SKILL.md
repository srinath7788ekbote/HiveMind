---
name: diff-branches
description: >
  Structured diff between two Git branches, categorized by file type
  (pipeline/terraform/helm/other).
---

## When to use this skill

- "What changed between develop and release_26_1"
- "Diff branches X and Y"
- "What's different in release vs develop"
- Understanding what was modified between branches
- Pre-release change audit

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/diff_branches.py "{branch1}" "{branch2}" --client {client}
```

To diff a specific file:

```
python tools/diff_branches.py "{branch1}" "{branch2}" "{file_path}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --repo | Diff specific repo only | --repo terraform-infra |

## Output

Returns a structured diff grouped by category:
- **pipeline_changes**: Modified pipeline YAML files
- **terraform_changes**: Modified .tf files
- **helm_changes**: Modified Helm chart files
- **other_changes**: All other modified files

Each change includes:
- **file_path**: Path to the changed file
- **change_type**: added / modified / deleted
- **repo**: Which repository

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
