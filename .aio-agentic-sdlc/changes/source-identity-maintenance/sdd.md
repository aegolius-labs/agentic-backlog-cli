---
document_type: sdd
title: "Add Explicit Source Identity Maintenance"
author: "sdlc_architect"
date: "2026-08-21"
related_prd: ".aio-agentic-sdlc/changes/source-identity-maintenance/prd.md"
node_id: "15019926-c6be-5c98-b558-954c7657e5c6"

---
# Add Explicit Source Identity Maintenance

## 1. Architecture Overview

Extend the existing `MappingEngine` owned by parent capability `6317643a-a8fc-5026-b373-9330004bc90d`; do not create a second mapping store or ontology.
The approved node is one cohesive implementation slice because explicit selection and receipt refresh share the same fresh-Reality scan, exact-symbol resolver, evidence envelope, approval model, workspace lock order, guarded source replacement, and post-write verification.

Preserve the current automatic name-matched review and approval as the default. An optional exact observed Reality GUID selects a differently named class or function without trusting caller-supplied paths, symbols, or line numbers.
A separate receipt-review/refresh path applies only to an already confirmed canonical marker and replaces its one adjacent receipt while preserving that marker byte-for-byte.
Both paths are read-only until an exact fresh digest is approved with approver, timezone-aware timestamp, and rationale. Mapping remains source-identity evidence only and never becomes behavioral or requirement approval.

Public reviews acquire the workspace-migration lock and persistent mapping lock in that order, then operate on the canonical Intention DAG and a newly generated in-memory Reality DAG. Approvals acquire the same locks and replay the exact review internally before any write. Reviews do not persist Reality, reconciliation, backlog, or canonical DAG state. No dependency or external service is added.

## 2. System Components

1. **Mapping core (`src/aio_agentic_sdlc/mapping.py`)**: factor a lock-free internal review primitive called only beneath the public lock boundary; support automatic or explicit observed-candidate selection; add confirmed-receipt review and refresh.
   Retain the existing decision-brief renderer and add a receipt-maintenance brief with GUIDs and digests only in its final audit section.
2. **Receipt parsing (`src/aio_agentic_sdlc/source_markers.py`)**: parse only a complete adjacent `aio-sdlc-mapping-approval` comment; reject duplicate JSON keys, unknown receipt shapes, noncanonical GUIDs, oversized receipts, malformed timestamps, mismatched intent/symbol/path, duplicate receipts, or anything other than one class/function marker-receipt pair.
   Provide annotation-neutral whole-file bytes by removing exactly the adjacent receipt and marker lines; do not introduce symbol-scoped hashing.
3. **Guarded source transition**: under the existing migration-then-mapping lock order, open the source without following links, bind descriptor and leaf identities, require one regular non-hardlinked leaf, preserve mode/newline/indentation, write and fsync a same-directory temporary, revalidate the original leaf immediately before replacement, then verify fresh Reality.
   Roll back to the exact original bytes and mode on a post-write failure without overwriting a leaf whose identity was externally swapped. Candidate approval inserts one receipt plus marker; receipt refresh replaces only the receipt line.
4. **Python, CLI, and MCP adapters**: keep existing APIs valid, add optional explicit selection to review/approve, and expose receipt review/refresh as distinct operations.
   Existing required fields, defaults, tool names, resources, prompt, and error semantics remain unchanged; the MCP inventory grows additively from 21 to 23 tools.
5. **Codex guidance and product documentation**: document exact commands, identity-only semantics, digest replay, separate human approval, stale-receipt interpretation, and safe regeneration.
6. **Verification and self-dogfood evidence**: add focused unit/adversarial/concurrency tests plus CLI/MCP parity and v2 auto/legacy protocol tests.
   After QA, generate bounded review reports for the MCP v2 representative and the two stale confirmed receipts without modifying any of those three identities.

## 3. Data Model

Use mapping review schema version 3 for new reports while accepting the existing automatic workflow. Every report contains `operation` (`candidate_mapping` or `receipt_refresh`), `selection_mode` (`automatic_name_match`, `explicit_observed_guid`, or `confirmed_marker`), bounded human decision data, `approval` support/blockers, and one SHA-256 `evidence_digest` only when approval is safe.

The canonical digest envelope is deterministic JSON (`sort_keys=true`, compact separators, UTF-8) and binds schema, operation, selection mode, the full selected Intent semantics, and canonical Intention-DAG SHA-256.
It also binds the fresh relevant Reality node; exact source path, kind, symbol, and line coordinates; raw and annotation-neutral whole-file SHA-256 values; bounded structural/test summaries; and, for refresh, the validated prior receipt plus its canonical SHA-256.
No caller-provided source metadata enters the envelope. Approval reruns the same operation and rejects any changed digest, selected Reality GUID, source identity, source bytes, marker, receipt, Intention DAG, or fresh Reality observation.

Candidate approval continues to emit the existing schema-1 receipt so current consumers remain compatible. Receipt refresh emits schema version 2 with stable identity fields (`intent_id`, original `candidate_reality_id`, source path/kind/name), current annotation-neutral `source_sha256`, and immutable `identity_approval` copied from schema 1 or preserved from schema 2.
Its latest `maintenance_approval` contains the fresh digest, approver, timestamp, rationale, and `supersedes_receipt_sha256`. Repeated refresh replaces only the latest maintenance approval and links it to the immediately prior receipt hash; it does not create an unbounded nested chain.

State transitions are ephemeral review gates: `unmapped/candidate -> reviewed candidate -> explicitly approved -> confirmed`, or `confirmed with parseable receipt -> reviewed refresh -> explicitly approved -> confirmed with refreshed receipt`. A rejection/defer or any error leaves all bytes and canonical state unchanged.
A review never records approval. The three dogfood reports are reproducible evidence under `.aio-agentic-sdlc/changes/source-identity-maintenance/`; they are not canonical state and cannot authorize a write.

## 4. API Design

### Python API

- `MappingEngine.review(intent_id, *, candidate_reality_id=None)` preserves automatic matching when the optional GUID is absent and selects exactly that current Reality observation when present. The explicit path requires compatible Intent/Reality node types, exactly one supported source location, and an unconfirmed class/function.
- `MappingEngine.approve(intent_id, reality_id, evidence_digest, approval, *, selection_mode="automatic_name_match")` preserves the existing default and requires `selection_mode="explicit_observed_guid"` for an explicit review.
- `MappingEngine.review_receipt_refresh(intent_id)` resolves exactly one current confirmed class/function marker and adjacent receipt.
- `MappingEngine.refresh_receipt(intent_id, evidence_digest, approval)` replays refresh review and replaces only that receipt.
- Public methods acquire locks; private review primitives never reacquire them. All expected failures raise bounded `MappingError`.

### CLI and MCP parity

- Extend `dag-tool mapping review` with optional `--candidate-reality-id` and `mapping approve` with optional `--selection-mode`; defaults preserve current scripts.
- Add `dag-tool mapping receipt review` and `dag-tool mapping receipt refresh`. Human output remains default; `--format json` is object-equivalent to Python output.
- Extend MCP `review_mapping` with optional `candidate_reality_id` and `approve_mapping` with optional `selection_mode`. Add `review_mapping_receipt` and `refresh_mapping_receipt`; valid results are JSON object-equivalent to CLI JSON and expected errors use the bounded tool-error channel.

### File-level implementation sequence

1. Add failing contract and safety tests in `tests/test_mapping.py` or a focused `tests/test_source_identity_maintenance.py`; extend `tests/test_dag_cli.py`, `tests/test_mcp_server.py`, `tests/test_mcp_v2_contract.py`, `tests/test_mcp_v2_concurrency.py`, and `tests/test_codex_plugin.py`.
2. Add strict receipt parsing/neutralization in `source_markers.py`, then implement selection, digest, locking, atomic update, rollback, and postcondition logic in `mapping.py`.
3. Wire `dag_cli.py` and `mcp_server.py`; update the normalized MCP v2 contract to 23 additive tools and exercise both official Client auto and legacy modes.
4. Update `plugins/aio-agentic-sdlc/skills/manage-sdlc/references/tools.md`, `doc/codex-plugin.md`, and any README surface count that would otherwise be false.
5. Produce `.aio-agentic-sdlc/changes/source-identity-maintenance/self-dogfood-review.json` and QA evidence only through fresh read-only tool calls. Do not approve or edit the three target source identities.

### Acceptance traceability

- `IDENTITY-MAINT-AC1`: explicit-selection unit tests plus CLI/MCP review parity.
- `IDENTITY-MAINT-AC2`: schema-1/schema-2 receipt parsing and deterministic read-only refresh review tests.
- `IDENTITY-MAINT-AC3`: digest replay, stale Intent/Reality/source/receipt tests, descriptor/leaf-swap tests, rollback injection, and concurrent approval/refresh tests.
- `IDENTITY-MAINT-AC4`: human-first rendering, JSON equivalence, v2 protocol inventory/calls, and Codex plugin/skill validators.
- `IDENTITY-MAINT-AC5`: traversal, symlink, Windows reparse-point, hardlink, duplicate marker/receipt, malformed JSON, stale writer, protected-state hash, and three-target self-dogfood evidence.

The post-QA Cartographer must present the exact human-readable candidate/receipt table and digests to Felix. Those identity approvals remain a separate gate and are not delegated to implementation or QA.

## 5. Security Considerations

Treat Reality GUIDs as selectors, never as trusted source metadata. Canonicalize all GUIDs and reject an explicit candidate already confirmed to any Intent, type-incompatible candidates, duplicate source locations, modules/variables, malformed source, and hidden duplicate canonical markers.
Receipt JSON uses a strict versioned model with duplicate-key rejection, bounded line/text sizes, timezone-aware approvals, and exact intent/path/kind/name agreement. Display strings are bounded and truncated with totals; source content is represented only by hashes and structural summaries.

Path containment is necessary but insufficient: reject symlinked or reparse-point parents/leaves, nonregular leaves, hardlinks, and changed device/inode identities. Revalidate after acquiring locks and immediately before atomic replacement.
Preserve CRLF/LF, decorator adjacency, indentation, and read-only mode behavior already guaranteed by guarded source updates. Failure before replacement performs no write; failure after replacement restores exact original bytes and mode when the written leaf is still owned by the transaction.
A detected hostile post-replacement leaf swap must fail closed without writing through the swapped path and surface a blocker rather than corrupt another file.

Use one persistent mapping lock for candidate and receipt operations and the established acquisition order: workspace migration lock, then mapping lock. This serializes MCP v2 worker threads and cooperative CLI/Python callers.
Approval always recomputes fresh evidence inside the lock, so concurrent or stale approvals cannot reuse an earlier digest. No operation changes canonical DAGs, backlog, state audit, semantic cache, or process cwd. Expected validation failures remain actionable and bounded; unexpected MCP failures remain sanitized.

Whole-file versus symbol-scoped provenance is explicitly out of scope. This milestone hashes the entire annotation-neutral file, so unrelated same-file changes intentionally stale a receipt and require another explicit refresh. A future symbol-scoped evidence design requires its own Intent, compatibility analysis, and approval.
