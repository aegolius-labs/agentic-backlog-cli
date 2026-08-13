# Product Requirement Document (PRD)

## Feature
Deprecate External Task Trackers & Refactor Configuration

## Summary
The transition to the Dual-DAG architecture creates a highly dynamic, fast-moving backlog natively calculated by diffing the Intention and Reality DAGs. Attempting to sync this ephemeral, high-speed task list to rigid 3rd-party task managers (like GitHub Projects, Jira, or ADO) introduces unnecessary friction, latency, and complexity. This feature officially deprecates all external issue tracker integrations and refactors the legacy configuration schema to match the new architecture.

## User Stories
- As a developer, I want the framework to rely purely on the local DAG diff for task prioritization so that execution cycles aren't wasted trying to sync state with an external UI.
- As a system administrator, I want a cleanly named, modern configuration file that only tracks settings relevant to the Dual-DAG engine, removing any confusion caused by legacy `agentic-backlog` naming.

## Requirements
- **Configuration Migration**: Rename the primary configuration schema from `.agentic-backlog.json` to a standardized `.aio-agentic-sdlc/config.json` (or `.yaml`).
- **Schema Refactor**: Remove legacy configuration fields related to external issue tracking (e.g., `github.project_number`, `github.is_org`, and related token scopes). Retain only what is necessary for repository routing or core engine behavior.
- **Codebase Clean-up**: Remove all framework logic dedicated to pushing, pulling, or syncing backlog tasks with GitHub Projects, GitHub Issues, ADO, Jira, or other external systems.
- **CLI Validation**: Update the CLI and underlying Orchestrator logic to parse the new configuration file and ignore the legacy one.

## Out of Scope
- Rebuilding or maintaining any form of API adapter for 3rd-party task managers. (This decision may be revisited in the future, but is strictly excluded from current architecture).

## Acceptance Criteria
1. The framework successfully boots and executes using the new `.aio-agentic-sdlc/config.json` configuration file.
2. The legacy `.agentic-backlog.json` file can be safely deleted without breaking the application.
3. Running the pipeline (e.g., `plan` or `apply`) makes zero network calls to GitHub APIs or external task management systems for the purpose of syncing issues or backlog states.
