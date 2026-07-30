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
- RECONCILE-AC3: Reports and safe diffs are deterministically bounded at both the top level and nested candidate level, and expose totals plus truncation metadata.

### Test strategy

Use behavior-driven fixtures containing true GUID matches, mixed-case textual GUID forms, unique normalized-name matches, Unicode and empty normalization keys, duplicate-name ambiguity, type mismatches, unmatched reality, duplicate or reordered edges, and over-limit results.
Verify exact classifications, bounded nested evidence, complete totals, deterministic ordering, mutation-free operation, protected-state output rejection, safe default diff output, explicit legacy compatibility, CLI JSON, and MCP JSON.

## 2. System Components

1. `ReconciliationEngine`: compares canonical Intention nodes with observed Reality nodes using deterministic signals only.
2. `ReconciliationReport`: versioned JSON-safe totals, mappings, candidates, ambiguities, unmapped nodes, and truncation metadata.
3. `DiffPolicy`: safe default versus explicitly requested legacy structural behavior.
4. `DiffingEngine`: consumes reconciliation output and produces bounded review tasks in safe mode.
5. CLI and MCP adapters: expose the same read-only report without duplicating policy logic.

## 3. Data Model

Each reconciliation record contains the canonical intent ID, optional Reality ID, classification, normalized evidence, and whether human approval is required.
Confirmed records require the same canonical GUID value; original textual forms remain visible as source evidence. Duplicate textual forms of one canonical GUID fail closed. Candidate records require exactly one type-compatible normalized-name match.
Multiple matches are ambiguous. No match is unmapped. Unmatched Reality observations are summarized separately and are never deletion evidence.
Reports carry `schema_version`, complete category totals, `returned_items`, `max_items`, and `truncated`. Each non-confirmed intent record also carries complete candidate totals and a configurable bounded candidate list.

## 4. API Design

`ReconciliationEngine(intention, reality).analyze(max_items=..., max_candidates=...)` returns a serializable report.
`DiffingEngine(..., policy=DiffPolicy.safe(max_tasks=..., max_candidates=...)).calculate_diff()` is the default and creates reconciliation-review work only.
`DiffPolicy.legacy_structural()` preserves the former raw structural algorithm for explicit callers.
`dag-tool reconcile --intention ... --reality ... --max-items ... --max-candidates ...` prints JSON. MCP `reconcile_dags(project_path, max_items, max_candidates)` returns the same JSON report.

## 5. Security Considerations

Reconciliation is read-only and must not inject source markers, rewrite either DAG, or mutate backlog, audit, or lock state. Report output rejects protected framework-state paths.
Candidate matching is deterministic and exact after normalization; semantic similarity cannot approve mappings.
Destructive operations are absent from safe mode. Bounded collectors and indexed matching constrain memory, CPU, and prompt size while preserving full totals.
CLI and MCP paths use existing validated DAG loading and project-root containment conventions.
