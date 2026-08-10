# Delivery pipeline

## 1. Intake

Identify the authoritative input: direct prompt, `inbox/`, `changes/`, `specs/`, or the agentic
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

When reconciliation yields exactly one supported structural candidate, run `review_mapping` and
ask an authorized human to accept or reject the exact candidate, source path, and evidence digest.
Only after that explicit decision may `approve_mapping` atomically add the canonical source marker
and audit receipt. A changed digest or source requires a new review and a new approval.

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
