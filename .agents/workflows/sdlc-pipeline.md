---
name: sdlc-pipeline
description: A comprehensive, stack-agnostic SDLC workflow that handles Intake, Breakdown, Planning, Implementation, and Testing. It dynamically adapts to the intake source (Agentic Backlog, Spec-Kit, Jira/AzDO, or Prompt) and leverages subagents for parallel execution.
---

# SDLC Pipeline Workflow

This workflow enforces a clean Software Development Life Cycle (SDLC) across any stack. The agent MUST follow these stages sequentially unless explicitly instructed otherwise.

## 1. Intake

Determine the source of the requested work and ingest the requirements.

* **Agentic Backlog**: If instructed to work from the backlog, use the `aio-agentic-sdlc` skill to fetch the highest priority `TODO` item.
* **Spec-Kit / Open-Spec**: If pointed to `.aio-agentic-sdlc/specs/`, read the relevant `.md` specification files to understand the requirements.
* **Jira / AzDO (External)**: If requested, attempt to use available MCP tools to read the specific ticket/issue.
* **User Prompt**: If none of the above, ingest the requirements directly from the user's conversational prompt.

## 2. Breakdown & Planning

Analyze the requirements and design the solution.

* **Architecture Diagram**: Create or update the Mermaid architecture diagram in the `doc/` folder to reflect the upcoming changes.
* **Component Isolation**: Identify logically distinct components, layers, or modules that need to be built.
* **Parallelization Check (Delegation)**:
  * *Rule*: If the feature requires extensive research on 3rd-party libraries, invoke a `research` subagent to evaluate options concurrently.
  * *Rule*: If the architecture spans completely decoupled domains (e.g., a database migration vs. a UI component), prepare to delegate them to separate subagents in the Implementation phase.

## 3. Branching & Setup

Prepare the environment.

* Do NOT work on `main` or `master`.
* Create a new branch following Conventional Branching (e.g., `feature/ticket-123`, `bugfix/login-crash`).

## 4. Implementation (TDD Enforced)

Execute the work following Test-Driven Development. This is stack-agnostic (the specific testing framework depends on the workspace).

* **Write Tests First**: Write unit/integration tests based on the acceptance criteria gathered during Intake.
* **Parallel Implementation (Delegation)**:
  * For large, decoupled components identified in the Planning phase, use `invoke_subagent` (type: `self`) to implement them in parallel.
  * Assign specific subagents to specific modules and monitor their progress.
* **Write Code**: Implement the solution until all tests pass locally.

## 5. Comprehensive Testing & Validation

Verify the integrity of the system before completion.

* **Automated Tests**: Ensure all unit and integration tests are passing.
* **Parallel Validation (Delegation)**:
  * If applicable (e.g., web apps), spawn a subagent to perform visual/UI DOM inspection while the main agent handles backend integration tests.
  * Use a subagent to attempt basic security/edge-case fuzzing if the feature handles user input.
* **Builds**: Verify the project builds successfully.

## 6. Wrap-up & PR

Finalize the scope of work.

* **Documentation**: Ensure durable behavior and architectural decisions are documented in `doc/`.
* **State Reconciliation**: If using `aio-agentic-sdlc` or external trackers (Jira/AzDO), update the status of the task to `DONE` or `IN_REVIEW`.
* **Commit & PR**: Write Conventional Commits and open a Pull Request against `main`.
