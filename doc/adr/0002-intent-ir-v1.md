# ADR 0002: Intent IR v1

- Status: Accepted
- Date: 2026-07-23

## Context

The Intention DAG identifies desired components and relationships, but its existing node fields do
not explain where an interpretation came from, which assumptions or ambiguities shaped it, what
observable evidence would satisfy it, or whether anyone approved it. Agents could therefore
produce structurally valid YAML that was difficult to audit and easy to overstate.

## Decision

Intention DAG nodes may carry an `intent` payload conforming to the strict, versioned Intent IR v1
schema. The payload records:

- one or more provenance statements with durable source references;
- explicit assumptions, unresolved or resolved ambiguities, and bounded confidence;
- uniquely identified acceptance criteria with at least one required evidence reference each;
- a monotonic revision history with the responsible actor and generator version;
- the currently responsible agent and generator version; and
- an explicit draft, review-required, approved, or rejected state with approval audit fields.

Unknown fields fail validation. Revision history starts at one and increases strictly. Approved
intent requires both an approver and approval timestamp. Existing DAG nodes remain loadable without
an Intent IR payload during migration, while `dag-tool validate-intent` defaults to strict coverage
and fails when any node is missing the payload.

`dag-tool intent-summary` renders the interpretation for review without requiring a person to read
or edit raw graph YAML. State mutation remains the responsibility of framework tools; these review
and validation commands do not mutate the DAG.

`set_intent` and `dag-tool intent set` are the supported single-node Intent IR mutation surfaces.
They serialize writes with a local lock, require the caller's expected revision, preserve existing
history, append exactly one revision, and atomically replace the DAG file.

The framework-managed legacy migration surface consists of `dag-tool intent inventory`,
`plan-migration`, and `apply-migration`. The compiler uses only exact preserved descriptions,
described relationships, and exact-title framework documents as provenance. Every mechanically
compiled payload remains `review_required` with an open ambiguity. Plans cover every legacy node in
canonical GUID order, bind the source DAG and each node fingerprint, and carry a content digest.
Apply recompiles and validates the complete plan under the canonical DAG lock before one atomic
replacement; stale, incomplete, modified, re-digested, or mechanically approved plans fail without
mutation.

## Consequences

- Human statements and imported sources remain traceable through subsequent agent transformations.
- Acceptance criteria state their required evidence before implementation is judged complete.
- Low-confidence interpretations and open ambiguities are visible before downstream execution.
- Legacy DAGs can migrate atomically into strict coverage while retaining explicit review gates.
- Structural node creation and a benchmarked Intake-to-Intent translation loop remain necessary
  before the framework can fully dogfood its roadmap.

## Alternatives Considered

- Storing the fields in the existing free-form `attributes` dictionary was rejected because it
  cannot provide a stable, validated contract.
- Requiring every existing node to migrate immediately was rejected because it would make current
  projects unreadable before framework-managed migration tooling exists.
- Treating confidence or approval as prose was rejected because downstream policy needs bounded,
  machine-readable values.
