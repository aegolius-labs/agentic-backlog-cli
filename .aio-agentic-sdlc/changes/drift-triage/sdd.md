---
document_type: sdd
title: "Evidence-Bound Reconciliation Drift Triage"
author: "sdlc_architect"
date: "2026-08-15"
related_prd: ".aio-agentic-sdlc/specs/bootstrapping-legacy-reingestion/prd.md"
node_id: "9015c8a3-fd14-5598-916d-d03fcf41e415"

---
# Evidence-Bound Reconciliation Drift Triage

## 1. Architecture Overview

Add a deterministic, read-only triage layer between safe reconciliation and backlog execution.
It classifies every retained safe-plan subject as missing implementation, obsolete or unapproved
intent, framework-tooling drift, identity review, or still needing classification. Non-approved
intent can never authorize implementation. Explicit decisions are bound to canonical Intention and
Reality content through a reproducible plan digest.

### Acceptance criteria

- TRIAGE-AC1: Every safe-plan subject is routed without converting non-approved intent into coding work.
- TRIAGE-AC2: Explicit decisions are schema-valid, auditable, and stale after either canonical DAG changes.
- TRIAGE-AC3: Human output is name-first and GUID-last; JSON output has complete totals and bounded nested evidence.
- TRIAGE-AC4: CLI and MCP expose the same read-only contract, and report output cannot overwrite inputs or protected state.

### Test strategy

Exercise approved and review-required intent, supported and unsupported relationships, stale,
duplicate, unused, and inapplicable decisions, canonical hash stability across order and GUID case,
nested evidence limits, human rendering order, protected output paths, CLI persistence, MCP parity,
full warning-strict regression tests, and byte-for-byte dogfood regeneration after a package build.

## 2. System Components

1. `DriftTriageEngine` consumes validated DAG managers and the bounded safe plan.
2. `TriageDecisionSet` validates explicit, timestamped decisions and rejects stale or unused subjects.
3. CLI and MCP adapters expose the same JSON contract; the CLI also renders a GUID-last human brief.
4. Derived report writing reuses protected-path and atomic-write safeguards.
5. The Cartographer supplies explicit decisions only where deterministic routing cannot decide safely.

## 3. Data Model

The report carries canonical DAG hashes, a combined plan digest, complete classification totals,
bounded items, implementation authorization, reasons, approval evidence, and audit identifiers.
Review-required, draft, or rejected intent is automatically withheld as
`obsolete_or_unapproved_intent`. Relationships with non-approved endpoints are likewise withheld.
Unsupported relationship observation is `framework_tooling_drift`. Approved unmapped intent and
otherwise observable missing relationships remain `needs_classification` until a matching decision
set resolves them.

## 4. API Design

`DriftTriageEngine(intention, reality).analyze(decisions=..., max_items=...)` returns the versioned report.
`dag-tool triage --intention ... --reality ... [--decisions ...] [--format human|json] [--output ...]`
provides local access. MCP `triage_reconciliation_drift(project_path, decisions_json, max_items)`
returns the identical JSON result. Output is read-only and never mutates DAG or backlog state.

## 5. Security Considerations

Validate all limits and decision fields, require timezone-aware decision timestamps, and reject
duplicate, stale, unknown, or inapplicable subject keys. Never permit non-approved intent to authorize
implementation. Hash validated canonical DAG content rather than checkout bytes. Keep report output
and embedded acceptance criteria bounded, preserve complete totals, reject protected-state and
symlink or reparse output aliases, and use atomic replacement for derived JSON evidence.
