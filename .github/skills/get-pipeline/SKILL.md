---
name: get-pipeline
description: >
  Deep parse a Harness pipeline -- returns stages, templateRefs, serviceRefs,
  envRefs, variables, triggers. Use for pipeline structure questions.
---

## When to use this skill

- "What does pipeline X do"
- "What stages does X have"
- "What templates does pipeline X use"
- "What services does pipeline X deploy"
- Understanding pipeline structure, approval gates, and triggers

## How to invoke

Run this command and use the output as evidence in your answer:

```
python tools/get_pipeline.py "{pipeline_name}" --client {client}
```

## Flags

| Flag | Purpose | Example |
|------|---------|---------|
| --client | Override active client | --client dfin |
| --branch | Look at specific branch version | --branch release_26_1 |

## Output

Returns a structured pipeline breakdown:
- **name**: Pipeline identifier
- **file_path**: Source pipeline.yaml file
- **stages**: Ordered list of stages with:
  - Stage name and type (deploy, approval, custom)
  - Steps within each stage
  - templateRef references
  - serviceRef references
  - environmentRef references
- **variables**: Pipeline-level variables
- **triggers**: What triggers this pipeline

## Citation rule

Every result includes a file_path. Cite it in your answer as:
`file_path (relevance: {pct}%)`
