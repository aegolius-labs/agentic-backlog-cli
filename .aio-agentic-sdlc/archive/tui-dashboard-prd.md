# Product Requirement Document (PRD)

## Feature
Real-time Terminal UI (TUI) Dashboard

## Summary
With the framework moving to an asynchronous, continuous background loop, users lose visibility into what the implementation swarms are doing. This feature will introduce a lightweight Terminal User Interface (TUI) that provides real-time visibility into the DAG state, active subagents, and pipeline progress, as well as an interactive interface for navigating the dynamic backlog without leaving the terminal.

## User Stories
- As a user interacting with the Intake Agent in one terminal pane, I want a TUI in another pane that shows me exactly what the background orchestrator and swarms are currently hacking on.
- As a developer, I want to see a live visual representation of the dynamically generated backlog (the DAG diff) and the status of parallel execution tasks.
- As a product manager or developer, I want to interactively navigate the backlog within the TUI to drill down into specific DAG nodes and review their requirements, dependencies, and current status.

## Requirements
- **TUI Framework**: Build an interactive terminal dashboard (e.g., using Textual for Python).
- **Tokenless Architecture**: The TUI MUST NOT make any LLM API calls. It MUST derive all its data locally from state files, DAGs, and agent logs, ensuring `agy-cli` users do not need a BYOK API token to use it.
- **Backlog Navigation**: The TUI MUST allow users to interactively scroll through, filter, and inspect the dynamically generated backlog (DAG diff), viewing detailed metadata, dependencies, and status for individual tasks.
- **Live Pipeline Status**: Display the current phase of the SDLC pipeline (Listening to Inbox -> Architecting -> Diffing -> Swarm Execution -> QA).
- **DAG Visualization**: Display a list or tree of unblocked tasks currently being worked on by parallel subagents.
- **Agent Logs Tail**: Provide a scrolling pane showing the latest top-level summary logs from active subagents.
- **Integration**: The TUI MUST run seamlessly alongside the daemon mode, pulling state from a shared local state file or socket.

## Out of Scope
- A full web-based GUI (React/Vue/etc.).
- Advanced editing of DAG nodes directly within the TUI (the TUI is for navigation and monitoring; structural changes remain driven by the Orchestrator/Architect).

## Acceptance Criteria
1. The TUI can be launched via `aio-sdlc ui` (or similar command) and renders a terminal dashboard.
2. The dashboard updates in near real-time as the background daemon processes tasks and updates the DAG.
3. The dashboard correctly identifies active subagents and their current tasks.
4. Users can use keyboard navigation to select specific tasks in the backlog and view their detailed metadata and dependencies.
