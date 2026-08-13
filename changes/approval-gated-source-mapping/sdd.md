---
document_type: sdd
title: "Approval-Gated Source Mapping"
author: "sdlc_architect"
date: "2026-08-07"
related_prd: "specs/bootstrapping-legacy-reingestion/prd.md"
node_id: "6317643a-a8fc-5026-b373-9330004bc90d"

---
# Approval-Gated Source Mapping

## 1. Architecture Overview

Canonical Intention DAG node: `6317643a-a8fc-5026-b373-9330004bc90d`. Add a two-step review/approve transition on top of read-only reconciliation.

Review always generates fresh Reality evidence in memory and binds one candidate to an exact Python source symbol through a deterministic digest. Approval re-runs review under a project lock, requires an exact digest and explicit audit fields, inserts source evidence atomically, and verifies a fresh scan before returning success.

### Acceptance criteria

- MAPPING-AC1: Review binds one fresh candidate to source path, symbol location, source hash, and evidence digest without mutation.
- MAPPING-AC2: Non-candidates, unsupported symbols, stale evidence, mismatches, duplicate markers, and path escapes fail without mutation.
- MAPPING-AC3: Approval atomically writes an adjacent canonical marker plus audit receipt and rolls back if fresh Reality verification fails.
- MAPPING-AC4: Python API, CLI, MCP, and Codex role guidance expose one consistent contract.

### Test strategy

Use real temporary Python projects and the actual tree-sitter Reality generator. Verify exact review evidence, successful marker placement before plain and decorated definitions, confirmed identity after regeneration, byte-identical rejection paths, stale-source protection, containment, audit validation, rollback, CLI JSON, and MCP JSON.

Tests must exercise the real parser and filesystem transition rather than mocked coverage-only branches.

## 2. System Components

1. `RealityDAGGenerator.source_locations`: ephemeral source provenance keyed by observed GUID; it is not serialized into canonical DAG state.
2. `TreeSitterVisitor`: recognizes definition-adjacent canonical markers and records exact Python symbol locations.
3. `MappingEngine`: creates fresh review evidence and performs the guarded atomic transition.
4. `MappingApproval`: strict approver, timestamp, rationale, candidate, and evidence-digest contract.
5. CLI and MCP adapters: expose review and approval without duplicating policy logic.

## 3. Data Model

A mapping review contains `schema_version`, classification, canonical intent summary, observed candidate summary, normalized structural signals, source path, symbol kind/name, definition and insertion lines, source SHA-256, and `evidence_digest`. The digest covers all identity and source-bound evidence with canonical JSON ordering.

A successful source receipt is two adjacent comments: a stable JSON approval record followed immediately by `aio-sdlc-node: <canonical-guid>`. The receipt retains the prior Reality candidate GUID, pre-write source hash, approver, timezone-aware approval time, rationale, and evidence digest.

Operational source locations remain ephemeral so regenerating `reality-dag.yaml` does not create location-only churn.

## 4. API Design

`MappingEngine(project_root, intention_path).review(intent_id)` returns JSON-safe fresh evidence without mutation.

`MappingEngine(...).approve(intent_id, reality_id, evidence_digest, approval)` accepts only the unique candidate represented by that exact current digest. It returns the durable receipt and post-write confirmed evidence.

`dag-tool mapping review` and `dag-tool mapping approve` expose the same operations. MCP tools `review_mapping` and `approve_mapping` return the same JSON payloads. Reality regeneration remains an explicit framework operation after approval.

## 5. Security Considerations

Resolve every source path beneath the project root and reject escaping symlinks. Serialize mapping transitions with a dedicated ignored mapping lock. Recompute fresh Reality and source hashes under the lock; stale evidence fails closed. Scan for an existing canonical marker before writing.

Preserve file bytes, newline convention, indentation, and mode outside the inserted receipt. Write through a flushed temporary file and atomic replacement. After insertion, regenerate Reality and require the canonical Intention GUID at the same source symbol; on any verification failure restore the original bytes atomically.

Never modify the Intention DAG, Reality DAG, backlog, or their transaction audit and lock state as a side effect of source approval.
