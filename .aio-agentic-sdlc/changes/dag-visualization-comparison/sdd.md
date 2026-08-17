---
document_type: sdd
title: "DAG Visualization and Comparison"
author: "sdlc_architect"
date: "2026-08-17"
related_prd: "intention:841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58"
node_id: "841ddc3e-b7a2-57d3-80f1-bfb5ef9c6f58"

---
# DAG Visualization and Comparison

## 1. Architecture Overview

Add one read-only DAGVisualizationEngine that validates canonical DAG inputs, delegates identity classification to ReconciliationEngine, and produces one deterministic bounded report. Pure human and Mermaid renderers consume that report; CLI and MCP adapters contain no traversal or matching logic. No runtime Mermaid dependency is added.

## 2. System Components

- DAGVisualizationEngine: Intention, Reality, focused-neighborhood, and comparison report construction.
- ReconciliationEngine: authoritative confirmed, candidate, ambiguous, and unmapped classification.
- render_dag_human / render_dag_mermaid: safe name-first presentation.
- dag-tool visualize and visualize_dag MCP: equivalent adapters over canonical local workspace state.
- manage-sdlc Cartographer guidance: present visual evidence before identity approval.

## 3. Data Model

Schema version 1 includes view, focus/depth, complete summary totals, record/edge/candidate limits, bounded records, intended and observed relationships, reconciliation classification, explicit evidence state, and optional exact SourceLocation evidence. Selection is deterministic by distance then canonical GUID; edge order is canonical source, target, type, description.

## 4. API Design

- CLI: `dag-tool visualize --project-path PATH --view intention|reality|comparison` with optional focus, depth, item, edge, candidate, and format bounds.
- MCP: `visualize_dag` exposes the same view, focus, depth, bounds, and output format.
- Both adapters reject invalid limits, invalid DAGs, unknown focus nodes, and unsupported formats.

## 5. Security Considerations

- Never mutate DAG, backlog, audit, source, or lock state.
- Validate canonicalized DAG identities and relationships before traversal.
- Bound node, edge, candidate, nested-source, and text output while retaining complete totals and truncation metadata.
- Mermaid uses fixed synthetic identifiers and quoted, entity-escaped bounded labels. It emits no links, click directives, raw HTML, frontmatter, or user-provided directives.
- Missing or stale source provenance is reported unavailable and never inferred.
- Test references do not establish behavioral verification.
