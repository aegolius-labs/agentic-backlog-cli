# Product Requirement Document (PRD)

## Feature
CLI Daemon / Watch Mode

## Summary
To support a continuous, asynchronous software factory workflow, the `aio-sdlc` CLI needs a long-running daemon mode. Instead of requiring manual `plan` and `apply` invocations, the daemon will monitor the workspace for file changes (specifically PRDs arriving in the `.aio-agentic-sdlc/inbox/`) and automatically trigger the Architect, Diffing, and Orchestrator pipelines in the background.

## User Stories
- As an enterprise user, I want to start the `aio-sdlc` engine in the background using my own API key (BYOK) so that it continuously processes PRDs on a headless server.
- As an `agy-cli` user, I want a simple `/command` or workflow inside my chat session that starts the background loop using my existing Google AI Pro subscription, so I do not need to provide a separate API token.
- As a system administrator, I want the CLI to react to file system events to efficiently process new requirements and update the DAGs continuously.

## Requirements
- **Daemon Command Structure (BYOK)**: For standalone executions, the CLI MUST support a daemon service pattern utilizing `aio-sdlc daemon start`, `aio-sdlc daemon stop`, and `aio-sdlc daemon restart`. This executes natively and requires a BYOK API token.
- **Antigravity CLI Integration (No-Token)**: To support `agy-cli` users, the framework MUST include an Antigravity **Skill** (e.g., `.agents/skills/sdlc-daemon/SKILL.md`). This allows users to type `/skill sdlc-daemon` or prompt the agent in chat to spawn a background Orchestrator subagent that uses their existing subscription to monitor the inbox.
- **File System Watcher**: When started, the daemon MUST monitor the `.aio-agentic-sdlc/inbox/` directory for new or modified markdown files.
- **Trigger Pipeline**: Upon detecting a new PRD, the daemon MUST trigger the `sdlc-architect-agent` to update the `.aio-agentic-sdlc/intention-dag.yaml`, calculate the new diff, and spawn the Orchestrator loop.
- **Resilience**: The daemon MUST gracefully handle errors (e.g., malformed PRDs) without crashing, logging the error and waiting for the next file change.
- **Concurrency Control**: The daemon MUST prevent overlapping pipeline executions if a previous pipeline run is still active.

## Out of Scope
- Distributed webhooks (this is purely local file-system watching).
- Real-time streaming of internal agent logs to external monitoring platforms.

## Acceptance Criteria
1. Running `aio-sdlc daemon start` launches the background watcher process successfully.
2. Dropping a new PRD into the `.aio-agentic-sdlc/inbox/` while the daemon is running automatically triggers the Architect and subsequent DAG processing.
3. The daemon can be gracefully terminated using `aio-sdlc daemon stop`.
4. The daemon does not crash when an agent encounters a failure, but logs it and continues watching.
