---
name: impact-analysis
description: >
  Blast radius finder -- given an entity, finds everything that depends on it
  and classifies risk as LOW/MEDIUM/HIGH/CRITICAL.
---

## When to use this skill

- "Impact of changing X"
- "What breaks if X changes"
- "Blast radius of modifying Y"
- "Safe to modify X?"
- "What uses X"
- Pre-change risk assessment

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/impact_analysis.py "{entity}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --depth | Max traversal depth | --depth 3 |
| --branch | Filter by branch | --branch develop |

## Output

Returns a blast radius report:
- **entity**: The entity being analyzed
- **risk_level**: LOW / MEDIUM / HIGH / CRITICAL
- **direct_dependents**: Entities directly affected (depth 1)
- **transitive_dependents**: Entities indirectly affected (depth 2+)
- **affected_files**: All files that reference this entity
- **summary**: Human-readable impact narrative

### Risk classification

| Dependent Count | Risk Level |
|----------------|------------|
| 0-2 | LOW |
| 3-5 | MEDIUM |
| 6-10 | HIGH |
| 10+ | CRITICAL |

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
