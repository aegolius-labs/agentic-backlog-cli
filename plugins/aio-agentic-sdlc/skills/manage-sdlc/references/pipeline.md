# Delivery pipeline

## 1. Intake

Identify the authoritative input: direct prompt, `.aio-agentic-sdlc/inbox/`,
`.aio-agentic-sdlc/changes/`, `.aio-agentic-sdlc/specs/`, or the agentic
backlog. For new requirements, follow [roles/intake.md](roles/intake.md). Do not invent missing
product decisions when they would materially change scope.

## 2. Architecture and planning

Follow [roles/architect.md](roles/architect.md). Ground the breakdown in the accepted PRD and fresh
research. Create structural dependency nodes before detailed just-in-time task specs. Use the
framework tools for documents and DAG state.

## 3. Reality reconciliation

Follow [roles/cartographer.md](roles/cartographer.md). Generate the Reality DAG, validate GUID
traceability, run evidence-gated identity reconciliation, classify drift, and route the repair.
Only identical canonical GUIDs are confirmed. Exact structural matches remain approval-required
candidates, and unmatched Reality observations are unclassified rather than deletion candidates:

- Reality drift: accepted intent is not implemented; route to the implementer.
- Intention drift: code exists without accepted intent; route to the architect for validation.
- Tooling drift: the framework cannot represent or detect the state; record a framework blocker.

Run `triage_reconciliation_drift` before adding reconciliation work to the backlog. Treat its plan
digest as stale after either canonical DAG changes. Only items classified as
`missing_implementation` with `implementation_authorized: true` may proceed to implementation.
Route `obsolete_or_unapproved_intent` to Intake/Architecture and
`framework_tooling_drift` to framework maintenance; never convert either into product code work.

When reconciliation yields exactly one supported structural candidate, run `review_mapping` and
present its human decision brief. Ask an authorized human whether the implementation responsibility,
public surface, documentation, and related-test evidence justify linking the candidate to the
Intention node. Structural matching and test references are not behavioral proof, so defer is the
default. Only after an explicit identity-linkage decision may `approve_mapping` atomically add the
canonical source marker and audit receipt. GUIDs and the digest are audit inputs, and any changed
digest, intent, or source requires a new review and approval.

## 4. Implementation

Pull the highest-priority unblocked node with the MCP tool. Follow
[roles/implementer.md](roles/implementer.md) using the exact micro-spec and a red-green-refactor
loop. Make the smallest coherent change.

## 5. Static and runtime validation

Run [roles/linter.md](roles/linter.md), then [roles/qa.md](roles/qa.md). Route actionable failures
back to implementation and repeat. Do not promote a spec while validation is failing.

## 6. Acceptance and delivery

After QA passes:

1. Have the cartographer promote the accepted spec with the MCP tool.
2. Follow [roles/scribe.md](roles/scribe.md) for user-facing documentation.
3. Follow [roles/devops.md](roles/devops.md) only for VCS actions authorized by the user.
4. Report artifacts, state transitions, and validation evidence.
