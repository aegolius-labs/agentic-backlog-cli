---
name: manage-sdlc
description: Manage spec-driven software delivery with the AIO Agentic SDLC dual-DAG backlog and MCP tools. Use when Codex needs to interview for a PRD, detect duplicate requirements, plan or execute a feature through architect/implementer/QA roles, prioritize or update the agentic backlog, generate or reconcile intention and reality DAGs, triage reconciliation drift, review or approve source mappings, validate GUID traceability, promote accepted specs, or prepare documentation and delivery.
---

# Manage AIO Agentic SDLC

Use deterministic MCP tools for state and artifacts. Use Codex reasoning for requirements,
architecture, implementation, review, and coordination.

## Select the workflow

- For feature ideation, discovery, or PRD work, read
  [references/roles/intake.md](references/roles/intake.md) and the researcher role it links to.
- For implementation, bug fixes, or end-to-end delivery, read
  [references/pipeline.md](references/pipeline.md) and
  [references/roles/orchestrator.md](references/roles/orchestrator.md).
- For a direct backlog, DAG, traceability, document-generation, or promotion request, read
  [references/tools.md](references/tools.md) and perform only that operation.
- For role-specific work delegated by an orchestrator, read only the matching file under
  `references/roles/` plus [references/safeguards.md](references/safeguards.md).

## Initialize context

1. Resolve the repository root to an absolute path.
2. Read the applicable `AGENTS.md` chain and the requested PRD or task artifact.
3. Inspect `.aio-agentic-sdlc/intention-dag.yaml`,
   `.aio-agentic-sdlc/reality-dag.yaml`, and runtime backlog state only as needed.
4. Pass the absolute repository root as `project_path` to every MCP tool that accepts it.
5. Prefer plugin MCP tools. If unavailable, use the local UV environment with `uv run`.
   Use the portable `uvx --from git+https://github.com/aegolius-labs/aio-agentic-sdlc`
   form only when the local checkout is not the intended implementation.

## Coordinate roles

- Keep one main agent responsible for state transitions and the final answer.
- Delegate only bounded, independent work when subagents are available and delegation is allowed.
  Prefer the matching project-scoped `sdlc_*` custom agent when it exists; otherwise give a
  generic subagent the matching role reference.
- Give each subagent the absolute repository path, exact artifact path, role reference,
  allowed files/actions, and expected return shape.
- Do not let multiple agents mutate the same files or DAG state concurrently.
- Run implementation and QA as a feedback loop until QA passes or a genuine blocker is recorded.
- Keep commits, pushes, pull requests, issue changes, and other external writes within the user's
  explicit authorization.

## Enforce invariants

- Never edit `.aio-agentic-sdlc/intention-dag.yaml`,
  `.aio-agentic-sdlc/reality-dag.yaml`, or backlog state by hand. Use MCP, CLI,
  or the Python API.
- Never manually alter generated document frontmatter or promote a spec with filesystem moves.
- Preserve canonical GUID traceability across DAG nodes, specifications, and source markers.
- Use UV for Python environment and command execution.
- Work test-first for implementation changes and run proportionate validation before completion.
- Follow [references/safeguards.md](references/safeguards.md) for blocking and delivery rules.

## Return results

State the outcome first. Include changed artifact paths, DAG/backlog transitions, validation
commands and results, and any unresolved blocker. Avoid dumping subagent transcripts.
