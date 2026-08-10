# Product Requirement Document (PRD)

## Feature
Intake Agent Deduplication and Overlap Checking

## Summary
The Intake Agent currently blindly generates new Product Requirement Documents (PRDs) based on user requests without verifying if similar features have already been requested or implemented. This leads to duplicate PRDs and overlapping scope. This feature explicitly mandates that the Intake Agent must perform deduplication and context-awareness checks against existing documents before generating new PRDs.

## User Stories
- As a framework maintainer, I want the Intake Agent to check existing PRDs before writing a new one, so the inbox doesn't get cluttered with duplicate requests.
- As a user, I want the Intake Agent to inform me if my idea overlaps with an existing or archived PRD, so we can either revise the existing one or cancel the redundant request.

## Requirements
- **Context Verification**: Before drafting any new PRD, the Intake Agent MUST scan both the `.aio-agentic-sdlc/inbox/` and `.aio-agentic-sdlc/archive/` directories.
- **Overlap Detection**: The agent MUST analyze the summaries of existing PRDs to determine if the user's current request overlaps with or duplicates an existing specification.
- **User Confirmation**: If an overlap is detected, the agent MUST pause and inform the user of the existing PRD, asking how they wish to proceed (e.g., merge requirements, abandon, or create a distinct PRD).
- **Instruction Update**: The `sdlc_intake` configuration (`.agents/agents/sdlc_intake/agent.md`) MUST be updated to explicitly encode this required behavior into its system instructions.

## Out of Scope
- Automated merging of PRDs without explicit user consent.

## Acceptance Criteria
1. The `sdlc_intake/agent.md` file contains explicit instructions to scan `.aio-agentic-sdlc/inbox/` and `.aio-agentic-sdlc/archive/` for duplicates before writing.
2. The Intake Agent successfully detects and warns the user about overlapping requests before writing a new file to the inbox.
