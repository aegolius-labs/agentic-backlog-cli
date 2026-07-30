---
document_type: sdd
title: "Evidence-Gated Reconciliation Baseline"
author: "sdlc_architect"
date: "2026-07-30"
related_prd: "specs/bootstrapping-legacy-reingestion/prd.md"
node_id: "9015c8a3-fd14-5598-916d-d03fcf41e415"

---
# Evidence-Gated Reconciliation Baseline

## 1. Architecture Overview

Canonical Intention DAG node: `9015c8a3-fd14-5598-916d-d03fcf41e415`. Add a deterministic, read-only reconciliation layer before backlog diffing.
The layer classifies identity matches and structural candidates but never upgrades a candidate to an approved mapping.
Safe planning treats unmatched Reality observations as unclassified and unmatched Intention nodes as reconciliation work, not proof that code must be created.
Legacy structural create/delete behavior remains available only through an explicit compatibility policy.

### Acceptance criteria

- RECONCILE-AC1: Reports classify confirmed GUID matches, unique structural candidates, ambiguous candidates, and unmapped intent with concrete evidence.
- RECONCILE-AC2: Default planning emits no create, remove, or disconnect task solely from a GUID mismatch.
- RECONCILE-AC3: Reports and safe diffs are deterministically bounded and expose totals plus truncation metadata.

### Test strategy

Use behavior-driven fixtures containing true GUID matches, unique normalized-name matches, duplicate-name ambiguity, type mismatches, unmatched reality, and over-limit results.
Verify exact classifications, evidence, deterministic ordering, mutation-free operation, safe default diff output, explicit legacy compatibility, CLI JSON, and MCP JSON.

## 2. System Components

1. `ReconciliationEngine`: compares canonical Intention nodes with observed Reality nodes using deterministic signals only.
2. `ReconciliationReport`: versioned JSON-safe totals, mappings, candidates, ambiguities, unmapped nodes, and truncation metadata.
3. `DiffPolicy`: safe default versus explicitly requested legacy structural behavior.
4. `DiffingEngine`: consumes reconciliation output and produces bounded review tasks in safe mode.
5. CLI and MCP adapters: expose the same read-only report without duplicating policy logic.

## 3. Data Model

Each reconciliation record contains the canonical intent ID, optional Reality ID, classification, normalized evidence, and whether human approval is required.
Confirmed records require identical GUIDs. Candidate records require exactly one type-compatible normalized-name match.
Multiple matches are ambiguous. No match is unmapped. Unmatched Reality observations are summarized separately and are never deletion evidence.
Reports carry `schema_version`, complete category totals, `returned_items`, `max_items`, and `truncated`.

## 4. API Design

`ReconciliationEngine(intention, reality).analyze(max_items=...)` returns a serializable report.
`DiffingEngine(..., policy=DiffPolicy.safe()).calculate_diff()` is the default and creates reconciliation-review work only.
`DiffPolicy.legacy_structural()` preserves the former raw structural algorithm for explicit callers.
`dag-tool reconcile --intention ... --reality ... --max-items ...` prints JSON. MCP `reconcile_dags(project_path, max_items)` returns the same JSON report.

## 5. Security Considerations

Reconciliation is read-only and must not inject source markers, rewrite either DAG, or mutate backlog state.
Candidate matching is deterministic and exact after normalization; semantic similarity cannot approve mappings.
Destructive operations are absent from safe mode. Output limits constrain memory and prompt size while preserving full totals.
CLI and MCP paths use existing validated DAG loading and project-root containment conventions.
