# Product Requirement Document (PRD)

## Feature
Operational Modes (Approval vs Bypass)

## Summary
The goal of this feature is to introduce user approval gates before merging code changes, while also supporting a "Bypass Approval" mode for fully autonomous continuous delivery. This allows for human-in-the-loop oversight when desired, and full automation when trusted.

## User Stories
- As a user, I want the system to pause and request my approval before merging any code, so I can review the changes for accuracy and safety.
- As a developer, I want to configure the system to bypass approvals for specific projects or tasks, enabling fully autonomous end-to-end execution.

## Requirements
- **Approval Gate**: The SDLC pipeline MUST pause execution and prompt the user via the orchestrator before completing a merge or final PR.
- **Bypass Configuration**: The system MUST support a flag, configuration, or operational mode (e.g., `--bypass-approval`) that skips the approval gate.
- **Resumption**: When paused, the system MUST resume execution successfully upon receiving user approval.
- **Rejection Handling**: If a user rejects the changes, the system MUST gracefully abort or route back to the appropriate agent for revisions.

## Out of Scope
- Complex role-based access control (RBAC) for approvals.
- Integration with external approval systems (e.g., Jira, ServiceNow).

## Acceptance Criteria
1. With approval mode active, the system halts before merging and waits for user input.
2. The user can approve the prompt to complete the merge.
3. The user can reject the prompt to abort or request changes.
4. With bypass mode active, the system completes the entire pipeline autonomously without pausing for user input.
