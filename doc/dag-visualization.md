# DAG visualization and comparison

Use the read-only visualization surface to inspect canonical Intention and Reality DAGs without
opening or parsing their raw YAML. The CLI and MCP tool load the workspace DAGs, validate them,
apply deterministic bounds, and render the same report as name-first text, safe Mermaid, or JSON.
They do not change source, DAG, backlog, audit, or lock state.

## Choose a view

| View | Shows |
| --- | --- |
| `intention` | Selected Intention nodes and intended relationships. |
| `reality` | Selected Reality nodes, observed relationships, and exact source locations when fresh evidence is available. |
| `comparison` | Intention records classified as `confirmed`, `candidate`, `ambiguous`, or `unmapped`, plus unclassified Reality records and both relationship sets. |

`--focus-node UUID` restricts the report to the focus node and its incoming and outgoing
neighborhood. `--depth 0` selects only the focus node; larger depths follow both edge directions.
The focus GUID must exist in the selected view, or in either DAG for `comparison`.

The complete CLI shape is:

```text
uv run --no-sync dag-tool visualize --project-path PATH \
  --view intention|reality|comparison [--focus-node UUID] [--depth 1] \
  [--max-items 100] [--max-edges 200] [--max-candidates 20] \
  [--format human|mermaid|json]
```

The MCP equivalent is `visualize_dag`. Pass the absolute repository root as `project_path`; use
`focus_node_id` and `output_format` for the MCP names of `--focus-node` and `--format`.

## Self-dogfood this repository

From this repository root in PowerShell, inspect the visualization capability and its immediate
Intention neighborhood:

```powershell
$projectPath = (Resolve-Path .).Path
uv run --no-sync dag-tool visualize `
  --project-path $projectPath `
  --view comparison `
  --focus-node 841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58 `
  --depth 1 `
  --max-items 20 `
  --max-edges 20 `
  --max-candidates 5 `
  --format human
```

Render the same bounded report as Mermaid for a visual review:

```powershell
uv run --no-sync dag-tool visualize `
  --project-path $projectPath `
  --view comparison `
  --focus-node 841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58 `
  --depth 1 `
  --max-items 20 `
  --max-edges 20 `
  --max-candidates 5 `
  --format mermaid
```

Use JSON when checking complete evidence and truncation metadata:

```powershell
uv run --no-sync dag-tool visualize `
  --project-path $projectPath `
  --view comparison `
  --focus-node 841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58 `
  --depth 1 `
  --max-items 20 `
  --max-edges 20 `
  --max-candidates 5 `
  --format json
```

The human renderer leads with node names, types, and classifications. Mermaid uses synthetic node
identifiers and bounded, entity-escaped labels; it emits no links, click directives, raw HTML, or
frontmatter. The JSON renderer exposes the complete report schema for automation and audit.

## Interpret the evidence

- `summary` contains complete available and selected node totals, classification totals, and the
  total intended and observed relationships in the selected neighborhood.
- `limits.records` reports the record maximum, complete total, returned count, and truncation.
  `limits.intended_relationships` and `limits.observed_relationships` do the same independently for
  edges.
- `candidate_limit` and each `source_evidence.limit` expose complete nested totals even when
  `--max-candidates` truncates returned candidates or source locations.
- `source_discovery.state` is `available` only when an in-memory fresh Reality generation exactly
  matches the loaded canonical Reality DAG. If generation fails or the snapshots differ, exact
  source locations are withheld and the reason is reported rather than inferred.
- `evidence_state.behavioral_verification` is always `unavailable`. Classification, source
  locations, and related test references establish neither behavioral correctness nor acceptance
  of the intent.

Human and Mermaid output are concise review surfaces. Use JSON whenever complete limit,
truncation, source-location, or reconciliation evidence must be audited.

## Use visualization in mapping review

Before asking a human to approve an Intention-to-Reality identity mapping, present a
`comparison` view in human or Mermaid format. It provides orientation across intended and observed
names, identities, and relationships, but it is not an approval artifact.

Then run `review_mapping` immediately before the decision and present its fresh, source-bound human
decision brief. Only `approve_mapping` consumes the exact reviewed candidate and evidence digest.
Visualization does not replace that two-step gate, prove behavior, or authorize a mapping.
